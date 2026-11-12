import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from PIL import Image
from . import tcp_reference as reference
from .tcp_calibration import signature,write_json,read_json


class TCPReferenceTests(unittest.TestCase):
    def test_center_comes_from_saved_marker_dimensions(self):
        cfg={'mode':'aruco','width_mm':468.8,'height_mm':202}
        self.assertEqual(reference.board_point(cfg,'center'),[234.4,101])
        self.assertEqual(reference.board_point(cfg,'right'),[274.4,101])
        with self.assertRaises(ValueError):reference.board_point(dict(cfg,mode='temporary'),'center')

    def test_target_overlay_uses_live_marker_geometry(self):
        cfg={'mode':'aruco','width_mm':468.8,'height_mm':202}
        corners=np.array([[50,30],[550,30],[550,270],[50,270]],np.float32)
        with patch.object(reference,'geometry',return_value=(cfg,corners,[0,1,2,3])),patch.object(reference,'transform',return_value={'approach_mm':[180,0,65],'surface_mm':[180,0,15]}),patch.object(reference,'frame_config',return_value={'frame':1}):
            info=reference.reference_info(Image.new('RGB',(600,300)),'center',50)
            np.testing.assert_allclose(info['pixel'],[300,150],atol=.001)
            self.assertEqual(info['target_robot_mm'],[180,0,65])

    def test_required_motion_is_not_copied_as_successful_target(self):
        r={'model_sha256':'hash','reference_raw_ticks':[0]*5,'reference_model_radians':[0]*5,'robot_frame':{},'serial':'test'}
        last={'key':'center','height_mm':50,'board_mm':[234.4,101],'finished':time.time(),
              'move_id':'move1','frame':{},'reference_signature':signature(r),'corners_pixels':[[0,0],[100,0],[100,100],[0,100]]}
        engine=Mock();engine.cameras={'top':Mock()};engine.cameras['top'].snapshot.return_value=(None,1,time.time())
        sample={'id':'sample1','reference_signature':signature(r)}
        with tempfile.TemporaryDirectory() as temp,patch.object(reference,'DATA',Path(temp)),patch.object(reference,'LATEST',last),patch.object(reference,'reference_info',return_value=last),patch.object(reference,'draft',return_value={'samples':[]}),patch.object(reference,'stationary_sample',return_value=sample) as capture,patch.object(reference.actions,'snapshot',return_value={'running':False}):
            write_json(Path(temp)/'working_calibration.json',r)
            reference.record_observation(engine,[10,-20],48,move_id='move1')
            capture.assert_called_once_with([224.4,121.0],48)
            saved=read_json(Path(temp)/'tcp_draft.json')['samples'][0]
            self.assertEqual(saved['required_board_motion_mm'],[10,-20])
            self.assertEqual(saved['reference_target_board_mm'],[234.4,101])
            with self.assertRaisesRegex(ValueError,'기록이 바뀌'):reference.record_observation(engine,[0,0],50,move_id='old')
