import unittest
from unittest.mock import patch
from PIL import Image
from .coarse_grasp import correct_gap,fixed_gap,object_alignment,anchor_plan


class CoarseGraspTests(unittest.TestCase):
    def test_broad_success_band_does_not_chase_exact_center(self):
        def measure():return {'gap_px':36,'low_px':6,'high_px':56,'in_band':True}
        with patch('builtins.print'):
            result=correct_gap(measure,lambda _:self.fail('unnecessary movement'),lambda *_:None)
        self.assertEqual(result['moves'],0)

    def test_visual_response_determines_sign_and_pixel_scale(self):
        for slope in (-6,6):
            position=[0.];moves=[]
            initial=100 if slope<0 else -30
            def measure():
                gap=initial+slope*position[0]
                return {'gap_px':gap,'low_px':6,'high_px':56,'in_band':6<=gap<=56}
            def move(mm):moves.append(mm);position[0]+=mm;return mm
            result=correct_gap(measure,move,lambda *_:None)
            self.assertTrue(result['final']['in_band'])
            self.assertLessEqual(len(moves),2)
            self.assertTrue(all(abs(v)<=6 for v in moves))

    def test_no_response_does_not_keep_moving(self):
        moves=[]
        def measure():return {'gap_px':90,'low_px':6,'high_px':56,'in_band':False}
        with self.assertRaisesRegex(ValueError,'불명확'):
            correct_gap(measure,lambda mm:(moves.append(mm) or mm),lambda *_:None)
        self.assertEqual(moves,[4])

    def simulate(self,initial,slope,**kwargs):
        position=[0.];moves=[]
        def measure():
            gap=initial+slope*position[0]
            return {'gap_px':gap,'low_px':6,'high_px':56,'in_band':6<=gap<=56}
        def move(mm):moves.append(mm);position[0]+=mm;return mm
        return correct_gap(measure,move,lambda *_:None,**kwargs),moves,position

    def test_deep_overlap_after_wrong_way_probe_is_recovered(self):
        # Trial 6926d474: gap -27px. Old 4mm probe + 6mm cap could only net 2mm back.
        result,moves,position=self.simulate(-27,-6)
        self.assertTrue(result['final']['in_band'])
        self.assertEqual(moves[0],4)
        self.assertLess(moves[1],-6)
        self.assertLessEqual(abs(position[0]),12)
        self.assertAlmostEqual(result['slope_px_per_mm'],-6)

    def test_learned_slope_moves_by_measured_amount_without_probe(self):
        result,moves,_=self.simulate(1,-6,learned_slope=-6)
        self.assertEqual(len(moves),1)
        self.assertTrue(result['final']['in_band'])
        self.assertGreater(result['final']['gap_px'],10)  # aims inside the band, not its edge

    def test_total_travel_limit_stops_without_reaching_band(self):
        with self.assertRaisesRegex(ValueError,'한도'):
            self.simulate(-200,6,settings={'correction_mm':12})

    def test_reversed_response_against_learned_slope_stops(self):
        with self.assertRaisesRegex(ValueError,'반대'):
            self.simulate(1,6,learned_slope=-6)

    def test_signed_gap_uses_fixed_finger_only(self):
        profile={'frame_size':[640,480],'contour':[[80,300],[120,300],[120,479],[80,479]]}
        for left,expected in [(132,12),(105,-15)]:
            shape={'box_pixels':[[left,310],[left+100,310],[left+100,479],[left,479]],'width_pixels':100}
            with patch('beta.coarse_grasp.pink_tube',return_value=shape):
                gap=fixed_gap(Image.new('RGB',(640,480)), 'blue',profile)
            self.assertEqual(gap['gap_px'],expected)
            self.assertEqual(gap['in_band'],expected>0)

    def test_object_ending_one_px_into_tip_rows_is_extended(self):
        # v0.2.70 (flow-ce91cb8f): USB bottom 1px below the finger tip top -> extend its edge.
        profile={'frame_size':[640,480],'contour':[[80,300],[120,300],[120,479],[80,479]]}
        shape={'box_pixels':[[130,100],[180,100],[180,301],[130,301]],'width_pixels':50}
        with patch('beta.coarse_grasp.pink_tube',return_value=shape):
            gap=fixed_gap(Image.new('RGB',(640,480)),'blue',profile)
        self.assertEqual(gap['gap_px'],10);self.assertTrue(gap['extrapolated_edge'])

    def test_descent_uses_visually_accepted_xy_and_keeps_grasp_height(self):
        plan={'approach_xyz_mm':[180,0,65],'grasp_xyz_mm':[180,0,20],'verification_lift_xyz_mm':[180,0,65]}
        anchor_plan(plan,[184,-5,63])
        self.assertEqual(plan['grasp_xyz_mm'],[184,-5,20])
        self.assertEqual(plan['verification_lift_xyz_mm'],[184,-5,63])
        self.assertTrue(object_alignment({'long_axis_deg':100})['aligned'])
        self.assertFalse(object_alignment({'long_axis_deg':30})['aligned'])
