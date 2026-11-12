import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from .kinematics import Model,rotation
from .tcp_calibration import fit_samples,verify_sample,signature,active_profile


def samples_for(base,tool):
    samples=[]
    for i,(x,y,z) in enumerate([(0,0,0),(.5,0,0),(0,.5,0),(-.4,-.3,.4),(.2,-.5,-.3)]):
        r=rotation([1,0,0],x)@rotation([0,1,0],y)@rotation([0,0,1],z)
        p=np.array([130+i*15,-50+i*20,70+i*2.])
        if i==4:p[0]+=80
        samples.append({'rotation':r.tolist(),'model_position_mm':p.tolist(),
                        'measured_position_mm':(p+base+r@tool).tolist()})
    return samples


class TCPCalibrationTests(unittest.TestCase):
    def test_separates_base_and_rotating_tool_offset(self):
        base=np.array([12.,-8,4]);tool=np.array([9.,-5,17])
        s=samples_for(base,tool);fit=fit_samples(s[:4])
        np.testing.assert_allclose(fit['base_translation_mm'],base,atol=1e-9)
        np.testing.assert_allclose(fit['tcp_local_mm'],tool,atol=1e-9)
        self.assertLess(verify_sample(fit,s[4],s[:4])['error_mm'],1e-8)

    def test_identical_or_only_roll_rotations_cannot_separate_offsets(self):
        samples=samples_for(np.zeros(3),np.ones(3))
        for i,s in enumerate(samples):
            s['rotation']=rotation([0,0,1],i*.3).tolist()
        with self.assertRaisesRegex(ValueError,'분리할 수 없는'):fit_samples(samples)

    def test_wrong_independent_point_does_not_verify(self):
        samples=samples_for(np.ones(3),np.ones(3));fit=fit_samples(samples[:4])
        samples[4]['measured_position_mm'][0]+=15
        with self.assertRaisesRegex(ValueError,'보정 적용 안 함'):verify_sample(fit,samples[4],samples[:4])
        with self.assertRaisesRegex(ValueError,'30mm'):verify_sample(fit,samples[0],samples[:4])

    def test_model_uses_same_tcp_for_all_poses_without_changing_orientation(self):
        raw=Model(use_position_calibration=False)
        with patch('beta.tcp_calibration.active_profile',return_value={'base_translation_mm':[12,-8,4],'tcp_local_mm':[9,-5,17]}):
            calibrated=Model()
        for q in ([0,.2,-.4,1.3,0],[.6,.4,-.5,1.4,1.1],[-.5,-.3,.3,.8,-1.]):
            a=raw.forward(q);b=calibrated.forward(q)
            np.testing.assert_allclose(b['position'],a['position']+[12,-8,4]+a['rotation']@[9,-5,17])
            np.testing.assert_allclose(b['opening_axis'],a['opening_axis'])
            np.testing.assert_allclose(b['tool_axis'],a['tool_axis'])
            solved=calibrated.inverse(b['position'],seed=q,prefer_seed=True)
            self.assertTrue(solved['reachable_in_model'])

    def test_frame_or_reference_change_invalidates_common_profile(self):
        ref={'model_sha256':'abc','reference_raw_ticks':[1]*5,'reference_model_radians':[0]*5,'robot_frame':{'id':1},'serial':'test'}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def put(name,value):(root/name).write_text(json.dumps(value),encoding='utf-8')
            put('working_calibration.json',ref);put('robot_frame.json',ref['robot_frame'])
            put('tcp_active.json',{'verified':True,'model_sha256':'abc','reference_signature':signature(ref)})
            self.assertIsNotNone(active_profile('abc',root))
            put('robot_frame.json',{'id':2})
            with self.assertRaises(ValueError):active_profile('abc',root)
