import unittest,threading
from unittest.mock import Mock,patch
import numpy as np
from .robot_actions import Actions,MotionAborted,motion_duration,ALL
from .following_compensation import move_with_compensation
from .stage_motion import verify_stage_position
from .approach_path import path_cost

def state(values):return {'joints':[{'name':n,'raw_ticks':v} for n,v in values.items()]}
class FinalApproachTests(unittest.TestCase):
    def test_34_tick_bias_reaches_nominal_after_one_compensation(self):
        nominal=dict.fromkeys(ALL,2000);now=[None];sent=[]
        def move(goal,corrected):
            sent.append(dict(goal));feedback=dict(goal,elbow_flex=goal['elbow_flex']+34);now[0]=state(feedback)
        result=move_with_compensation(nominal,move,lambda:now[0],lambda *_:None)
        self.assertEqual(len(sent),2);self.assertEqual(sent[1]['elbow_flex'],1966)
        self.assertEqual(nominal['elbow_flex'],2000)
        self.assertEqual(next(j['raw_ticks'] for j in result['joints'] if j['name']=='elbow_flex'),2000)
    def test_ordinary_abort_does_not_latch_stationary_robot(self):
        a=Actions();a.log=Mock()
        def fail():raise MotionAborted('FK validation')
        with patch('beta.robot_actions.manual') as manual:
            manual.snapshot.return_value={'connected':True,'active':None,'latched':False}
            a.launch('test',fail);a.thread.join(2)
            manual.send.assert_not_called()
            self.assertFalse(a.info['running'])
            self.assertEqual(a.log.call_args.args[0],'aborted')
    def test_regular_fault_still_requests_stop(self):
        a=Actions();a.log=Mock()
        def fail():raise RuntimeError('communication')
        with patch('beta.robot_actions.manual') as manual:
            manual.snapshot.return_value={'connected':True,'active':None,'latched':False}
            a.launch('test',fail);a.thread.join(2)
            manual.send.assert_called_once_with('stop')
    def test_low_target_over_15_deg_takes_five_seconds(self):
        start=dict.fromkeys(ALL,2000);goal=dict(start,elbow_flex=2261)
        self.assertEqual(motion_duration(start,goal,target_height_mm=60),5)
        self.assertEqual(motion_duration(start,goal,target_height_mm=101),3)
        self.assertEqual(motion_duration(start,dict(start,elbow_flex=2065),target_height_mm=60),1.71)
    def test_small_moves_scale_with_angle(self):
        # v0.2.68: <=10 deg moves take angle*0.3s (min 1s); explicit minimum keeps the floor.
        start=dict.fromkeys(ALL,2000)
        self.assertEqual(motion_duration(start,dict(start,elbow_flex=2008)),1.0)      # 0.7 deg gap nudge
        self.assertEqual(motion_duration(start,dict(start,elbow_flex=2114)),3.0)      # 10.0 deg: same as before
        self.assertEqual(motion_duration(start,dict(start,elbow_flex=2120)),3)        # >10 deg unchanged
        self.assertEqual(motion_duration(start,dict(start,elbow_flex=2008),minimum=3),3)
        a=dict(start,elbow_flex=2057);self.assertLessEqual(5.01/motion_duration(start,a),3.34)   # peak deg/s bound
    def test_only_board_floor_stops_other_errors_warn(self):
        # v0.2.36: XY / height tolerance -> warning; below the board floor -> stop.
        self.assertFalse(verify_stage_position([100,100,23],[100,100,20],descent=True,plane_z=15)['warning'])
        self.assertTrue(verify_stage_position([103.1,100,20],[100,100,20],descent=True,plane_z=15)['warning'])
        self.assertTrue(verify_stage_position([106.1,100,60],[100,100,60],plane_z=15)['warning'])
        verify_stage_position([100,100,11.9],[100,100,13],descent=True,plane_z=15)   # FK board height is approximate
        with self.assertRaises(MotionAborted):verify_stage_position([100,100,11.9],[100,100,20],descent=True,plane_z=15)
        with self.assertRaises(MotionAborted):verify_stage_position([100,100,24],[100,100,60],plane_z=15)
    def test_weighted_cost_prefers_smaller_final_segment(self):
        start=np.zeros(5);goal=np.ones(5)
        self.assertLess(path_cost(start,[np.ones(5)*.9,goal]),path_cost(start,[np.ones(5)*.5,goal]))
    def test_shoulder_sag_up_to_60_ticks_is_compensated(self):
        # flow-c583e50c: shoulder_lift +45 (sagged) after a lateral move at full reach.
        nominal=dict.fromkeys(ALL,2000);now=[None];sent=[]
        def move(goal,corrected):
            sent.append(dict(goal));now[0]=state(dict(goal,shoulder_lift=goal['shoulder_lift']+45))
        move_with_compensation(nominal,move,lambda:now[0],lambda *_:None)
        self.assertEqual(sent[1]['shoulder_lift'],1955)
        for bad in [dict(nominal,shoulder_lift=1955),dict(nominal,elbow_flex=2045)]:   # skipped, logged
            move=Mock();logged=[]
            move_with_compensation(nominal,move,lambda:state(bad),lambda *_:None,logged.append)
            self.assertEqual(move.call_count,1);self.assertIn('40',logged[-1]['compensation_skipped'])
    def test_unchanged_34_tick_bias_compensates_only_once(self):
        # Not improved -> no extra commands; FK position check (stage_motion) decides.
        nominal=dict.fromkeys(ALL,2000);move=Mock()
        move_with_compensation(nominal,move,lambda:state(dict(nominal,elbow_flex=2034)),lambda *_:None)
        self.assertEqual(move.call_count,2)
if __name__=='__main__':unittest.main()
