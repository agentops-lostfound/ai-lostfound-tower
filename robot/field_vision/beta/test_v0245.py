"""v0.2.45: measured aperture table, unified tilt, drop-off transfer helpers."""
import json
import unittest
import numpy as np
from .config import DATA
from .gripper_aperture import choose
from .kinematics import Model,NAMES
from .approach_path import context
from .view_clearance import validate_view_path
from . import return_path as rp

TABLE={'revision':'r','height_mm':5.,'margin_mm':6.,'gripper_limits':[1345,2800],
       'rows':[{'percent':50,'width_mm':82.},{'percent':80,'width_mm':120.},{'percent':100,'width_mm':135.}]}


class MeasuredApertureTests(unittest.TestCase):
    def test_real_table_selection(self):
        self.assertEqual(choose(72.7,5,TABLE)['percent'],80)   # phone must not fall back to 50%
        self.assertEqual(choose(47.5,5,TABLE)['percent'],50)
        self.assertEqual(choose(60,5,TABLE)['percent'],80)
        self.assertEqual(choose(129,5,TABLE)['percent'],100)
        with self.assertRaisesRegex(ValueError,'부족'):choose(130,5,TABLE)

    def test_height_reuse_within_3mm(self):
        a=choose(72.7,7,TABLE);self.assertEqual(a['percent'],80);self.assertIn('2.0mm',a['warning'])
        self.assertNotIn('warning',choose(72.7,5.3,TABLE))
        with self.assertRaisesRegex(ValueError,'미측정'):choose(72.7,9,TABLE)
        self.assertFalse(choose(40,9,TABLE)['verified'])


def _setup():
    reference=json.loads((DATA/'working_calibration.json').read_text(encoding='utf-8'))
    home=json.loads((DATA/'robot_home.json').read_text(encoding='utf-8'))['raw_ticks']
    limits={'shoulder_pan':(846,3553),'shoulder_lift':(849,3211),'elbow_flex':(877,3063),
            'wrist_flex':(975,3286),'wrist_roll':(137,3933),'gripper':(1345,2800)}
    state={'joints':[{'name':n,'raw_ticks':int(home[n]),'min_ticks':limits[n][0],'max_ticks':limits[n][1]} for n in NAMES+['gripper']]}
    model,q,r,q0=context(reference,state)
    return reference,home,limits,state,model,r,q0


def _reachable_pose(model,r,q0,limits,xyz):
    sol=model.inverse(np.asarray(xyz,float),tool_down=True,max_down_deg=10)
    t=rp.to_ticks(sol['joint_radians'],r,q0)
    pose={n:int(t[i]) for i,n in enumerate(NAMES)}
    assert all(limits[n][0]<=pose[n]<=limits[n][1] for n in NAMES),pose
    return pose


class DropoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference,cls.home,cls.limits,cls.state,cls.model,cls.r,cls.q0=_setup()
        cls.bounds={n:cls.limits[n] for n in NAMES+['gripper']}

    def z(self,ticks):return self.model.forward(rp.to_q(ticks,self.r,self.q0),with_points=False)['position'][2]

    def test_staged_lift_30_then_fallback(self):
        base=_reachable_pose(self.model,self.r,self.q0,self.limits,[200,0,60])
        goal,info=rp.vertical_lift(self.model,self.r,self.q0,base,self.bounds)
        self.assertEqual(info['requested_mm'],30.);self.assertGreater(self.z(goal)-self.z(base),26)
        # Cap shoulder_lift so 30mm is impossible but a smaller lift works.
        need=goal['shoulder_lift']-base['shoulder_lift']
        tight=dict(self.bounds)
        lo,hi=self.bounds['shoulder_lift']
        tight['shoulder_lift']=(lo,base['shoulder_lift']+int(need*.75)) if need>0 else (base['shoulder_lift']+int(need*.75),hi)
        goal2,info2=rp.vertical_lift(self.model,self.r,self.q0,base,tight)
        self.assertLess(info2['requested_mm'],30.);self.assertGreaterEqual(info2['lift_mm'],7)
        self.assertEqual([t['mm'] for t in info2['tried']][0],30.)

    def test_lift_refused_below_10mm(self):
        base=_reachable_pose(self.model,self.r,self.q0,self.limits,[200,0,60])
        frozen={n:(base[n],base[n]) if n!='gripper' else self.bounds[n] for n in self.bounds}
        with self.assertRaisesRegex(ValueError,'모두 불가'):rp.vertical_lift(self.model,self.r,self.q0,base,frozen)

    def test_dropoff_plan_rise_travel_descend(self):
        plane=0.
        start=_reachable_pose(self.model,self.r,self.q0,self.limits,[200,80,45])
        drop=_reachable_pose(self.model,self.r,self.q0,self.limits,[120,-200,15])
        plan=rp.plan_dropoff(self.model,self.r,self.q0,start,drop,self.home,plane,8,120,self.bounds)
        m=plan['moves']
        self.assertGreater(self.z(m['lifted']),100)              # rose toward the transfer height
        self.assertGreater(self.z(m['above']),100)               # above the drop point at height
        self.assertAlmostEqual(self.z(m['drop']),self.z(drop),3)
        a=self.model.forward(rp.to_q(m['above'],self.r,self.q0),with_points=False)['position']
        d=self.model.forward(rp.to_q(drop,self.r,self.q0),with_points=False)['position']
        self.assertLess(np.linalg.norm(a[:2]-d[:2]),10)          # straight-down descent
        self.assertGreaterEqual(plan['travel_min_z_mm'],plan['travel_required_z_mm']-.5)

    def test_dropoff_plan_refuses_when_object_cannot_clear(self):
        start=_reachable_pose(self.model,self.r,self.q0,self.limits,[200,80,45])
        drop=_reachable_pose(self.model,self.r,self.q0,self.limits,[120,-200,15])
        frozen={n:(start[n],start[n]) if n!='gripper' else self.bounds[n] for n in self.bounds}
        with self.assertRaises(ValueError):
            rp.plan_dropoff(self.model,self.r,self.q0,start,drop,self.home,0.,8,120,frozen)

    def test_transfer_height_capped_by_reach_steps_down(self):
        base=_reachable_pose(self.model,self.r,self.q0,self.limits,[200,0,60])
        goal,info=rp.lift_to_height(self.model,self.r,self.q0,base,self.bounds,60+500,20)
        self.assertLess(info['requested_mm'],500);self.assertGreater(info['lift_mm'],10)


