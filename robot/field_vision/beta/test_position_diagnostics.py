import unittest
import numpy as np
from .position_diagnostics import compare_positions, observed_translation
from .manual_worker import arrived_at_target


class PositionDiagnosticsTests(unittest.TestCase):
    def test_observation_does_not_double_count_following_error(self):
        d=compare_positions([228.739429,-181.00918,60],
                            [227.446952,-179.879137,61.847288],
                            [226.303091,-176.039300,54.310912])
        np.testing.assert_allclose(np.array(d['ik_error']['delta_mm'])+d['following_error']['delta_mm'],
                                   d['total_model_error']['delta_mm'])
        frame={'x_axis':[0,-1,0],'y_axis':[-1,0,0]}
        observation=observed_translation(d,[10,-20],frame)
        np.testing.assert_allclose(observation['observed_robot_motion_mm'],[20,-10,0])
        np.testing.assert_allclose(observation['candidate_target_delta_mm'],[17.563662,-5.03012,0])
        self.assertFalse(observation['applied'])
        self.assertEqual(d['physical_alignment'],'unmeasured')

    def test_final_approach_rejects_old_coarse_arrival(self):
        names=['elbow_flex','wrist_roll','gripper']
        active={'start':dict.fromkeys(names,2000),'target':dict.fromkeys(names,2000)}
        positions=dict(elbow_flex=2022,wrist_roll=2000,gripper=2000)
        self.assertTrue(arrived_at_target(positions,active,names))
        active['arrival_tolerance_ticks']=12
        self.assertFalse(arrived_at_target(positions,active,names))
        positions['elbow_flex']=2012
        positions['gripper']=2030
        self.assertTrue(arrived_at_target(positions,active,names))
