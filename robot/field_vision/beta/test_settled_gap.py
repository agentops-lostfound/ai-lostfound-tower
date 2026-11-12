import unittest
from .manual_worker import settled_at_target
from .gap_motion import lateral_feedback_move
from .robot_actions import ALL
import numpy as np

class SettledGapTests(unittest.TestCase):
    def active(self):return {'started':0,'duration':3,'target':dict.fromkeys(ALL,2000)}
    def test_not_complete_before_full_duration_or_before_stable_window(self):
        a=self.active();p=dict.fromkeys(ALL,2000)
        self.assertFalse(settled_at_target(p,a,ALL,2.9))
        self.assertFalse(settled_at_target(p,a,ALL,3.0))
        self.assertFalse(settled_at_target(p,a,ALL,3.2))
        self.assertTrue(settled_at_target(p,a,ALL,3.26))
    def test_sag_and_roll_five_ticks_do_not_create_false_relative_demand(self):
        a=self.active();a['target']['wrist_roll']=1287
        p=dict.fromkeys(ALL,2000);p.update(shoulder_lift=1970,wrist_roll=1292)
        for t in [3,3.1,3.2]:self.assertFalse(settled_at_target(p,a,ALL,t))
        self.assertTrue(settled_at_target(p,a,ALL,3.26))
    def test_moving_joint_and_absolute_error_do_not_pass(self):
        a=self.active()
        for i in range(10):
            p=dict.fromkeys(ALL,2000);p['elbow_flex']+=i*4
            self.assertFalse(settled_at_target(p,a,ALL,3+i*.05))
        p['elbow_flex']=2047
        self.assertFalse(settled_at_target(p,a,ALL,4))
    def test_undertravel_retries_same_target_once_and_uses_total_mm(self):
        attempts=[];poses=iter([[0,0,60],[1.6,0,60],[3,0,60]])
        result=lateral_feedback_move(lambda i:attempts.append(i),lambda:next(poses),[1,0,0],4)
        self.assertEqual(attempts,[0,1]);self.assertEqual(result,3)
    def test_stationary_robot_retries_then_leaves_decision_to_camera(self):
        attempts=[];logged=[]
        self.assertEqual(lateral_feedback_move(lambda i:attempts.append(i),lambda:[0,0,60],[1,0,0],4,logged.append),0)
        self.assertEqual(attempts,[0,1]);self.assertTrue(logged[-1].get('short_move'))
    def test_only_height_drop_stops(self):
        for end in [[3,3.1,60],[3,0,64.1],[-1,0,60]]:   # warnings only
            poses=iter([[0,0,60],end,end]);logged=[]
            lateral_feedback_move(lambda i:None,lambda:next(poses),[1,0,0],4,logged.append)
            self.assertTrue(any(d.get('warning') for d in logged))
        poses=iter([[0,0,60],[3,0,47.9]])   # v0.2.43: stop below -12 (origin ref)
        with self.assertRaises(ValueError):lateral_feedback_move(lambda i:None,lambda:next(poses),[1,0,0],4)
    def test_default_offset_is_20_point_7(self):
        from .gap_learning import offset_amount
        from pathlib import Path
        value=offset_amount(47.615075,5.15,{},'test',Path('work/not-existing-offset-test.json'))
        self.assertAlmostEqual(value['signed_mm'],20.66527625)

class SagLateralTests(unittest.TestCase):
    def test_commanded_height_reference_and_short_move_left_to_camera(self):
        # flow 19:29: origin sagged (z 52.9), after move z 60.8 vs commanded 60.8; along 0.87/2.86.
        poses=iter([[0,0,52.9],[.87,.56,60.75]]);logs=[]
        self.assertAlmostEqual(lateral_feedback_move(lambda _:None,lambda:next(poses),[1,0,0],2.86,logs.append,max_attempts=1,expected_z=60.8),.87)
        self.assertTrue(any(d.get('short_move') for d in logs))
        poses=iter([[0,0,52.9],[1.5,0,46.]])   # 14.8mm below commanded -> stop (v0.2.43 limit -14)
        with self.assertRaisesRegex(ValueError,'높이'):
            lateral_feedback_move(lambda _:None,lambda:next(poses),[1,0,0],2.86,max_attempts=1,expected_z=60.8)
