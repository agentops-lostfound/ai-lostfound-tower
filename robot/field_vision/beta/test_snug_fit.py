"""v0.2.76: wide-item snug step (category independent)."""
import unittest
from . import snug_fit as s


class SnugFitTests(unittest.TestCase):
    def test_moves_a_fraction_toward_the_side(self):
        mm=s.step_mm(30.7,6.41,0,20)                  # flow-e1f0b648 floor gap
        self.assertAlmostEqual(mm,(6-30.7)/6.41*.7,3);self.assertLess(mm,0)
    def test_sign_follows_measured_slope(self):
        self.assertGreater(s.step_mm(30.7,-6.41,0,20),0)
    def test_no_move_when_close_unknown_or_no_room(self):
        self.assertIsNone(s.step_mm(10,6.4,0,20))
        self.assertIsNone(s.step_mm(None,6.4,0,20))
        self.assertIsNone(s.step_mm(30,None,0,20))
        self.assertIsNone(s.step_mm(30,6.4,19.9,20))
    def test_clamped_to_remaining_limit(self):
        self.assertAlmostEqual(s.step_mm(200,6.4,18,20),-2.0)

    def test_path_floor_allows_start_below_board(self):
        self.assertAlmostEqual(s.path_floor(12.7,15),12.2)    # flow-79bca983: feedback plane-2.3mm
        self.assertAlmostEqual(s.path_floor(17,15),13.5)

    def test_second_step_uses_floor_response_and_minimum_move(self):
        # flow-fba8acfb: -1.3mm moved the gap 17.9 -> 12.5px (4.15 px/mm); then 0.7mm did nothing
        slope=s.measured_slope(17.9,12.5,-1.3);self.assertAlmostEqual(slope,4.154,2)
        self.assertAlmostEqual(s.step_mm(12.5,slope,1.3,20,measured=True),(6-12.5)/slope,2)
        self.assertEqual(s.step_mm(13,40,0,20),-1.0)                      # tiny computed move -> 1mm
        self.assertIsNone(s.measured_slope(12.5,12.5,-0.7))


if __name__=='__main__':unittest.main()
