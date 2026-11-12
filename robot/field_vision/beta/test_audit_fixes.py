"""v0.2.41 audit fixes (Fable + Codex agreed plan items 1-5)."""
import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from . import floor_descent as fd
from .coarse_grasp import correct_gap,object_alignment,fixed_gap
from .gap_learning import slope_state,mark_suspect,confirm_key,load_slope


class Arm:
    """Fake arm: feedback follows the command, but never below `support` and never
    moves for commands within `dead` mm of the current feedback."""
    def __init__(self,z,support=-99.,dead=0.,ik_below=None):
        self.z=z;self.support=support;self.dead=dead;self.ik_below=ik_below;self.cmds=[]
    def goal(self,z):
        if self.ik_below is not None and z<self.ik_below:raise ValueError('IK 실패')
        return z
    def move(self,goal,z,label):
        self.cmds.append(z)
        # Downward moves shorter than `dead` stall (friction/dead zone); upward always move.
        if z>self.z or self.z-z>=self.dead:self.z=max(z,self.support)
        return self.z
    def read(self):return self.z


def run(arm,grasp_z=20.,plane=10.):
    return fd.descend(grasp_z,plane,arm.goal,arm.move,arm.read)


class FloorDescentTests(unittest.TestCase):
    def test_board_support_is_contact_and_released(self):
        arm=Arm(20.,support=13.)
        r=run(arm)
        self.assertEqual(r['status'],'contact');self.assertTrue(r['low_enough'])
        self.assertAlmostEqual(r['final_z'],13.5)   # released to feedback + 0.5mm
        # v0.2.42: reaching plane+1 ends the descent at once (no pressing until held up).
        arm=Arm(20.,support=11.);r=run(arm)
        self.assertEqual(r['status'],'target');self.assertTrue(r['low_enough']);self.assertIsNone(r['abort'])
        self.assertEqual(min(arm.cmds),10.)

    def test_dead_zone_high_is_not_contact(self):
        # Arm never moves (flow-8a3571cc): old loop read this as contact at step 4.
        arm=Arm(20.,dead=99.)
        r=run(arm)
        self.assertNotEqual(r['status'],'contact')
        self.assertTrue(r['stalled_high']);self.assertFalse(r['low_enough'])
        self.assertIn('retry',r)

    def test_stall_retry_crosses_dead_zone(self):
        arm=Arm(20.,dead=15.,support=10.5)   # ladder steps stall, the long retry gets through
        r=run(arm)
        self.assertTrue(r['stalled_high']);self.assertTrue(r['low_enough'])
        self.assertLessEqual(r['final_z'],13.)

    def test_command_never_below_absolute_floor(self):
        arm=Arm(20.)   # nothing holds it up
        r=run(arm)
        self.assertGreaterEqual(min(arm.cmds),fd.command_floor(20.,10.)-1e-9)
        self.assertEqual(fd.command_floor(20.,10.),8.)   # max(20-12, 10-8)
        self.assertEqual(fd.command_floor(14.,10.),2.)   # plane-8 is the limit

    def test_ik_failure_is_its_own_state(self):
        arm=Arm(20.,ik_below=15.)
        r=run(arm)
        self.assertEqual(r['status'],'ik_limit');self.assertIn('IK',r['ik_error'])
        self.assertFalse(r['low_enough'])

    def test_feedback_below_board_is_a_failure_not_low_enough(self):
        arm=Arm(20.)
        r=fd.descend(20.,10.,arm.goal,lambda g,z,l:z-15,arm.read)   # feedback 3 < plane-6
        self.assertEqual(r['status'],'below_floor');self.assertTrue(r['too_low'])
        self.assertFalse(r['low_enough']);self.assertIsNotNone(r['abort'])
        self.assertEqual(fd.verdict(r,gap_checked=False)[0],'stop')

    def test_retry_has_the_same_lower_bound(self):
        state={'z':20.}
        def move(goal,z,label):
            if '한 번에' in label:state['z']=2.      # retry plunges below plane-6
            elif z>state['z']:state['z']=z           # ladder steps stall, lift works
            return state['z']
        r=fd.descend(20.,10.,lambda z:z,move,lambda:state['z'])
        self.assertIn('retry',r);self.assertEqual(r['status'],'below_floor');self.assertIsNotNone(r['abort'])

    def test_release_ik_failure_stops(self):
        arm=Arm(20.,support=13.)
        def goal(z):
            if z>13.2 and arm.cmds and arm.cmds[-1]<13:raise ValueError('IK 실패')
            return z
        r=fd.descend(20.,10.,goal,arm.move,arm.read)
        self.assertEqual(r['status'],'contact');self.assertIn('release_error',r);self.assertIsNotNone(r['abort'])

    def test_verdict_connects_judgement_to_action(self):
        ok={'abort':None,'low_enough':True,'reached_z':11.,'plane_z':10.}
        high=dict(ok,low_enough=False,reached_z=16.)
        self.assertEqual(fd.verdict(ok,{'gap_px':2.})[0],'close')
        self.assertEqual(fd.verdict(high,{'gap_px':2.})[0],'warn_close')
        self.assertEqual(fd.verdict(ok,None)[0],'stop')                 # not measured != no overlap
        self.assertEqual(fd.verdict(ok,{'gap_px':-9.})[0],'stop')
        self.assertEqual(fd.verdict(dict(ok,abort='x'),{'gap_px':2.})[0],'stop')

    def test_stop_error_propagates(self):
        arm=Arm(20.)
        def move(*_):raise ValueError('STOP 래치')
        with self.assertRaisesRegex(ValueError,'STOP'):fd.descend(20.,10.,arm.goal,move,arm.read)


