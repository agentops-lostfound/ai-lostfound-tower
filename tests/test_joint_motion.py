import unittest
from robot.joint_motion import JOINTS,plan,execute


def state(value=0):return {n+'.pos':value for n in JOINTS}


class FakeTransport:
    def __init__(self):self.state=state();self.sent=[];self.held=False
    def has_exclusive_control(self):return True
    def read_normalized(self):return self.state
    def send_normalized(self,v):self.state=v;self.sent.append(v)
    def hold_current(self):self.held=True


class JointMotionTests(unittest.TestCase):
    def test_interpolation_bounded_and_gripper_preserved(self):
        target=state();target['wrist_flex.pos']=84
        p=plan(state(),target)
        self.assertEqual(len(p['waypoints']),168)
        previous=p['start']
        for point in p['waypoints']:
            self.assertLessEqual(max(abs(a-b) for a,b in zip(point,previous)),0.500001)
            previous=point

    def test_no_approval_means_no_command(self):
        t=FakeTransport()
        with self.assertRaises(PermissionError):execute(plan(state(),state()),t)
        self.assertEqual(t.sent,[])

    def test_cancellation_holds_without_sending(self):
        t=FakeTransport()
        r=execute(plan(state(),state()),t,approved=True,stop_requested=lambda:True)
        self.assertEqual(r['status'],'cancelled');self.assertTrue(t.held);self.assertEqual(t.sent,[])

    def test_mismatch_holds_instead_of_jumping(self):
        t=FakeTransport();t.state['elbow_flex.pos']=10
        with self.assertRaises(RuntimeError):execute(plan(state(),state()),t,approved=True)
        self.assertTrue(t.held);self.assertFalse(t.sent)

    def test_move_and_confirm(self):
        t=FakeTransport();target=state();target['shoulder_pan.pos']=1
        r=execute(plan(state(),target),t,approved=True,sleep=lambda _:None)
        self.assertEqual(r['status'],'reached');self.assertTrue(t.held)
