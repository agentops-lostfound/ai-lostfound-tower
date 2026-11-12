"""v0.2.69: ARM target outline limited to the tracked detector box."""
import unittest

import numpy as np
from PIL import Image

from . import arm_roi
from .overlay import LiveOverlay


class FakeCamera:
    def __init__(self):self.overlay=LiveOverlay()


def scene():
    """Green foam tray, black USB at x170-240, white wall strip at x480+ (like the live ARM view)."""
    im=np.zeros((480,640,3),np.uint8);im[:]=(110,200,160)
    rng=np.random.default_rng(1);im[:]=np.clip(im+rng.normal(0,6,im.shape),0,255).astype(np.uint8)
    im[:,480:]=(225,228,222);im[300:,520:]=(200,170,140)
    im[140:345,170:240]=(30,32,40);im[140:180,178:222]=(180,180,185)
    for x in range(175,235,9):im[200:330,x:x+3]=(70,70,80)          # texture so the tracker has corners
    return Image.fromarray(im)


class ArmRoiTests(unittest.TestCase):
    def tearDown(self):arm_roi.deactivate()

    def test_choose_groups_cap_with_body_and_picks_near_finger(self):
        items=[{'bbox':[168,138,239,348]},{'bbox':[174,138,221,181]},{'bbox':[194,250,214,308]},{'bbox':[500,20,630,200]}]
        self.assertEqual(arm_roi.choose_target(items,(640,480),inner_x=190),0)
        self.assertIsNone(arm_roi.choose_target([{'bbox':[0,0,640,480]}],(640,480)))

    def test_apply_without_box_is_noop_and_with_box_clips(self):
        mask=np.full((480,640),255,np.uint8)
        self.assertTrue((arm_roi.apply(mask)==255).all())
        camera=FakeCamera();image=scene();arm_roi.activate(camera)
        camera.overlay.update(image)
        camera.overlay.set_detections(image,7,[{'bbox':[168,138,239,348],'category':'usb','index':0,'quality':'detected'}])
        camera.overlay.mark_target(7,0,'usb1');arm_roi._active['track']=camera.overlay.tracks[0]['id']
        box=arm_roi.current_box((640,480));self.assertEqual(box[:2],[143,106])
        out=arm_roi.apply(mask);self.assertEqual(out[:,500:].max(),0);self.assertEqual(out[240,200],255)

    def test_background_outline_no_longer_reaches_wall(self):
        from .object_reference import _located_shape
        import cv2
        image=scene();wall=cv2.cvtColor(np.uint8([[[200,200,205]]]),cv2.COLOR_RGB2LAB)[0,0].tolist()
        ref={'foreground':[wall],'background':[[180,100,140]]}   # pale palette (silver/white item) also matches the wall
        free=_located_shape(image,ref)
        self.assertGreater(max(p[0] for p in free['box_pixels']),470)               # old: outline jumps to the wall
        camera=FakeCamera();arm_roi.activate(camera);camera.overlay.update(image)
        camera.overlay.set_detections(image,3,[{'bbox':[168,138,239,348],'category':'usb','index':0,'quality':'detected'}])
        camera.overlay.mark_target(3,0,'usb1');arm_roi._active['track']=camera.overlay.tracks[0]['id']
        boxed=_located_shape(image,ref)
        xs=[p[0] for p in boxed['box_pixels']];self.assertLess(max(xs),260);self.assertGreater(min(xs),150)
        self.assertIn('arm_roi',boxed)


if __name__=='__main__':unittest.main()


class EnclosingBodyTests(unittest.TestCase):
    """v0.2.74: a close phone whose colours match only a logo patch uses its whole body."""
    def frame(self,right=590):
        im=np.zeros((480,640,3),np.uint8);im[:]=(110,200,160)
        im[:,205:right]=(175,170,215)                    # lavender phone body, top-bottom
        im[250:330,360:440]=(120,110,190)                # darker logo patch
        return im
    def test_whole_body_replaces_logo_patch(self):
        from .object_reference import _enclosing_body
        patch={'center_pixels':[400,290],'area_pixels':6400}
        body=_enclosing_body(self.frame(),{},patch)
        xs=[p[0] for p in body['box_pixels']];self.assertLess(min(xs),215);self.assertGreater(max(xs),580)
    def test_body_touching_frame_side_is_not_used(self):
        from .object_reference import _enclosing_body
        self.assertIsNone(_enclosing_body(self.frame(right=640),{},{'center_pixels':[400,290],'area_pixels':6400}))
    def test_large_item_may_touch_far_side_only(self):
        # v0.2.75: close to the floor the phone reaches the far (right) frame edge.
        from .object_reference import _enclosing_body
        finger={'frame_size':[640,480],'contour':[[60,357],[196,357],[196,479],[60,479]]}
        big={'physical_size_mm':{'width':72},'fixed_finger':finger}
        patch={'center_pixels':[400,290],'area_pixels':6400}
        body=_enclosing_body(self.frame(right=640),big,patch)
        self.assertLess(min(p[0] for p in body['box_pixels']),215)
        self.assertIsNone(_enclosing_body(self.frame(right=640),dict(big,physical_size_mm={'width':20}),patch))
        near=self.frame();near[:,0:205]=(175,170,215)                       # touches the finger side
        self.assertIsNone(_enclosing_body(near,big,patch))
    def test_small_patch_of_similar_size_kept(self):
        from .object_reference import _enclosing_body
        self.assertIsNone(_enclosing_body(self.frame(),{},{'center_pixels':[400,290],'area_pixels':90000}))
