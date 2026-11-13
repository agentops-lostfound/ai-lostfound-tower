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
        poses[f'pose_{n}_close'] = {**poses[f'pose_{n}_target'], 'gripper.pos': {7: 9.35, 8: 9.62}.get(n, 4.0)}
    return poses


def expected_sequence(n):
    return ['home', f'pose_{n}', f'pose_{n}_open', f'pose_{n}_target', f'pose_{n}_close',
            f'pose_{n}', 'outlet_return_1', 'close', 'open', 'outlet_return_1', 'home']
