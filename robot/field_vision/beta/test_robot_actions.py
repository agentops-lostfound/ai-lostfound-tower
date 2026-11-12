import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from .robot_actions import Actions,ALL,validate_goal


def state():
    return {'connected':True,'age':.01,'active':None,'latched':False,'joints':[
        {'id':i+1,'name':n,'raw_ticks':2000,'min_ticks':1000,'max_ticks':3000,'torque_enabled':True} for i,n in enumerate(ALL)]}


class ActionsTests(unittest.TestCase):
    def test_original_out_of_range_home_not_clamped(self):
        s=state();target={n:2000 for n in ALL};target['wrist_flex']=953
        with self.assertRaises(ValueError):validate_goal(target,s)
        self.assertEqual(target['wrist_flex'],953)

    def test_stop_cancels_future_steps(self):
        a=Actions();a.log=lambda *args,**kw:None
        with patch('beta.robot_actions.manual') as manual:
            manual.snapshot.return_value=state();a.stop()
            manual.send.assert_called_once_with('stop')
            with self.assertRaises(ValueError):a.check()

    def test_home_preserves_gripper_and_segments_without_auto_open(self):
        a=Actions();a.log=lambda *args,**kw:None;home={'raw_ticks':{n:2100 for n in ALL}}
        with patch('beta.robot_actions.read_home',return_value=home),patch('beta.robot_actions.fresh',return_value=state()),patch.object(a,'launch') as launch:
            a.go_home();fn=launch.call_args.args[1]
            with patch.object(a,'home_move') as move:fn();target=move.call_args.args[0]
            self.assertEqual(target['gripper'],2000)
            self.assertEqual(target['shoulder_pan'],2100)

    def test_stop_while_waiting_for_motion_sends_stop_and_exits(self):
        a=Actions();a.log=lambda *args,**kw:None
        with patch('beta.robot_actions.manual') as manual:
            manual.snapshot.return_value=state()
            def cancel_after_move(action,**kwargs):
                if action=='move':a.cancel.set()
                return state()
            manual.send.side_effect=cancel_after_move
            with self.assertRaises(ValueError):a.move({n:2050 for n in ALL},'test')
            self.assertIn('stop',[call.args[0] for call in manual.send.call_args_list])
