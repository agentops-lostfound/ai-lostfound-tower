import unittest
import numpy as np
from .reproduction import reproduce


class ReproductionTests(unittest.TestCase):
    def setUp(self):
        self.config={'reference_raw_ticks':[2000]*5,'reference_model_radians':[0,.1,.2,.3,.4],
                     'directions':[1,1,1,1,0]}

    def test_reference_maps_to_reference_angles(self):
        np.testing.assert_allclose(reproduce(self.config,[2000]*5),[0,.1,.2,.3,.4])

    def test_quarter_encoder_turn_is_not_normalized_degrees(self):
        q=reproduce(self.config,[3024,2000,2000,2000,2000])
        self.assertAlmostEqual(q[0],np.pi/2)

    def test_changed_roll_is_not_silently_inferred(self):
        with self.assertRaises(ValueError):reproduce(self.config,[2000]*4+[2010])

    def test_invalid_observation_rejected(self):
        with self.assertRaises(ValueError):reproduce(self.config,[2000,2000,float('nan'),2000,2000])
