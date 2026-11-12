import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
from PIL import Image,ImageDraw
from .coarse_grasp import fixed_gap,correct_gap
from .gap_observation import GapObserver,shared_clearance,ensure_fixed_clearance
from .gap_learning import offset_amount,apply_offset,learn_offset,load_slope,save_slope
from .robot_actions import small_move_arrival,ALL
from .manual_worker import arrived_at_target

class GapRevisionTests(unittest.TestCase):
    def test_fixed_failure_recorrects_and_never_waives_second_failure(self):
        bad={'fingers':[{'finger':'fixed','gap_px':-3,'side_ok':False}],'required_px':6}
        good={'fingers':[{'finger':'fixed','gap_px':12,'side_ok':True}],'required_px':6}
        correct=Mock();check=Mock(side_effect=[bad,good])
        self.assertIs(ensure_fixed_clearance(check,correct),good);correct.assert_called_once()
        with self.assertRaisesRegex(ValueError,'하강하지'):
            ensure_fixed_clearance(lambda:bad,correct,attempts=1)

    def test_hidden_contour_does_not_hide_overlap(self):
        finger={'frame_size':[640,480],'contour':[[80,300],[120,300],[120,479],[80,479]]}
        # Visible contour is right of the finger, full object envelope overlaps it.
        shape={'contour_pixels':[[130,300],[180,300],[180,479],[130,479]],'box_pixels':[[105,290],[180,290],[180,479],[105,479]],'width_pixels':75}
        result=fixed_gap(Image.new('RGB',(640,480)),'blue',finger,shape=shape)
        self.assertLess(result['gap_px'],0);self.assertFalse(result['in_band'])

    def test_tip_quantile_rejects_local_overlap(self):
        finger={'frame_size':[640,480],'contour':[[100,200],[120,200],[120,479],[100,479]]}
        shape={'box_pixels':[[105,200],[180,200],[240,479],[165,479]],'width_pixels':75}
        result=fixed_gap(Image.new('RGB',(640,480)),'blue',finger,shape=shape)
        self.assertLess(result['gap_px'],result['median_gap_px'])
        self.assertFalse(result['in_band'])

    def test_command_limit_not_feedback_limit(self):
        command=[0.];history=[];session={}
        def measure():return {'gap_px':-200+command[0]*2,'low_px':6,'high_px':56,'in_band':False}
        def move(step):command[0]+=step;history.append(command[0]);return step*.6
        with self.assertRaisesRegex(ValueError,'한도'):
            correct_gap(measure,move,lambda *_:None,session=session)
        self.assertTrue(all(abs(x)<=12 for x in history));self.assertEqual(session['command_mm'],12)

    def test_failed_correction_keeps_consistent_slope(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'slope.json';session={'slopes':[4.,5.]}
            self.assertTrue(save_slope(session,'key',45,[640,480],'failed-trial',path=path))
            self.assertEqual(load_slope('key',45,[640,480],path),4.5)
            # v0.2.40 (audit C1): a changed context key keeps the slope; a changed
            # frame size still invalidates it.
            self.assertEqual(load_slope('changed',45,[640,480],path),4.5)
            self.assertIsNone(load_slope('key',45,[1280,720],path))

    def test_small_move_requires_real_progress_despite_sag(self):
        held=dict.fromkeys(ALL,2000);target=dict(held,shoulder_lift=2012)
        tolerance,delta=small_move_arrival(held,target)
        start=dict(held,shoulder_lift=1975)
        active={'start':start,'target':target,'arrival_tolerance_ticks':tolerance,'arrival_displacement_ticks':delta}
        self.assertEqual(tolerance['shoulder_lift'],6)
        self.assertFalse(arrived_at_target(start,active,ALL))
        self.assertFalse(arrived_at_target(dict(start,shoulder_lift=1980),active,ALL))
        self.assertTrue(arrived_at_target(dict(start,shoulder_lift=1987),active,ALL))

    def test_shared_fixed_metric_and_auxiliary_warning(self):
        gap={'gap_px':-5,'low_px':6,'high_px':56,'in_band':False}
        aux={'clear':True,'fingers':[{'finger':'fixed','gap_px':17,'side_ok':True}]}
        self.assertFalse(shared_clearance(aux,gap)['clear'])
        self.assertEqual(shared_clearance(aux,gap)['fingers'][0]['gap_px'],-5)

    def test_offset_sign_size_and_cap_without_item_values(self):
        with tempfile.TemporaryDirectory() as d:
            missing=Path(d)/'missing'
            for slope,expected in [(5,24),(-5,-24),(None,0)]:
                offset=offset_amount(40,slope,{'preoffset_k':.5},'key',missing)
                self.assertEqual(offset['signed_mm'],expected)
                plan={k:[100,200,60] for k in ['approach_xyz_mm','grasp_xyz_mm','verification_lift_xyz_mm']}
                apply_offset(plan,[0,1,0],offset)
                self.assertEqual(plan['approach_xyz_mm'],[100,200+expected,60])
            # Cap scales with width: min(60, max(setting 30, width/2+15)).
            self.assertAlmostEqual(offset_amount(100,5,{},'key',missing)['signed_mm'],39)   # 0.35*100+4, cap 60
            self.assertEqual(offset_amount(200,5,{'preoffset_k':.5},'key',missing)['signed_mm'],60)
            self.assertEqual(offset_amount(30,5,{'preoffset_k':1.2},'key',missing)['signed_mm'],30)  # small: setting cap

    def test_fit_needs_varied_widths(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fit.json'
            for i in range(5):learn_offset(40,24,5,'key',str(i),path=path)
            self.assertNotIn('fit',json.loads(path.read_text()))
            for i,w in enumerate([10,20,30,50]):learn_offset(w,.5*w+4,5,'key','new'+str(i),path=path)
            fit=json.loads(path.read_text())['fit']
            self.assertAlmostEqual(fit['k'],.5);self.assertAlmostEqual(fit['c_mm'],4)

    def test_registration_translates_complete_preopen_box(self):
        rng=np.random.default_rng(2);pixels=np.zeros((480,640,3),np.uint8)
        pixels[80:400,220:340]=rng.integers(20,255,(320,120,3),dtype=np.uint8)
        image=Image.fromarray(pixels)
        finger={'frame_size':[640,480],'contour':[[80,300],[120,300],[120,479],[80,479]]}
        shape={'box_pixels':[[220,80],[340,80],[340,400],[220,400]]}
        with patch('beta.gap_observation.pink_tube',return_value=shape):
            observer=GapObserver(image,{},finger)
            moved=Image.new('RGB',(640,480));moved.paste(image,(12,0))
            result=observer.measure(moved)
        self.assertAlmostEqual(result['registration']['shift_px'],12,delta=1)
        self.assertTrue(result['registration']['remeasured'])
        self.assertAlmostEqual(observer.box[0,0],232,delta=1)

if __name__=='__main__':unittest.main()
