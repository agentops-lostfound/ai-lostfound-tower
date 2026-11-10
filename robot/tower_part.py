"""LF-21: DB target -> Studio saved approach. Construction never connects hardware."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading

from agents.contracts import robot_result
from robot.joint_motion import JOINTS, vector
from robot.studio_pose_transport import StudioPoseTransport


class TowerRobot:
    def __init__(self, *, motion=None, poses_path=None, environ=None, grasp_policy=None):
        env = os.environ if environ is None else environ  # Never read a .env file.
        self.cancelled = threading.Event()
        self.operation = threading.Lock()
        self.grasp_policy = grasp_policy
        self._approach = None
        self.poses = {}
        self.error = ''
        try:
            self.duration = int(env.get('TOWER_ROBOT_MOVE_SECONDS', '3'))
            if self.duration not in (3, 4, 5):
                raise ValueError('이동 시간은 3·4·5초 중 하나여야 합니다')
            path = Path(poses_path or env.get('TOWER_ROBOT_POSES') or
                        Path(__file__).resolve().parents[1] / 'outputs/robot_panel_live/poses.json')
            poses = json.loads(path.read_text(encoding='utf-8-sig'))
            self.poses = {name: dict(values) for name, values in poses.items()}
            for values in self.poses.values():
                if set(values) != {name + '.pos' for name in JOINTS}:
                    raise ValueError('저장 자세는 정확히 6축이어야 합니다')
                vector(values)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.error = f'저장 자세·설정 확인 필요: {type(exc).__name__}'
        self.motion = motion or StudioPoseTransport(
            env.get('TOWER_STUDIO_FOLLOWER_ID', ''),
            env.get('TOWER_STUDIO_CONTAINER', 'physical-ai-studio-cuda'),
            env.get('TOWER_STUDIO_DISTRIBUTION', 'Ubuntu-24.04'))

    def robot_go_pose(self, pose_name: str, slot_id: str) -> dict:
        if not self.operation.acquire(blocking=False):
            return robot_result(False, '다른 로봇 명령이 진행 중입니다')
        try:
            self._approach = None
            if self.cancelled.is_set():
                return robot_result(False, '정지 요청으로 이동 취소')
            if self.error:
                return robot_result(False, self.error)
            if not isinstance(slot_id, str) or not re.fullmatch(r'R[1-4]-[12]', slot_id):
                return robot_result(False, '로봇 접근 가능한 보관 칸이 아닙니다')
            if not isinstance(pose_name, str) or not re.fullmatch(r'pose_[1-8]', pose_name) or pose_name not in self.poses:
                return robot_result(False, '저장된 사전 접근 자세가 없습니다')
            number = (int(slot_id[1]) - 1) * 2 + int(slot_id[3])
            if pose_name != f'pose_{number}':
                return robot_result(False, 'DB 칸 번호와 저장 자세 이름이 다릅니다')
            self.motion.move(pose_name, self.duration, self.cancelled)
            if not self.cancelled.is_set():
                self._approach = (pose_name, slot_id)
            return robot_result(not self.cancelled.is_set(), '정지 요청으로 이동 취소')
        except Exception as exc:
            self.cancelled.set()  # Never resume automatically after an ambiguous failure.
            return robot_result(False, f'저장 자세 이동 실패: {str(exc)[:200]}')
        finally:
            self.operation.release()

    def robot_approach(self, center_mm, center_px) -> dict:
        return robot_result(False, '탑뷰 좌표 접근 미구현 — DB 칸 모드를 사용하세요')

    def run_pose_sequence_test(self, target) -> dict:
        """Complete taught sequence test: home -> approach -> pick -> outlet -> home.

        This is not the production robot_grasp/deliver contract and never marks
        a real item returned. Each move blocks until arrival before continuing.
        """
        return self._run_taught_sequence(target, test_only=True)

    def robot_run_sequence(self, target, progress=None) -> dict:
        """Tower-approved route; motion completion is not physical grasp verification."""
        return self._run_taught_sequence(target, progress=progress, test_only=False)

    def _run_taught_sequence(self, target, *, progress=None, test_only):
        from robot.db_pose_sequence import sequence_for_target, validate_taught_pose_values
        completed = []
        sequence = []
        result = {'test_only': test_only, 'vla_skipped': True, 'control_mode': 'taught', 'grasp_included': True,
                  'verification_required': True,
                  'item_id': target.get('item_id') if isinstance(target, dict) else None,
                  'completed': completed}
        try:
            sequence = sequence_for_target(target)
            result['sequence'] = sequence
            if self.cancelled.is_set() or self.error:
                raise ValueError(self.error or '정지 상태입니다. 직원 확인이 필요합니다')
            missing = [name for name in sequence if name not in self.poses]
            if missing:
                raise ValueError('시퀀스 저장 자세 없음: ' + ', '.join(missing))
            validate_taught_pose_values(sequence, self.poses)
            from robot.phone_carry import execution_plan
            commands, _, profiles = execution_plan(sequence, self.poses)
            result['command_sequence'] = commands
            result['motion_profiles'] = profiles
        except Exception as exc:
            return {**robot_result(False, str(exc)), **result}
        if not self.operation.acquire(blocking=False):
            return {**robot_result(False, '다른 로봇 명령이 진행 중입니다'), **result}
        try:
            self._approach = None  # A test route is not a production grasp start.
            for index, (pose, command_pose) in enumerate(zip(sequence, commands), 1):
                if self.cancelled.is_set():
                    raise InterruptedError('정지 요청으로 시퀀스 취소')
                event = {'index': index, 'total': len(sequence), 'pose_name': pose,
                         'command_pose': command_pose}
                if progress:
                    progress({**event, 'event': 'stage_started'})
                self.motion.move(command_pose, self.duration, self.cancelled)
                if self.cancelled.is_set():
                    raise InterruptedError('정지 요청으로 시퀀스 취소')
                completed.append(pose)
                if progress:
                    progress({**event, 'event': 'stage_arrived'})
            return {**robot_result(True), **result, 'motion_complete': True}
        except Exception as exc:
            stopped = self.robot_stop()
            reason = f'시험 시퀀스 중단: {str(exc)[:200]}'
            if not stopped['ok']:
                reason += ' · 정지 확인 실패'
            return {**robot_result(False, reason), **result,
                    'failed_pose': sequence[min(len(completed), len(sequence) - 1)],
                    'motion_complete': False, 'stop_confirmed': stopped['ok']}
        finally:
            self.operation.release()

    def robot_grasp(self) -> dict:
        """Policy closes at the target; saved-pose control returns to the approach.

        The injected policy(approach_pose=..., slot_id=..., cancelled=Event)
        must return {ok: True, control_released: True} only after grasp motion
        ends and Studio is in HOLD with the last gripper command preserved.
        This is not proof that an object was grasped; verification is separate.
        No adapter is installed or enabled by default.
        """
        if not self.operation.acquire(blocking=False):
            return robot_result(False, '다른 로봇 명령이 진행 중입니다')
        try:
            if self.cancelled.is_set() or self.error:
                return robot_result(False, self.error or '정지 상태입니다. 직원 확인이 필요합니다')
            if not callable(self.grasp_policy):
                return robot_result(False, '집기 학습 정책 미연결 — 사전 접근까지만 지원합니다')
            if self._approach is None:
                return robot_result(False, 'DB 칸의 사전 접근 도착 확인이 먼저 필요합니다')
            pose, slot = self._approach
            self._approach = None  # Consume once; never repeat a grasp after an uncertain outcome.
            try:
                result = self.grasp_policy(approach_pose=pose, slot_id=slot, cancelled=self.cancelled)
                if self.cancelled.is_set():
                    raise InterruptedError('정지 요청으로 집기 취소')
                if not isinstance(result, dict) or result.get('ok') is not True:
                    raise ValueError('VLA 집기 동작 완료를 확인하지 못했습니다')
                if result.get('control_released') is not True:
                    raise ValueError('VLA 제어 종료·HOLD 전환을 확인하지 못했습니다')
                # Studio also requires HOLD and fresh observations before accepting this move.
                # Preserve commanded closure, not the measured opening around a held object.
                self.motion.move(pose, self.duration, self.cancelled, include_gripper=False)
                if self.cancelled.is_set():
                    raise InterruptedError('정지 요청으로 어프로치 복귀 취소')
                return robot_result(True)
            except Exception as exc:
                stopped = self.robot_stop()
                reason = f'집기·어프로치 복귀 중단: {str(exc)[:200]}'
                if not stopped['ok']:
                    reason += ' · 정지 확인 실패'
                return robot_result(False, reason)
        finally:
            self.operation.release()

    def robot_verify_grasp(self) -> dict:
        return robot_result(False, '실물 파지 검증 미구현 — 집기 성공으로 판정할 수 없습니다')

    def robot_deliver(self) -> dict:
        return robot_result(False, '집기·안전 높이 확인과 배출구 경로 검증이 필요합니다')

    def robot_home(self) -> dict:
        return robot_result(False, '직원 확인 후 Studio에서 검증한 원복 경로를 사용하세요')

    def robot_stop(self) -> dict:
        self.cancelled.set()  # Never wait for the movement lock to stop.
        self._approach = None
        try:
            return robot_result(bool(self.motion.stop()), 'Studio 정지 확인 실패 — 직원 확인 필요')
        except Exception as exc:
            return robot_result(False, f'Studio 정지 확인 실패: {str(exc)[:200]}')
