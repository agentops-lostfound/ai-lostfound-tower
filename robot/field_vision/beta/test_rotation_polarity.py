import math
import unittest
from .approach_path import SIGN
from .grasp_flow import corrected_model_roll, model_roll

class RotationPolarityTests(unittest.TestCase):
    def test_observed_image_error_requires_opposite_encoder_delta(self):
        reference={'reference_model_radians':[0]*5,'reference_raw_ticks':[0,0,0,0,2035]}
        for error in [44.405,-44.405,89,-89]:
            raw=1720
            model_goal=corrected_model_roll(reference,raw,error)
            encoder_goal=2035+model_goal*SIGN[4]*4096/(2*math.pi)
            encoder_delta=(encoder_goal-raw)*360/4096
            self.assertAlmostEqual(encoder_delta,-error)
            # Observed camera axis changes in the same direction as encoder.
            residual=(error+encoder_delta+90)%180-90
            self.assertAlmostEqual(residual,0)

    def test_model_roll_round_trips_encoder_ticks(self):
        reference={'reference_model_radians':[0,0,0,0,.3],'reference_raw_ticks':[0,0,0,0,2035]}
        for raw in [137,1720,2035,3933]:
            back=2035+(model_roll(reference,raw)-.3)*SIGN[4]*4096/(2*math.pi)
            self.assertAlmostEqual(back,raw)