def sim(initial,slope,actual_scale=1.,**kw):
    pos=[0.];moves=[]
    def measure():
        g=initial+slope*pos[0];return {'gap_px':g,'low_px':6,'high_px':56,'in_band':6<=g<=56}
    def move(mm):
        a=mm*actual_scale(len(moves)) if callable(actual_scale) else mm*actual_scale
        moves.append(mm);pos[0]+=a;return a
    session={}
    return (lambda:correct_gap(measure,move,lambda *_:None,session=session,**kw)),moves,session


class GapCorrectionTests(unittest.TestCase):
    def test_short_real_move_is_skipped_once(self):
        # First move barely happens (dead zone), second is normal.
        f,moves,_=sim(-20,5,actual_scale=lambda i:.2 if i==0 else 1.)
        self.assertTrue(f()['final']['in_band'])

    def test_short_moves_never_stop_by_themselves(self):
        # flow-23834736: 30.5px, band 18.6..28.6, two ~0.4mm real moves -> 27.6px in band.
        def measure():
            g=30.5+3.6*pos[0];return {'gap_px':g,'low_px':18.6,'high_px':28.6,'in_band':18.6<=g<=28.6}
        pos=[0.]
        def move(mm):a=mm*.39;pos[0]+=a;return a
        r=correct_gap(measure,move,lambda *_:None,learned_slope=3.6)
        self.assertTrue(r['final']['in_band'])
        # A robot that barely moves is still bounded (moves / travel limit), not endless.
        f,moves,_=sim(-20,5,actual_scale=.05)
        with self.assertRaises(ValueError):f()
        self.assertLessEqual(len(moves),6)

    def test_single_reversal_is_rechecked_and_second_stops(self):
        f,_,session=sim(1,6,learned_slope=-6)
        with self.assertRaisesRegex(ValueError,'반대'):f()
        self.assertIn('reversed',session)


class EdgeEvidenceTests(unittest.TestCase):
    def test_clipped_without_usable_edge_skips_rotation(self):
        # flow-8aef9ccd: clipped box axis must not rotate; weak edge -> no rotation.
        shape={'long_axis_deg':0,'clipped':True,'visible_boundary':{'angle_deg':40,'usable_for_rotation':False}}
        r=object_alignment(shape);self.assertTrue(r['aligned']);self.assertFalse(r['axis_reliable'])

    def test_straight_edge_beyond_30deg_still_rotates(self):
        shape={'long_axis_deg':0,'clipped':True,'visible_boundary':{'angle_deg':125,'usable_for_rotation':True}}
        r=object_alignment(shape);self.assertFalse(r['aligned']);self.assertEqual(r['axis_source'],'fixed_side_edge')
        self.assertAlmostEqual(r['error_deg'],35)

    def test_weak_edge_never_decides_gap(self):
        finger={'frame_size':[640,480],'contour':[[80,300],[120,300],[120,479],[80,479]]}
        shape={'box_pixels':[[130,300],[230,300],[230,479],[130,479]],'width_pixels':100,
               'visible_boundary':{'points':[[130,0],[130,479]],'usable_for_gap':False,'error_deg':25}}
        with self.assertRaisesRegex(ValueError,'간격 근거 부족'):
            fixed_gap(Image.new('RGB',(640,480)),'blue',finger,shape=shape)


class SlopeKeyTests(unittest.TestCase):
    def write(self,d,**extra):
        path=Path(d)/'slope.json'
        path.write_text(json.dumps(dict(slope_px_per_mm=4.,context_key='old',approach_height_mm=45,frame_size=[640,480],**extra)))
        return path

    def test_changed_hard_key_reconfirms_and_confirm_adopts(self):
        with tempfile.TemporaryDirectory() as d:
            path=self.write(d)
            s=slope_state('new',45,[640,480],path);self.assertEqual(s['slope'],4.);self.assertTrue(s['reconfirm'])
            confirm_key('new',path)
            self.assertFalse(slope_state('new',45,[640,480],path)['reconfirm'])

    def test_two_suspects_discard(self):
        with tempfile.TemporaryDirectory() as d:
            path=self.write(d)
            mark_suspect('a',path);self.assertEqual(load_slope('old',45,[640,480],path),4.)
            mark_suspect('b',path);self.assertIsNone(load_slope('old',45,[640,480],path))


if __name__=='__main__':unittest.main()
