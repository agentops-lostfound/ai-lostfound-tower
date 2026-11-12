import unittest,json,tempfile
from pathlib import Path
from unittest.mock import Mock
import numpy as np
from PIL import Image,ImageDraw
from .following_compensation import compensated_goal,move_with_compensation
from .kinematics import NAMES
from .outline_refinement import refine_outline
from .grasp_reference import contact_reference
from .gap_motion import lateral_feedback_move

ALL=NAMES+['gripper']
def state(values):return {'joints':[{'name':n,'raw_ticks':v} for n,v in values.items()]}
class OutlineFollowingTests(unittest.TestCase):
    def test_constant_30_tick_bias_corrected_once_nominal_unchanged(self):
        nominal=dict.fromkeys(ALL,2000);current=[None];commands=[]
        def move(goal,corrected):
            commands.append(dict(goal));feedback=dict(goal);feedback['elbow_flex']+=30;current[0]=state(feedback)
        result=move_with_compensation(nominal,move,lambda:current[0],lambda *_:None)
        self.assertEqual(len(commands),2);self.assertEqual(commands[-1]['elbow_flex'],1970)
        self.assertEqual(nominal['elbow_flex'],2000)
        self.assertEqual(next(j['raw_ticks'] for j in result['joints'] if j['name']=='elbow_flex'),2000)
        self.assertEqual(commands[-1]['gripper'],2000)
    def test_over_40_ticks_never_sends_compensated_command(self):
        # v0.2.36: skipped and logged, not a stop.
        nominal=dict.fromkeys(ALL,2000);feedback=dict(nominal,elbow_flex=2041);move=Mock();logged=[]
        move_with_compensation(nominal,move,lambda:state(feedback),lambda *_:None,logged.append)
        self.assertEqual(move.call_count,1);self.assertIn('40',logged[-1]['compensation_skipped'])
    def test_invalid_corrected_path_is_not_sent(self):
        nominal=dict.fromkeys(ALL,2000);feedback=dict(nominal,elbow_flex=2030);move=Mock();logged=[]
        def invalid(*_):raise ValueError('path')
        move_with_compensation(nominal,move,lambda:state(feedback),invalid,logged.append)
        self.assertEqual(move.call_count,1);self.assertEqual(logged[-1]['compensation_skipped'],'path')
    def test_side_drift_limit_scales_with_long_moves(self):
        # flow-d9aa72cd: -11.25mm move, along -11.52mm, side 4.15mm -> now accepted.
        poses=iter([[0,0,60],[-11.52,4.15,58.1]])
        self.assertAlmostEqual(lateral_feedback_move(lambda _:None,lambda:next(poses),[1,0,0],-11.25),-11.52)
        # v0.2.36: side drift beyond the limit is a logged warning, not a stop.
        poses=iter([[0,0,60],[-11.5,5.2,58.1]]);logged=[]
        lateral_feedback_move(lambda _:None,lambda:next(poses),[1,0,0],-11.25,logged.append,max_attempts=1)
        self.assertTrue(any(d.get('warning') for d in logged))
    def test_no_improvement_is_logged_and_left_to_fk_check(self):
        # v0.2.10: an ineffective small correction no longer aborts by itself;
        # only one compensation is sent and the caller's FK check decides.
        nominal=dict.fromkeys(ALL,2000);move=Mock();logged=[]
        result=move_with_compensation(nominal,move,lambda:state(dict(nominal,elbow_flex=2030)),lambda *_:None,logged.append)
        self.assertEqual(move.call_count,2)
        self.assertEqual(next(j['raw_ticks'] for j in result['joints'] if j['name']=='elbow_flex'),2030)
        self.assertTrue(any(d.get('compensation_effective') is False for d in logged))
    def test_height_drop_toward_object_still_stops(self):
        poses=iter([[0,0,60],[3,0,47.5]])          # 12.5mm drop (> 4+8, v0.2.43)
        with self.assertRaisesRegex(ValueError,'하강'):
            lateral_feedback_move(lambda _:None,lambda:next(poses),[1,0,0],4,max_attempts=1)
    def test_multicolor_outline_includes_white_cap_excludes_green(self):
        image=Image.new('RGB',(400,400),'#609e80');d=ImageDraw.Draw(image)
        d.rectangle((170,60,230,280),fill='#3030a0');d.rectangle((170,281,230,330),fill='white')
        located={'box_pixels':[[170,90],[230,90],[230,330],[170,330]],'length_pixels':240,'width_pixels':60}
        shape=refine_outline(image,{'physical_size_mm':{'length':90,'width':20}},located)
        box=np.asarray(shape['box_pixels']);self.assertLessEqual(box[:,1].min(),61);self.assertGreaterEqual(box[:,1].max(),329)
        self.assertLess(shape['width_pixels'],65)
    def test_disconnected_other_object_not_selected(self):
        image=Image.new('RGB',(400,400),'#609e80');d=ImageDraw.Draw(image)
        d.rectangle((170,60,230,330),fill='blue');d.rectangle((20,20,80,350),fill='pink')
        located={'box_pixels':[[170,60],[230,60],[230,330],[170,330]],'length_pixels':270,'width_pixels':60}
        shape=refine_outline(image,{},located);self.assertGreater(np.asarray(shape['box_pixels'])[:,0].min(),160)
    def test_contact_is_explicit_provisional_common_strip(self):
        r=contact_reference({'frame_size':[640,480],'contour':[[80,300],[120,300],[120,479],[80,479]]})
        self.assertEqual(r['status'],'provisional');self.assertEqual(r['image_point'][0],120)
        self.assertEqual(r['image_rows'][0],300);self.assertFalse(r['model_verified'])
if __name__=='__main__':unittest.main()
