"""Attach to an existing Studio runtime; never open a serial port or start a session."""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
import queue
import subprocess
import uuid


class RuntimePipe:
    def __init__(self, follower, container, distribution):
        code = Path(__file__).with_name('studio_pose_worker.py').read_text(encoding='utf-8')
        self.process = subprocess.Popen([
            'wsl.exe', '-d', distribution, '--', 'docker', 'exec', '-i',
            '-e', 'PYTHONPATH=/app/application/backend/src', container,
            '/app/application/backend/.venv/bin/python', '-u', '-c', code, follower,
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.messages = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.messages.put({'event': 'error', 'message': 'Studio worker disconnected'})

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def receive(self):
        try:
            return self.messages.get(timeout=0.1)
        except queue.Empty:
            return None

    def close(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass  # Detach failure is not proof of HOLD. Never kill Studio.


class StudioPoseTransport:
    def __init__(self, follower, container='physical-ai-studio-cuda', distribution='Ubuntu-24.04', *,
                 socket_factory=RuntimePipe, clock=time.monotonic):
        self.follower, self.container, self.distribution = follower, container, distribution
        self.socket_factory, self.clock = socket_factory, clock
        self.lock = threading.RLock()
        self.socket = None
        self.stop_confirmed = threading.Event()
        self.stop_requested = threading.Event()

    def _open(self):
        self.follower = str(uuid.UUID(self.follower))
        return self.socket_factory(self.follower, self.container, self.distribution)

    def _send(self, sock, event, data=None):
        with self.lock:
            sock.send({'event': event, 'data': data or {}})

    def _ready(self, sock, pose=None, cancelled=None):
        deadline = self.clock() + 10  # Worker attachment only, not an arrival deadline.
        state, observed = None, None
        while self.clock() < deadline:
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError('정지 요청으로 이동 취소')
            message = sock.receive()
            if not message:
                continue
            if message.get('event') == 'error':
                raise ValueError(message.get('message', 'Studio 오류'))
            if message.get('event') == 'observation':
                self._check_observation(message)
                observed = self.clock()
            if message.get('event') == 'state':
                state = message.get('data') or {}
            if state and state.get('connected') and observed is not None and self.clock() - observed <= 0.5:
                if pose is not None:
                    if state.get('follower_source') != 'hold' or state.get('is_recording'):
                        raise ValueError('녹화를 끄고 Studio를 HOLD로 전환하세요')
                    if state.get('saved_pose_status') in ('moving', 'holding_target'):
                        raise ValueError('다른 저장 자세 이동이 진행 중입니다')
                    if state.get('saved_pose_robot_id') != self.follower or pose not in state.get('saved_pose_names', []):
                        raise ValueError('Studio에 해당 팔의 저장 자세가 없습니다')
                return
        raise ValueError('Studio 연결·관측을 확인하지 못했습니다')

    @staticmethod
    def _check_observation(message):
        from robot.joint_motion import JOINTS
        data = message.get('data') or {}
        if set(data) != {name + '.pos' for name in JOINTS} or not all(
                type(v) in (int, float) and math.isfinite(v) for v in data.values()):
            raise ValueError('Studio 관절 관측이 올바르지 않습니다')

    def _confirm_stop(self, sock, timeout=2.0):
        # A broadcast may be old or deduplicated. The worker queries current
        # runtime metadata after publication and tags its answer with this ID.
        request_id = str(uuid.uuid4())
        self._send(sock, 'stop_saved_pose', {'request_id': request_id})
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            message = sock.receive()
            if (message and message.get('event') == 'stop_result'
                    and message.get('request_id') == request_id):
                if message.get('ok') is True:
                    self.stop_confirmed.set()
                    return True
                return False
        return False

    def move(self, pose, duration, cancelled, *, include_gripper=True):
        if type(include_gripper) is not bool:
            raise ValueError('include_gripper must be a boolean')
        sock = self._open()
        sent = False
        try:
            self._ready(sock, pose, cancelled)
            token = str(uuid.uuid4())
            with self.lock:
                if cancelled.is_set():
                    raise InterruptedError('정지 요청으로 이동 취소')
                self.stop_confirmed.clear()
                self.stop_requested.clear()
                self.socket = sock
                sent = True  # A write/flush error can occur after command delivery.
                self._send(sock, 'move_saved_pose', {
                    'pose': pose, 'follower_id': self.follower, 'token': token,
                    'approved': True, 'return_to_approach': False,
                    'include_gripper': include_gripper, 'duration_seconds': duration})
            last_observation = self.clock()
            heartbeat_at = self.clock()
            requested_at = self.clock()
            accepted = False
            # The selected 3/4/5 seconds is interpolation, never an arrival deadline.
            while True:
                if cancelled.is_set() or self.stop_requested.is_set():
                    raise InterruptedError('정지 요청으로 이동 취소')
                now = self.clock()
                if not accepted and now - requested_at > 2:
                    raise ValueError('Studio가 저장 자세 명령을 수락하지 않았습니다')
                if now - last_observation > 0.5:
                    raise ValueError('Studio 관측 갱신이 중단됐습니다')
                if now - heartbeat_at >= 0.2:
                    self._send(sock, 'saved_pose_heartbeat', {'token': token})
                    heartbeat_at = now
                message = sock.receive()
                if not message:
                    continue
                event = message.get('event')
                if event == 'observation':
                    self._check_observation(message)
                    last_observation = self.clock()
                elif event == 'error':
                    raise ValueError(message.get('message', 'Studio 이동 오류'))
                elif event == 'state':
                    state = message.get('data') or {}
                    if not state.get('connected') or state.get('follower_source') != 'hold' or state.get('is_recording'):
                        raise ValueError('Studio 제어 상태가 변경됐습니다')
                    status = state.get('saved_pose_status')
                    if status in ('error', 'stopped'):
                        raise ValueError(state.get('saved_pose_error') or 'Studio 이동 중단')
                    if status in ('moving', 'holding_target'):
                        if state.get('saved_pose_token') != token or state.get('saved_pose_name') != pose:
                            raise ValueError('다른 클라이언트가 저장 자세 제어를 변경했습니다')
                        accepted = True
                    if accepted and status == 'arrived' and state.get('saved_pose_name') == pose:
                        with self.lock:
                            if cancelled.is_set() or self.stop_requested.is_set():
                                raise InterruptedError('정지 요청으로 이동 취소')
                            # Linearize completion against a concurrent stop. A
                            # later stop opens its own pipe rather than waiting
                            # on a receiver that has already returned.
                            self.socket = None
                        return
        except Exception as exc:
            if sent:
                confirmed = False
                try:
                    confirmed = self._confirm_stop(sock)
                except Exception:
                    pass
                if not confirmed:
                    raise RuntimeError(f'{exc}; Studio 정지 확인 실패 — 직원 확인 필요') from exc
            raise
        finally:
            with self.lock:
                self.socket = None
            sock.close()  # Detach only; do not send disconnect/restart/teleop.

    def stop(self):
        with self.lock:
            sock = self.socket
            if sock is not None:
                # The move thread remains the only receiver for this pipe.
                self.stop_requested.set()
        if sock is not None:
            return self.stop_confirmed.wait(3)
        sock = self._open()
        try:
            self.stop_confirmed.clear()
            # A stop must remain possible when joint observations have stalled.
            # The worker attaches before reading this buffered command.
            return self._confirm_stop(sock, timeout=10.0)
        finally:
            sock.close()
