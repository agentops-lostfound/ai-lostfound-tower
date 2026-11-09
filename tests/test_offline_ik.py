import tempfile
from pathlib import Path
import unittest
import numpy as np
from robot.offline_ik import Model


class OfflineIKTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=Path(self.temp.name)/'model.urdf'
        p.write_text('''<robot name="test"><link name="base_link"/>
        <joint name="pan" type="revolute"><parent link="base_link"/><child link="arm"/>
        <axis xyz="0 0 1"/><limit lower="-2" upper="2"/></joint>
        <joint name="tip" type="fixed"><parent link="arm"/><child link="gripper_frame_link"/>
        <origin xyz="0.2 0 0"/></joint></robot>''')
        self.model=Model(p)

    def test_fk_against_analytic_rotation(self):
        np.testing.assert_allclose(self.model.fk([np.pi/2])[:3,3],[0,0.2,0],atol=1e-10)

    def test_ik_reaches_known_point_and_respects_limits(self):
        r=self.model.solve([0,200,0]);self.assertEqual(r['status'],'position_solution')
        self.assertLessEqual(r['position_error_mm'],1)
        self.assertLessEqual(abs(r['joints']['pan']),2)
        self.assertFalse(r['robot_authorized'])

    def test_unreachable_point_does_not_claim_solution(self):
        r=self.model.solve([0,0,1000])
        self.assertEqual(r['status'],'no_solution_found')

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):self.model.solve([float('nan'),0,0])
