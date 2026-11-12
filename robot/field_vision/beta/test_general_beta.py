import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
from PIL import Image,ImageDraw
from .object_reference import build_reference,appearance_mask,shape_from_mask
from .lift_tracking import LiftTracker
from . import workflow
import numpy as np

class GeneralBetaTests(unittest.TestCase):
    def test_reference_accepts_non_tube_colors_and_square(self):
        for color in ['#dbb334','#8040a0','#101012','#eeeeee']:
            im=Image.new('RGB',(240,200),'#609e80');ImageDraw.Draw(im).rectangle((70,50,170,150),fill=color)
            ref,shape=build_reference(im,[65,45,175,155])
            self.assertFalse(shape['axis_reliable'])
            out=shape_from_mask(appearance_mask(np.asarray(im),ref))
            self.assertLess(np.linalg.norm(np.asarray(out['center_pixels'])-[120,100]),3)
    def test_no_background_reference_is_rejected(self):
        with self.assertRaises(ValueError):build_reference(Image.new('RGB',(100,100),'red'),[0,0,100,100])
    def test_lift_no_evidence_is_not_success(self):
        im=Image.new('RGB',(120,100),'green')
        ref={'foreground':[[200,150,140]],'background':[[100,90,150]]}
        tracker=LiftTracker(im,ref,1,1)
        for i in range(2,6):tracker.sample(im,i,i)
        self.assertEqual(tracker.result(40)['status'],'unconfirmed')
    def test_lift_decision_requires_motion_contrast_and_lift(self):
        tracker=object.__new__(LiftTracker);tracker.frames=3
        tracker.samples=[dict(object_shift_px=2,background_shift_px=v) for v in [6,9,12]]
        self.assertEqual(tracker.result(30)['status'],'held_likely')
        self.assertEqual(tracker.result(0)['status'],'unconfirmed')
        tracker.samples=[dict(object_shift_px=25,background_shift_px=25)]*3
        self.assertEqual(tracker.result(30)['status'],'not_held_likely')
    def test_rolling_body_with_steady_outline_is_held(self):
        # v0.2.71 (flow-aace61d2): printed text slid 52px (cylinder rolled) but the outline stayed.
        tracker=object.__new__(LiftTracker);tracker.frames=3;tracker.last_image=object()
        tracker.samples=[dict(object_shift_px=v,background_shift_px=v*2.4) for v in [11,47,53]]
        tracker.outline={'center':[270,301],'length':364,'width':162}
        tracker.locate=lambda im:{'center':[263,296],'length':367,'width':143}
        self.assertEqual(tracker.result(25)['status'],'held_likely')
        tracker.locate=lambda im:{'center':[263,250],'length':367,'width':143}      # outline moved 51px -> not held
        self.assertEqual(tracker.result(25)['status'],'not_held_likely')
        tracker.locate=lambda im:{'center':[270,301],'length':364,'width':162}
        self.assertEqual(tracker.result(10)['status'],'unconfirmed')                 # lift too small
    def test_settings_are_validated_and_persisted(self):
        with tempfile.TemporaryDirectory() as d,patch.object(workflow,'DATA',Path(d)):
            workflow.save({'grasp_height_mm':5,'gap_high_px':60})
            self.assertEqual(workflow.load()['gap_high_px'],60)
            with self.assertRaises(ValueError):workflow.save({'grasp_height_mm':-10})
            self.assertEqual(workflow.load()['grasp_height_mm'],5)
