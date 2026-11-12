import json
import numpy as np
from .config import DATA
from .robot_frame import load

def at_target(plan):
    path=DATA/'local_grasp_correction.json'
    if not path.exists():return None
    c=json.loads(path.read_text(encoding='utf-8'))
    if c['frame']!=load():raise ValueError('로컬 집기 보정의 보관함 기준이 변경되었습니다.')
    if np.linalg.norm(np.asarray(plan['board_mm'])-c['anchor_board_mm'])>c['radius_mm']:return None
    return c

def offset(plan,state):
    c=at_target(plan)
    if c is None:return None
    by={j['name']:j for j in state['joints']}
    if abs(by['wrist_roll']['raw_ticks']-c['anchor_roll_ticks'])>c['roll_tolerance_ticks']:
        raise ValueError('실측 지점의 손목 방향이 달라 로컬20mm 보정을 적용할 수 없습니다.')
    if not c['gripper_normalized_range'][0]<=by['gripper']['normalized']<=c['gripper_normalized_range'][1]:
        raise ValueError('로컬20mm 보정은 집게50%개방 부근 전용입니다.')
    return c
