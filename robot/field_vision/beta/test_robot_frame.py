import unittest
from unittest.mock import patch
import numpy as np
from .robot_frame import fit,transform


class RobotFrameTests(unittest.TestCase):
    def test_rotated_board_and_upward_approach(self):
        c=fit([[100,200,30],[100,668.8,30],[-102,200,30]],468.8,202)
        board={'width_mm':468.8,'height_mm':202}
        c['board_config']=board
        with patch('beta.robot_frame.board_config',return_value=board):
            r=transform([234.4,101],80,c)
        np.testing.assert_allclose(r['surface_mm'],[-1,434.4,30],atol=.001)
        np.testing.assert_allclose(r['approach_mm'],[-1,434.4,110],atol=.001)
        self.assertFalse(r['motion_sent'])

    def test_wrong_units_and_collinear_points_rejected(self):
        with self.assertRaises(ValueError):fit([[0,0,0],[46.88,0,0],[0,20.2,0]],468.8,202)
        with self.assertRaises(ValueError):fit([[0,0,0],[468.8,0,0],[202,0,0]],468.8,202)

    def test_changed_board_blocks_old_calibration(self):
        with patch('beta.robot_frame.board_config',return_value={'width_mm':500}):
            with self.assertRaises(ValueError):transform([1,1],80,{'board_config':{'width_mm':468.8}})
