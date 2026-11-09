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
    def __init__(self, *, motion=None, poses_path=None, environ=None):
        env = os.environ if environ is None else environ  # Never read a .env file.
        self.cancelled = threading.Event()
        self.operation = threading.Lock()
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
        if self.cancelled.is_set():
            return robot_result(False, '정지 상태입니다. 직원 확인 후 부품을 다시 준비하세요')
        if self.error:
            return robot_result(False, self.error)
        if not isinstance(slot_id, str) or not re.fullmatch(r'R[1-4]-[12]', slot_id):
            return robot_result(False, '로봇 접근 가능한 보관 칸이 아닙니다')
        if not isinstance(pose_name, str) or not re.fullmatch(r'pose_[1-8]', pose_name) or pose_name not in self.poses:
            return robot_result(False, '저장된 사전 접근 자세가 없습니다')
        if not self.operation.acquire(blocking=False):
            return robot_result(False, '다른 로봇 명령이 진행 중입니다')
        try:
            if self.cancelled.is_set():
                return robot_result(False, '정지 요청으로 이동 취소')
            self.motion.move(pose_name, self.duration, self.cancelled)
            return robot_result(not self.cancelled.is_set(), '정지 요청으로 이동 취소')
        except Exception as exc:
            self.cancelled.set()  # Never resume automatically after an ambiguous failure.
            return robot_result(False, f'저장 자세 이동 실패: {str(exc)[:200]}')
        finally:
            self.operation.release()

    def robot_approach(self, center_mm, center_px) -> dict:
        return robot_result(False, '탑뷰 좌표 접근 미구현 — DB 칸 모드를 사용하세요')

    def run_pose_sequence_test(self, target) -> dict:
        """Explicit no-VLA test: DB pose -> outlet_return_1 -> close -> open -> return -> home.

        This is not the production robot_grasp/deliver contract and never marks
        a real item returned. Each move blocks until arrival before continuing.
        """
        from robot.db_pose_sequence import sequence_for_target
        completed = []
        sequence = []
        result = {'test_only': True, 'vla_skipped': True, 'item_id': target.get('item_id') if isinstance(target, dict) else None,
                  'completed': completed}
        try:
            sequence = sequence_for_target(target)
            result['sequence'] = sequence
            if self.cancelled.is_set() or self.error:
                raise ValueError(self.error or '정지 상태입니다. 직원 확인이 필요합니다')
            missing = [name for name in sequence if name not in self.poses]
            if missing:
                raise ValueError('시퀀스 저장 자세 없음: ' + ', '.join(missing))
        except Exception as exc:
            return {**robot_result(False, str(exc)), **result}
        if not self.operation.acquire(blocking=False):
            return {**robot_result(False, '다른 로봇 명령이 진행 중입니다'), **result}
        try:
            for pose in sequence:
                if self.cancelled.is_set():
                    raise InterruptedError('정지 요청으로 시퀀스 취소')
                self.motion.move(pose, self.duration, self.cancelled)
                if self.cancelled.is_set():
                    raise InterruptedError('정지 요청으로 시퀀스 취소')
                completed.append(pose)
            return {**robot_result(True), **result}
        except Exception as exc:
            stopped = self.robot_stop()
            reason = f'시험 시퀀스 중단: {str(exc)[:200]}'
            if not stopped['ok']:
                reason += ' · 정지 확인 실패'
            return {**robot_result(False, reason), **result,
                    'failed_pose': sequence[len(completed)], 'stop_confirmed': stopped['ok']}
        finally:
            self.operation.release()

    def robot_grasp(self) -> dict:
        return robot_result(False, '집기 학습 정책 미연결 — 사전 접근까지만 지원합니다')

    def robot_verify_grasp(self) -> dict:
        return robot_result(False, '실물 파지 검증 미구현 — 집기 성공으로 판정할 수 없습니다')

    def robot_deliver(self) -> dict:
        return robot_result(False, '집기·안전 높이 확인과 배출구 경로 검증이 필요합니다')

    def robot_home(self) -> dict:
        return robot_result(False, '직원 확인 후 Studio에서 검증한 원복 경로를 사용하세요')

    def robot_stop(self) -> dict:
        self.cancelled.set()  # Never wait for the movement lock to stop.
        try:
            return robot_result(bool(self.motion.stop()), 'Studio 정지 확인 실패 — 직원 확인 필요')
        except Exception as exc:
            return robot_result(False, f'Studio 정지 확인 실패: {str(exc)[:200]}')
