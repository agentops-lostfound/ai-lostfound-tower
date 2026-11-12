import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from .grasp_flow import make_plan
from .test_robot_actions import state
from .finger_edges import edges
from .grasp_flow import GraspFlow
from unittest.mock import Mock
import tempfile
import json
from pathlib import Path


class FlowTests(unittest.TestCase):
    def test_plan_uses_detected_center_and_axis_not_fixed_center(self):
        image=Image.new('RGB',(1000,600))
        result={'id':'fresh-job','captured':123,'frame_id':42,'items':[{'category':'hand_cream','features':{'body_color':'pink'},'quality':'accepted','bbox':[300,100,500,400]}]}
        cfg={'mode':'aruco','width_mm':468.8}
        shape={'grasp_center_pixels':[80,120],'long_axis_segment':[[80,80],[80,160]],'box_pixels':[[60,80],[100,80],[100,160],[60,160]]}
        def convert(image,point):return {'inside':True,'temporary':False,'mm':[float(point[0]),float(point[1])]}
        def transform(point,height):return {'surface_mm':[point[1],-point[0],15],'approach_mm':[point[1],-point[0],15+height]}
        ref={'model_sha256':'hash','robot_frame':{'id':'frame'},'reference_model_radians':[0]*5}
        with patch('beta.grasp_flow.apply_alignment',side_effect=lambda r:r),patch('beta.grasp_flow.geometry',return_value=(cfg,np.zeros((4,2)),[0,1,2,3])),patch('beta.grasp_flow.build_reference',return_value=({'kind':'selected_object_lab'},shape)),patch('beta.grasp_flow.convert',side_effect=convert),patch('beta.grasp_flow.transform',side_effect=transform),patch('beta.grasp_flow.frame_config',return_value={'id':'frame'}),patch('beta.grasp_flow.Model') as model,patch('beta.grasp_flow.json.loads',return_value=ref),patch('pathlib.Path.read_text',return_value='{}'):
            model.return_value.hash='hash'
            for category in ['hand_cream','usb','lip_balm','phone','wallet','unknown_object']:
                result['items'][0]['category']=category
                plan=make_plan(image,result)
                self.assertEqual(plan['category'],category)
                simple=make_plan(image,result,simple_mode=True)
                self.assertEqual(simple['center_pixels'],[400,250])
                self.assertEqual(simple['approach_xyz_mm'],[250,-400,60])
        self.assertEqual(plan['verification_lift_xyz_mm'],plan['approach_xyz_mm']);self.assertEqual(plan['center_pixels'],[380,220]);self.assertEqual(plan['approach_xyz_mm'],[220,-380,60]);self.assertEqual(plan['detection_id'],'fresh-job')

    def test_empty_detection_has_no_fixed_coordinate_fallback(self):
        with patch('beta.grasp_flow.geometry',return_value=({'mode':'aruco','width_mm':468.8},[],[])):
            with self.assertRaises(ValueError):make_plan(Image.new('RGB',(640,480)),{'items':[]})

    def test_white_fingers_missing_never_count_as_contact(self):
        self.assertFalse(edges(Image.new('RGB',(640,480),'green'))['bilateral_contact_candidate'])

    def test_edge_result_is_json_serializable(self):
        from PIL import ImageDraw
        image=Image.new('RGB',(640,480),'#609e80');d=ImageDraw.Draw(image)
        d.rectangle((240,0,390,430),fill='#e5a1bc');d.rectangle((30,230,160,479),fill='#ddd8d5');d.rectangle((470,230,620,479),fill='#ddd8d5')
        result=edges(image);json.dumps(result)
        self.assertFalse(result['bilateral_contact_candidate'])

    def test_stall_without_visual_contact_does_not_lift(self):
        engine=Mock();engine.cameras={'top':Mock(),'arm':Mock()};image=Image.new('RGB',(640,480),'green')
        engine.cameras['top'].snapshot.return_value=(image,100,123)
        engine.cameras['arm'].snapshot.return_value=(image,101,124)
        engine.submit.return_value={'status':'complete','result':{'id':'new','items':[]}}
        plan={'approach_xyz_mm':[170,0,60],'grasp_xyz_mm':[170,0,30],
              'verification_lift_xyz_mm':[170,0,40],'marker_corners_pixels':np.zeros((4,2)).tolist(),'reference':{}}
        s=state();s['motion']={'status':'contact_candidate','contact_source':'motor_stall'}
        with tempfile.TemporaryDirectory() as temp,patch('beta.grasp_flow.DATA',Path(temp)),patch('beta.grasp_flow.actions') as action,patch('beta.grasp_flow.manual') as manual,patch('beta.grasp_flow.read_home',return_value={'raw_ticks':{n:2000 for n in s['joints'] for n in [n['name']]}}),patch('beta.grasp_flow.make_plan',return_value=plan),patch('beta.grasp_flow.joints_for',return_value={j['name']:2000 for j in s['joints']}),patch('beta.grasp_flow.geometry',return_value=({},np.zeros((4,2)),[])):
            manual.snapshot.return_value=s;action.cancel.is_set.return_value=False
            action.snapshot.return_value={'run_id':'test'};action.check.return_value=s;action.move.return_value=s
            with self.assertRaises(ValueError):GraspFlow(engine).run(None,45,15)
            labels=[call.args[1] for call in action.move.call_args_list]
            self.assertFalse(any('확인 들기' in label for label in labels))
            self.assertIn('접근',labels[0]);self.assertIn('열기',labels[1]);self.assertIn('하강',labels[2])
            approach=action.move.call_args_list[0].args[0]
            self.assertEqual(approach['gripper'],2000)
            opening=action.move.call_args_list[1].args[0]
            self.assertTrue(all(opening[j['name']]==j['raw_ticks'] for j in s['joints'] if j['name']!='gripper'))
