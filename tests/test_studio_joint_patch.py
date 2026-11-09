import unittest
from types import SimpleNamespace
import numpy as np
from robot.stage_studio_patch import HANDLER,replace_once


class StudioJointPatchTests(unittest.TestCase):
    def setUp(self):
        scope={'np':np,'ErrorEvent':lambda **kwargs:kwargs}
        exec('class Handler:\n'+HANDLER,scope)
        self.source=scope['Handler']()
        self.events=[]
        self.source._follower_source='hold'
        self.names=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper']
        self.source._follower=SimpleNamespace(joint_names=self.names)
        self.source._hold_target=np.zeros(6)
        self.source._event_sink=SimpleNamespace(emit=self.events.append)
        self.state=SimpleNamespace(joint_positions=np.zeros(6))
        self.command=SimpleNamespace(stage_approved=True,
            target={n+'.pos':0.0 for n in self.names},expected={n+'.pos':0.0 for n in self.names})

    def test_bounded_step_updates_only_hold_target(self):
        self.command.target['shoulder_pan.pos']=0.25
        self.source._handle_manual_joint_target(self.command,self.state)
        self.assertEqual(self.source._hold_target[0],0.25);self.assertEqual(self.events,[])

    def test_rejects_teleop_unapproved_large_step_and_gripper(self):
        for case in ['teleop','approval','step','gripper']:
            self.setUp()
            if case=='teleop':self.source._follower_source='teleop'
            if case=='approval':self.command.stage_approved=False
            if case=='step':self.command.target['shoulder_pan.pos']=1
            if case=='gripper':self.command.target['gripper.pos']=1.0
            self.source._handle_manual_joint_target(self.command,self.state)
            np.testing.assert_array_equal(self.source._hold_target,np.zeros(6))
            self.assertEqual(len(self.events),1)

    def test_rate_limit_prevents_second_target(self):
        self.command.target['shoulder_pan.pos']=0.25
        self.source._handle_manual_joint_target(self.command,self.state)
        self.command.target['shoulder_pan.pos']=0.5
        self.source._handle_manual_joint_target(self.command,self.state)
        self.assertEqual(self.source._hold_target[0],0.25)
        self.assertEqual(len(self.events),1)

    def test_ambiguous_patch_anchor_rejected(self):
        with self.assertRaises(ValueError):replace_once('aaa','a','b')