class TiltUnifyTests(unittest.TestCase):
    def test_view_path_uses_given_tilt(self):
        reference,home,limits,state,model,r,q0=_setup()
        a=_reachable_pose(model,r,q0,limits,[200,0,60])
        qa=rp.to_q(a,r,q0)
        # tilt the wrist ~12 deg: fails at 10, passes at 18
        qb=qa.copy();qb[3]+=np.radians(12)
        tool=model.forward(qb,with_points=False)['tool_axis']
        tilt=np.degrees(np.arccos(-tool[2]))
        self.assertTrue(10<tilt<18,tilt)
        with self.assertRaises(ValueError):validate_view_path(model,qb,qb,-100,0,max_tilt_deg=10)
        validate_view_path(model,qb,qb,-100,0,max_tilt_deg=18)


if __name__=='__main__':unittest.main()


class ContactTicksTests(unittest.TestCase):
    def test_expected_contact_from_measured_table(self):
        from .gripper_aperture import contact_ticks,ticks
        self.assertEqual(contact_ticks(82,TABLE),ticks(50,1345,2800))
        self.assertEqual(contact_ticks(120,TABLE),ticks(80,1345,2800))
        t=contact_ticks(48.8,TABLE);self.assertTrue(1650<t<1730,t)    # hand cream: ~380 ticks below 50%
        self.assertIsNone(contact_ticks(50,{'rows':[{'percent':50,'width_mm':82}]}))


class ArmMaskTests(unittest.TestCase):
    def ref(self,fg,w):
        return {'foreground':fg,'foreground_weights':w,'background':[[179.,98.,129.],[110.,108.5,125.]]}

    def test_greenish_palette_entries_do_not_capture_shadowed_foam(self):
        import cv2
        from .object_reference import appearance_mask
        img=np.zeros((120,160,3),np.uint8);img[:]=(120,185,150)          # lit foam
        img[80:,:60]=(95,150,120)                                          # shadowed foam (green)
        img[20:70,70:90]=(20,20,24)                                        # black USB
        lab=cv2.cvtColor(img,cv2.COLOR_RGB2LAB)
        shadow=lab[100,30].astype(float).tolist();usb=lab[40,80].astype(float).tolist()
        m=appearance_mask(img,self.ref([usb,shadow],[.8,.2]))              # palette polluted by foam
        self.assertTrue(m[40,80]>0);self.assertEqual(int(m[100,30]),0)

    def test_green_object_keeps_its_green(self):
        import cv2
        from .object_reference import appearance_mask
        img=np.zeros((60,60,3),np.uint8);img[:]=(230,230,230);img[10:50,10:50]=(60,170,90)
        g=cv2.cvtColor(img,cv2.COLOR_RGB2LAB)[30,30].astype(float).tolist()
        m=appearance_mask(img,{'foreground':[g],'foreground_weights':[1.],'background':[[230.,128.,128.]]})
        self.assertTrue(m[30,30]>0)


class TargetPickTests(unittest.TestCase):
    def test_refuses_object_that_looks_more_like_another_item(self):
        from .grasp_flow import pick_target
        objs=[{'category':'usb','candidates':[{'id':'white_phone','category':'phone','matching_score':.703},{'id':'sandisk_usb','category':'usb','matching_score':.582}]},
              {'category':'wallet','candidates':[{'id':'axxen_usb','category':'usb','matching_score':.845},{'id':'sandisk_usb','category':'usb','matching_score':.731}]}]
        with self.assertRaisesRegex(ValueError,'대상 불확실'):pick_target(objs,'sandisk_usb')

    def test_clear_best_is_picked(self):
        from .grasp_flow import pick_target
        objs=[{'category':'lip','candidates':[{'id':'Red_lip','category':'lip_balm','matching_score':.96},{'id':'blue_lip','category':'lip_balm','matching_score':.59}]},
              {'category':'lip','candidates':[{'id':'blue_lip','category':'lip_balm','matching_score':.88},{'id':'Red_lip','category':'lip_balm','matching_score':.70}]}]
        self.assertIs(pick_target(objs,'Red_lip'),objs[0])


class SameCategoryRivalTests(unittest.TestCase):
    def test_other_category_rival_does_not_block(self):
        from .grasp_flow import pick_target
        objs=[{'category':'usb','candidates':[{'id':'blue_lip','category':'lip_balm','matching_score':.72},{'id':'sandisk_usb','category':'usb','matching_score':.60}]}]
        self.assertIs(pick_target(objs,'sandisk_usb'),objs[0])
