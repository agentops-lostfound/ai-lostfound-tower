"""DB target -> complete taught grasp/return sequence. No VLA is used.

The CLI runs an in-memory DB and simulated motors only. It never starts Studio
or changes a real item's status, assignment, or return record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agents.contracts import robot_result
from agents.storage import OUTLET_SEQUENCE, SLOT_NUMBERS


def sequence_for_target(target, *, sequence_path=None):
    if not isinstance(target, dict) or target.get('ok') is not True:
        raise ValueError('DB에서 사용할 수 있는 보관 칸을 받지 못했습니다')
    slot = target.get('slot_id')
    number = SLOT_NUMBERS.get(slot) if isinstance(slot, str) else None
    if number is None:
        raise ValueError('DB 칸이 로봇 보관 칸 1~8에 속하지 않습니다')
    pose = f'pose_{number}'
    if target.get('pose_name') != pose:
        raise ValueError('DB 칸 번호와 저장 자세 이름이 다릅니다')
    if 'number' in target and (type(target['number']) is not int or target['number'] != number):
        raise ValueError('DB 칸 번호가 일치하지 않습니다')
    if 'outlet_sequence' in target and target['outlet_sequence'] != list(OUTLET_SEQUENCE):
        raise ValueError('DB 배출구 순서가 시험 시퀀스와 다릅니다')
    path = Path(sequence_path) if sequence_path is not None else Path(__file__).with_name('config') / 'pick_sequences.json'
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(config, dict) or config.get('schema') != 'taught_pick_sequences.v1':
        raise ValueError('지원하지 않는 티칭 시퀀스 형식입니다')
    profiles = config.get('sequences')
    if not isinstance(profiles, dict):
        raise ValueError('티칭 시퀀스 목록이 없습니다')
    profile = profiles.get(pose + '_pick')
    if not isinstance(profile, dict) or profile.get('slot_id') != slot or profile.get('approach_pose') != pose:
        raise ValueError('DB 칸에 대응하는 티칭 시퀀스가 없습니다')
    returning = pose + '_return' if number in (7, 8) else pose
    names = [pose + '_open', pose + '_target', pose + '_close', returning]
    steps = profile.get('steps')
    if (not isinstance(steps, list) or len(steps) != 4
            or any(not isinstance(step, dict) for step in steps)
            or [step.get('pose_name') for step in steps] != names
            or any(step.get('captured') is not True or step.get('requires_reteach') for step in steps)):
        raise ValueError('집기 4단계의 티칭이 완료되지 않았거나 순서가 다릅니다')
    outlet = (['outlet_return_1_78', 'close_78', 'open', 'outlet_return_1_78', 'home']
              if number in (7, 8) else list(OUTLET_SEQUENCE))
    if profile.get('outlet_sequence', outlet) != outlet:
        raise ValueError('티칭 시퀀스의 배출구 순서가 다릅니다')
    sequence = ['home', pose, *names, *outlet]
    if profile.get('full_sequence', sequence) != sequence:
        raise ValueError('저장된 전체 시퀀스가 티칭 단계와 다릅니다')
    return sequence


def validate_taught_pose_values(sequence, poses):
    """Preflight all targets, including release without moving the outlet arm."""
    from robot.joint_motion import JOINTS, vector
    for name in sequence:
        if name not in poses:
            raise ValueError('시퀀스 저장 자세 없음: ' + name)
        vector(poses[name])
    closing = 'close_78' if 'close_78' in sequence else 'close'
    if any(poses['open'][joint + '.pos'] != poses[closing][joint + '.pos'] for joint in JOINTS[:5]):
        raise ValueError('open과 배출구 close의 팔 5축이 다릅니다. 같은 배출 위치로 맞추세요')
    if closing == 'close_78':
        number = 7 if 'pose_7_close' in sequence else 8
        names = [f'pose_{number}_close', f'pose_{number}_return', 'outlet_return_1_78', 'close_78']
        grip = poses[names[0]]['gripper.pos']
        if any(poses[name]['gripper.pos'] != grip for name in names):
            raise ValueError('7·8번 전용 복귀·운반의 그리퍼 목표가 다릅니다')


def trigger_db_sequence(item_id, target_lookup, robot):
    """Read the selected item once, then execute the explicit no-VLA test path.

    target_lookup is the tower's robot_target(item_id), not a client-supplied
    slot. This entry point is separate from the production return supervisor.
    """
    try:
        if not isinstance(item_id, str) or not item_id:
            raise ValueError('선택된 물건 번호가 필요합니다')
        target = target_lookup(item_id)
        if not isinstance(target, dict) or target.get('item_id') != item_id:
            raise ValueError('조회한 DB 물건 번호가 요청과 다릅니다')
        sequence_for_target(target)
    except Exception as exc:
        return {**robot_result(False, f'DB 시험 트리거 실패: {str(exc)[:200]}'),
                'test_only': True, 'vla_skipped': True, 'completed': []}
    try:
        return robot.run_pose_sequence_test(target)
    except Exception as exc:
        return {**robot_result(False, f'시험 시퀀스 실행 실패: {str(exc)[:200]}'),
                'test_only': True, 'vla_skipped': True, 'completed': []}


class SimulatedPoseMotion:
    """Exercise the existing interpolation/arrival logic with ideal motor feedback."""
    def __init__(self, poses):
        import numpy as np
        from robot.joint_motion import vector
        from robot.phone_carry import augmented_poses
        self.poses, self.profiles = augmented_poses(poses)
        self.current = np.array(vector(poses['home']), dtype=float)
        self.time = 0.0
        self.events = []
        self.stop_count = 0

    def move(self, pose, duration, cancelled):
        from robot.joint_motion import vector
        from robot.studio_extension.runtime.saved_pose import PoseMove
        start = self.time
        token = f'sim-{len(self.events)}'
        profile = self.profiles.get(pose)
        move = PoseMove(self.current, vector(self.poses[pose]), self.time, token, duration,
            arrival_target=vector(self.poses[profile['reference_pose']]) if profile else None,
            shoulder_tolerance=profile['shoulder_tolerance'] if profile else 5)
        self.events.append({'event': 'requested', 'pose': pose, 'time': round(self.time, 3)})
        while True:
            if cancelled.is_set():
                raise InterruptedError('모의 이동 취소')
            self.time += 0.05
            move.heartbeat(token, self.time)
            command, arrived = move.tick(self.current, self.time)
            self.current = command.copy()
            if arrived:
                self.events.append({'event': 'arrived', 'pose': pose, 'time': round(self.time, 3),
                                    'elapsed': round(self.time - start, 3)})
                return

    def stop(self):
        self.stop_count += 1
        self.events.append({'event': 'stop', 'time': round(self.time, 3)})
        return True


def simulate_trigger(slot_id, poses_path, seconds=3):
    from agents.storage import LAYOUT, MemoryStorageStore, SLOT_POSES, robot_target
    from robot.tower_part import TowerRobot
    poses_path = Path(poses_path)
    poses = json.loads(poses_path.read_text(encoding='utf-8-sig'))
    item_id = 'A-20990101-0001'  # Fictional fixture; no real DB connection.
    section = next((row for row in LAYOUT if row[0] == slot_id.split('-')[0]), None)
    if section is None or slot_id not in SLOT_NUMBERS:
        raise ValueError('시험 칸은 R1-1~R4-2 중 하나여야 합니다')
    category = section[3][0]
    items = {item_id: {'item_id': item_id, 'status': '본센터 보관', 'category': category}}
    db = MemoryStorageStore(item_lookup=items.get, poses=SLOT_POSES)
    db.assign(item_id, slot_id)
    target = robot_target(db.layout(), item_id)
    motion = SimulatedPoseMotion(poses)
    robot = TowerRobot(motion=motion, poses_path=poses_path,
                       environ={'TOWER_ROBOT_MOVE_SECONDS': str(seconds)})
    def lookup(identity):
        motion.events.append({'event': 'db_target_lookup', 'item_id': identity,
                              'time': round(motion.time, 3)})
        return robot_target(db.layout(), identity)
    result = trigger_db_sequence(item_id, lookup, robot)
    return {**result, 'simulation': True, 'control_mode': 'taught', 'grasp_included': True,
            'db_source': 'memory', 'target': target,
            'hardware_commands': 0, 'events': motion.events,
            'final_item_status': items[item_id]['status'],
            'poses_sha256': hashlib.sha256(poses_path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate', action='store_true', help='In-memory DB and simulated motors only')
    parser.add_argument('--slot', choices=tuple(SLOT_NUMBERS), default='R3-2')
    parser.add_argument('--seconds', type=int, choices=(3, 4, 5), default=3)
    parser.add_argument('--poses', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'outputs/robot_panel_live/poses.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.simulate:
        parser.error('이 CLI는 모의 시험 전용입니다. --simulate를 지정하세요.')
    result = simulate_trigger(args.slot, args.poses, args.seconds)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
