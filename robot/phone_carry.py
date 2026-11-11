"""Bounded fixed carry commands for phone-like loads; preserve original teaching."""
from __future__ import annotations

import json
import math
from pathlib import Path

from robot.joint_motion import vector

ALIASES = {
    'pose_1_phone': 'pose_1', 'pose_2_phone': 'pose_2',
    'pose_3_phone': 'pose_3',
    'pose_7_return_phone': 'pose_7_return',
    'outlet_return_1_phone': 'outlet_return_1',
    'outlet_return_1_78_phone': 'outlet_return_1_78',
    'close_78_phone': 'close_78',
    'close_phone': 'close', 'open_phone': 'open',
}


def load_config(path=None):
    path = Path(path) if path else Path(__file__).with_name('config') / 'phone_carry.json'
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if (config.get('schema') != 'phone_carry.v1' or type(config.get('enabled')) is not bool
            or config.get('slots') != ['R1-1', 'R1-2', 'R2-1', 'R4-1']):
        raise ValueError('휴대폰 운반 보정 설정 형식이 다릅니다')
    for key, low, high in [('shoulder_offset_normalized', -3, 0),
                           ('shoulder_arrival_tolerance_normalized', 5, 8)]:
        value = config.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('휴대폰 운반 보정값이 제한 범위를 벗어났습니다')
    return config


def augmented_poses(poses, config=None):
    """Derive carry aliases and their separate original arrival references."""
    config = load_config() if config is None else config
    # Validate even programmatically supplied configuration before generating motion.
    offset = config['shoulder_offset_normalized']
    tolerance = config['shoulder_arrival_tolerance_normalized']
    if (type(offset) not in (int, float) or not math.isfinite(offset) or not -3 <= offset <= 0
            or type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 5 <= tolerance <= 8):
        raise ValueError('휴대폰 운반 보정값이 제한 범위를 벗어났습니다')
    result = {name: dict(values) for name, values in poses.items()}
    profiles = {}
    if not config['enabled']:
        return result, profiles
    for alias, reference in ALIASES.items():
        if reference not in poses:
            continue  # A minimal approach-only pose file remains usable.
        values = dict(poses[reference])
        values['shoulder_lift.pos'] += offset
        vector(values)  # Reject limits; do not silently clip.
        if alias in poses and poses[alias] != values:
            raise ValueError('휴대폰 보정 자세가 원본·설정과 다릅니다: ' + alias)
        result[alias] = values
        profiles[alias] = {'reference_pose': reference, 'shoulder_offset': offset,
                           'shoulder_tolerance': tolerance}
    return result, profiles


def execution_plan(sequence, poses):
    """Only stages 6..9 of routes 1,2,3,7 use loaded commands (release included).

    Stage 9 opens at the same compensated arm position as close. Stage 10 is
    unloaded, so it returns to the ordinary, uncompensated outlet waypoint.
    """
    commands = list(sequence)
    values, profiles = augmented_poses(poses)
    if len(sequence) == 11 and sequence[1] in ('pose_1', 'pose_2', 'pose_3', 'pose_7') and profiles:
        for index in (5, 6, 7, 8):
            alias = sequence[index] + '_phone'
            if alias not in profiles:
                raise ValueError('휴대폰 운반 보정 자세가 없습니다: ' + alias)
            commands[index] = alias
    return commands, values, profiles
