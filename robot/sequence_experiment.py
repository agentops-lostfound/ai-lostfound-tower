"""User-operated sequence experiment state. No automatic hardware startup."""
from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import threading
import time

from robot.db_pose_sequence import sequence_for_target
from robot.joint_motion import JOINTS, vector
from robot.tower_part import TowerRobot


class AnimatedSimulation:
    def __init__(self, poses, observe):
        import numpy as np
        self.poses, self.observe = poses, observe
        self.current = np.array(vector(poses['home']), dtype=float)

    def move(self, pose, duration, cancelled):
        from robot.studio_extension.runtime.saved_pose import PoseMove
        token = 'sequence-panel-simulation'
        move = PoseMove(self.current, vector(self.poses[pose]), time.monotonic(), token, duration)
        while True:
            if cancelled.is_set():
                raise InterruptedError('정지 요청')
            now = time.monotonic()
            move.heartbeat(token, now)
            command, arrived = move.tick(self.current, now)
            self.current = command.copy()
            self.observe({'event': 'observation', 'data': dict(zip((n + '.pos' for n in JOINTS), map(float, self.current))),
                          'actions': dict(zip((n + '.pos' for n in JOINTS), map(float, command)))})
            if arrived:
                return
            time.sleep(0.02)

    def stop(self):
        return True


