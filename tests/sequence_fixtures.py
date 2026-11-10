"""Synthetic taught poses; never load physical motor samples into a test driver."""
from robot.joint_motion import JOINTS


def taught_poses():
    zero = {name + '.pos': 0.0 for name in JOINTS}
    poses = {'home': {**zero, 'gripper.pos': 4.5},
             'outlet_return_1': {**zero, 'shoulder_pan.pos': 25.0, 'gripper.pos': 1.2},
             'close': {**zero, 'shoulder_pan.pos': 30.0, 'gripper.pos': 1.8},
             'open': {**zero, 'shoulder_pan.pos': 30.0, 'gripper.pos': 77.0}}
    for n in range(1, 9):
        approach = {**zero, 'shoulder_pan.pos': n * 8.0, 'gripper.pos': 4.0}
        poses[f'pose_{n}'] = approach
        poses[f'pose_{n}_open'] = {**approach, 'gripper.pos': 70.0}
        poses[f'pose_{n}_target'] = {**approach, 'shoulder_lift.pos': 20.0, 'gripper.pos': 70.0}
        poses[f'pose_{n}_close'] = {**poses[f'pose_{n}_target'], 'gripper.pos': 35.575 if n in (7, 8) else 4.0}
        if n in (7, 8):
            poses[f'pose_{n}_return'] = {**approach, 'gripper.pos': 35.575}
    poses['outlet_return_1_78'] = {**poses['outlet_return_1'], 'gripper.pos': 35.575}
    poses['close_78'] = {**poses['close'], 'gripper.pos': 35.575}
    return poses


def expected_sequence(n):
    returning = f'pose_{n}_return' if n in (7, 8) else f'pose_{n}'
    outlet = 'outlet_return_1_78' if n in (7, 8) else 'outlet_return_1'
    closing = 'close_78' if n in (7, 8) else 'close'
    return ['home', f'pose_{n}', f'pose_{n}_open', f'pose_{n}_target', f'pose_{n}_close',
            returning, outlet, closing, 'open', outlet, 'home']
