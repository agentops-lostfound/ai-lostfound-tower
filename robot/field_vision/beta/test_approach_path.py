import unittest
import numpy as np
from .approach_path import context, plan_path, SIGN
from .kinematics import NAMES


class ApproachPathTests(unittest.TestCase):
    def test_rev3_center_turns_before_low_approach(self):
        # Frozen calibration and HOME from the rev3 centre trial.
        reference = {
            'reference_raw_ticks': [2146, 1983, 2051, 3262, 2035],
            'reference_model_radians': [.00010476143868449243, -.04598882741585057,
                                       .018624194226095684, 1.5981701093711786, -.003640457147708223],
            'opening_axis_local': [0.993571855676587, -0.113203213767907, 0.0],
        }
        bounds = [(846, 3553), (849, 3211), (877, 3063), (975, 3286), (137, 3933)]
        state = {'joints': [dict(name=n, raw_ticks=v, min_ticks=b[0], max_ticks=b[1])
                           for n, v, b in zip(NAMES, [2170, 858, 3062, 981, 2061], bounds)]}
        state['joints'].append(dict(name='gripper', raw_ticks=1376))
        target = np.array([183.17082977294922, -83.6809326171875, 60.])
        route = plan_path(reference, state, target, 15, opening_yaw=1.6135232255754959, relaxed=True)
        self.assertEqual(len(route['waypoints']), 2)
        model, previous, raw_reference, q0 = context(reference, state)
        def check_segment(a, b):
            valid = True
            for t in np.linspace(0, 1, 1001):
                pose = model.forward(a*(1-t)+b*t)
                p = pose['position']
                valid &= p[2] >= 35
                if np.linalg.norm(p[:2]-target[:2]) < 60 and p[2] < 80:
                    valid &= p[2] >= 57 and -pose['tool_axis'][2] >= np.cos(np.radians(10))
            return valid
        start = previous.copy()
        for waypoint in route['waypoints']:
            raw = np.array([waypoint['target'][n] for n in NAMES])
            self.assertTrue(all(low <= tick <= high for tick, (low, high) in zip(raw, bounds)))
            q = q0+(raw-raw_reference)*SIGN*2*np.pi/4096
            self.assertTrue(check_segment(previous, q))
            previous = q
        self.assertFalse(check_segment(start, previous))
        self.assertLess(np.linalg.norm(model.forward(previous)['position']-target), 3)


if __name__ == '__main__':
    unittest.main()
