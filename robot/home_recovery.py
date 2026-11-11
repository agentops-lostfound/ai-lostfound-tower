"""Plan an explicitly requested empty-gripper return using existing taught waypoints."""
import re

from robot.joint_motion import JOINTS, vector


def at_home(snapshot, poses):
    state, positions = snapshot['state'], snapshot['positions']
    vector(positions)
    vector(poses['home'])
    return (state.get('connected') is True and state.get('follower_source') == 'hold'
            and not state.get('is_recording')
            and state.get('saved_pose_status') not in ('moving', 'holding_target')
            and all(abs(positions[key]-poses['home'][key]) <= 2 for key in poses['home']))


def home_path(snapshot, poses):
    state, positions = snapshot['state'], snapshot['positions']
    vector(positions)
    vector(poses['home'])
    if (not state.get('connected') or state.get('follower_source') != 'hold'
            or state.get('is_recording') or state.get('saved_pose_status') in ('moving', 'holding_target')):
        raise ValueError('HOLD·정지·녹화 꺼짐을 확인한 뒤 복귀하세요')
    arm = [name + '.pos' for name in JOINTS[:5]]
    if all(abs(positions[key]-poses['home'][key]) <= 2 for key in arm):
        return ['home']
    name = state.get('saved_pose_name') or ''
    if name.endswith('_phone'):
        name = name[:-6]
    match = re.fullmatch(r'(pose_[1-8])(?:_open|_target|_close)?', name)
    if match:
        approach = match[1]
        references = [poses[key] for key in (approach, approach+'_open', approach+'_target', approach+'_close')]
    elif name in ('outlet_return_1', 'close', 'open'):
        approach = 'outlet_return_1'
        references = [poses[key] for key in ('outlet_return_1', 'close', 'open')]
    else:
        raise ValueError('현재 자세의 복귀 경로를 확인할 수 없습니다 — 로컬 확인 필요')
    # Recognition guard only; does not alter saved targets or arrival tolerances.
    for reference in references:
        vector(reference)
    if any(not min(row[key] for row in references)-8 <= positions[key] <= max(row[key] for row in references)+8
           for key in arm):
        raise ValueError('현재 관절이 해당 티칭 구간 밖입니다 — 임의로 홈 이동하지 않습니다')
    return [approach, 'home']
