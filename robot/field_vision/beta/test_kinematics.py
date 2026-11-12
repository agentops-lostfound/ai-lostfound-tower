import unittest
import numpy as np
from .kinematics import Model,rotation


class KinematicsTests(unittest.TestCase):
    def test_rotation_is_rigid(self):
        r=rotation([1,2,3],.7)
        np.testing.assert_allclose(r.T@r,np.eye(3),atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(r),1)

    def test_pan_preserves_height_and_radius(self):
        m=Model();a=m.forward([0,.3,-.2,.4,0]);b=m.forward([.5,.3,-.2,.4,0])
        self.assertAlmostEqual(a['position'][2],b['position'][2],places=3)
        self.assertAlmostEqual(np.linalg.norm(a['position'][:2]),np.linalg.norm(b['position'][:2]),places=3)

    def test_inverse_reaches_independently_generated_position(self):
        m=Model();target=m.forward([.3,.2,-.4,.5,.2])['position'];result=m.inverse(target)
        self.assertTrue(result['reachable_in_model'])
        self.assertLess(result['position_error_mm'],.1)
        q=np.array(result['joint_radians'])
        self.assertTrue(np.all(q>=m.limits[:,0]) and np.all(q<=m.limits[:,1]))

    def test_impossible_target_not_marked_reachable(self):
        m=Model();self.assertFalse(m.inverse([900,900,900])['reachable_in_model'])

    def test_invalid_angles_rejected(self):
        with self.assertRaises(ValueError):Model().forward([0,0,float('nan'),0,0])