class SequenceExperiment:
    def __init__(self, poses_path, *, live=False, motion=None, log_path=None, lease_seconds=None):
        self.lock = threading.RLock()
        self.poses_path = Path(poses_path)
        self.live, self.motion = live, motion
        self.log_path = Path(log_path) if log_path else None
        self.lease_seconds = lease_seconds
        self.last_ui = time.monotonic()
        self.events = deque(maxlen=80)
        self.closed = threading.Event()
        self.running = self.stopping = self.halted = False
        self.connected = not live
        self.message = '실물 연결 전' if live else '모의 모드 · 단계 선택 후 실행하세요'
        self.joints, self.actions, self.runtime_state = {}, {}, {}
        self.last_packet = None
        self.worker = self.stop_worker = None
        self.selected = 0
        self.seen_motion = False
        self.source = '수동 시험'
        self.prepare('R1-1', 5)
        if lease_seconds is not None:
            threading.Thread(target=self._watch_lease, daemon=True).start()

    def _record(self, event, **data):
        row = {'time': time.time(), 'event': event, 'live': self.live, 'vla_skipped': True, **data}
        with self.lock:
            self.events.append(row)
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    def prepare(self, slot, seconds, target=None):
        with self.lock:
            if self.running or self.stopping:
                raise ValueError('실행·정지가 끝난 뒤 다시 준비하세요')
            if type(seconds) is not int or seconds not in (3, 4, 5):
                raise ValueError('이동 시간은 3·4·5초 중에서 선택하세요')
            if target is None:
                from agents.storage import SLOT_NUMBERS
                if slot not in SLOT_NUMBERS:
                    raise ValueError('시험 칸을 선택하세요')
                target = {'ok': True, 'slot_id': slot, 'number': SLOT_NUMBERS[slot],
                          'pose_name': f'pose_{SLOT_NUMBERS[slot]}'}
                source = '수동 시험'
            else:
                target = dict(target)
                source = 'DB 응답 · ' + str(target.get('item_id') or '물건 ID 없음')
            plan = sequence_for_target(target)
            # Passing a placeholder prevents even lazy transport construction.
            robot = TowerRobot(motion=object(), poses_path=self.poses_path,
                               environ={'TOWER_ROBOT_MOVE_SECONDS': str(seconds)})
            if robot.error:
                raise ValueError(robot.error)
            if any(pose not in robot.poses for pose in plan):
                raise ValueError('시퀀스에 필요한 저장 자세가 없습니다')
            if self.motion is None:
                if self.live:
                    raise ValueError('실물 transport 설정이 필요합니다')
                self.motion = AnimatedSimulation(robot.poses, self.observe)
            elif isinstance(self.motion, AnimatedSimulation):
                self.motion.poses = robot.poses
            robot.motion = self.motion
            self.robot, self.plan, self.target = robot, plan, target
            self.seconds, self.source = seconds, source
            self.statuses = ['대기'] * len(plan)
            self.selected = 0
            self.halted = False
            self.message = '준비됨 · 경로를 확인한 뒤 실행하세요'
            self._record('prepared', sequence=plan, slot_id=target['slot_id'], profile_seconds=seconds, source=source)

    def mark_ui_alive(self):
        self.last_ui = time.monotonic()

    def _watch_lease(self):
        while not self.closed.wait(0.2):
            if self.running and time.monotonic() - self.last_ui > self.lease_seconds:
                self.request_stop('시험 화면 연결이 끊겨 정지 요청')

    def observe(self, row):
        stopped = False
        with self.lock:
            if row.get('event') == 'observation':
                data = row.get('data') or {}
                if set(data) == {n + '.pos' for n in JOINTS}:
                    self.joints = dict(data)
                    self.actions = dict(row.get('actions') or {})
                    self.last_packet = time.monotonic()
            elif row.get('event') == 'state':
                self.runtime_state = dict(row.get('data') or {})
                status = self.runtime_state.get('saved_pose_status')
                if self.running:
                    if status in ('moving', 'holding_target'):
                        self.seen_motion = True
                    stopped = (self.seen_motion and status in ('stopped', 'error')) or not self.runtime_state.get('connected')
        if stopped:
            self.request_stop('Studio에서 이동 중단 상태를 수신했습니다')

    def set_connected(self, connected, message):
        with self.lock:
            self.connected = connected
            if not self.running:
                self.message = message

    def start(self, mode, index, approved):
        with self.lock:
            if approved is not True:
                raise ValueError('빈 집게·이동 경로 확인을 체크하세요')
            if self.running or self.stopping:
                raise ValueError('이미 실행·정지 중입니다')
            if self.halted:
                raise ValueError('정지 후에는 다시 준비를 누르세요')
            if self.live and (not self.connected or self.last_packet is None or time.monotonic() - self.last_packet > 1):
                raise ValueError('먼저 Studio 수신 연결을 확인하세요')
            if self.live and (self.runtime_state.get('follower_source') != 'hold' or self.runtime_state.get('is_recording')):
                raise ValueError('Studio를 HOLD·녹화 꺼짐 상태로 준비하세요')
            if self.live and not set(self.plan).issubset(self.runtime_state.get('saved_pose_names', [])):
                raise ValueError('Studio에 필요한 저장 자세가 없습니다')
            if mode not in ('step', 'all') or type(index) is not int or not 0 <= index < len(self.plan):
                raise ValueError('실행할 단계를 선택하세요')
            if self.lease_seconds is not None and time.monotonic() - self.last_ui > self.lease_seconds:
                raise ValueError('시험 화면 연결을 확인하세요')
            indices = list(range(len(self.plan))) if mode == 'all' else [index]
            if mode == 'all':
                self.statuses = ['대기'] * len(self.plan)
            self.running = True
            self.seen_motion = False
            self.worker = threading.Thread(target=self._run, args=(indices,), daemon=True)
            self.worker.start()

    def _run(self, indices):
        current = indices[0]
        try:
            for current in indices:
                if self.robot.cancelled.is_set():
                    raise InterruptedError('정지 요청')
                with self.lock:
                    self.selected = current
                    self.statuses[current] = '도착 대기'
                    self.message = f'{self.plan[current]} 이동·도착 대기'
                    self._record('stage_start', index=current, pose=self.plan[current])
                self.motion.move(self.plan[current], self.seconds, self.robot.cancelled)
                if self.robot.cancelled.is_set():
                    raise InterruptedError('정지 요청')
                with self.lock:
                    self.statuses[current] = '도착'
                    self._record('stage_arrived', index=current, pose=self.plan[current], joints=self.joints)
            with self.lock:
                self.selected = min(current + 1, len(self.plan) - 1)
                self.message = '전체 시퀀스 완료' if len(indices) == len(self.plan) else '선택 단계 완료 · 다음 단계를 선택할 수 있습니다'
        except Exception as exc:
            with self.lock:
                self.statuses[current] = '중단'
                self.message = str(exc)[:240]
                self._record('stage_failed', index=current, pose=self.plan[current], reason=self.message)
            self.request_stop(self.message)
        finally:
            with self.lock:
                self.running = False

    def request_stop(self, reason='사용자 정지 요청'):
        self.robot.cancelled.set()
        with self.lock:
            self.halted = True
            self.message = reason
            if self.stopping:
                return
            self.stopping = True
            self._record('stop_requested', reason=reason)
            self.stop_worker = threading.Thread(target=self._stop, daemon=True)
            self.stop_worker.start()

    def _stop(self):
        result = self.robot.robot_stop()
        with self.lock:
            self.stopping = False
            self._record('stop_response', result=result)
            self.message = 'HOLD 상태 응답 수신 · 다시 준비 후 실행하세요' if result['ok'] else '정지 미확인 · Studio에서 상태를 확인하세요'

    def snapshot(self):
        with self.lock:
            goal = self.robot.poses[self.plan[self.selected]]
            return {'live': self.live, 'connected': self.connected, 'running': self.running,
                    'stopping': self.stopping, 'halted': self.halted, 'message': self.message,
                    'sequence': list(self.plan), 'statuses': list(self.statuses), 'selected': self.selected,
                    'slot_id': self.target['slot_id'], 'seconds': self.seconds, 'source': self.source,
                    'joints': dict(self.joints), 'actions': dict(self.actions), 'target': dict(goal),
                    'targets': [dict(self.robot.poses[name]) for name in self.plan],
                    'packet_age': None if self.last_packet is None else round(time.monotonic() - self.last_packet, 2),
                    'runtime_state': dict(self.runtime_state), 'events': list(self.events)}

    def close(self):
        self.closed.set()
        if self.running or self.stopping:
            self.request_stop('시험 도구 종료')
            if self.worker:
                self.worker.join(4)
            if self.stop_worker:
                self.stop_worker.join(4)
