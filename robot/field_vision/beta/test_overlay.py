import unittest
import cv2
import numpy as np
from PIL import Image
from .overlay import LiveOverlay
from .cameras import Camera


class OverlayContracts(unittest.TestCase):
    def setUp(self):
        pixels=np.full((240,320,3),120,dtype=np.uint8)
        rng=np.random.default_rng(421)
        pixels[70:150,90:210]=rng.integers(0,255,size=(80,120,3),dtype=np.uint8)
        self.image=Image.fromarray(pixels)
        self.item={'index':0,'category':'wallet','bbox':[90,70,210,150],'quality':'detected'}

    def test_live_box_follows_motion(self):
        overlay=LiveOverlay();overlay.update(self.image);overlay.set_detections(self.image,1,[self.item])
        shifted=Image.fromarray(cv2.warpAffine(np.asarray(self.image),np.float32([[1,0,7],[0,1,4]]),(320,240),borderValue=(120,120,120)))
        overlay.update(shifted)
        tracks=overlay.visible()
        self.assertEqual(len(tracks),1)
        for actual,expected in zip(tracks[0]['bbox'],[97,74,217,154]): self.assertAlmostEqual(actual,expected,delta=1)

    def test_lost_target_does_not_leave_a_stale_box(self):
        overlay=LiveOverlay();overlay.update(self.image);overlay.set_detections(self.image,1,[self.item])
        overlay.update(Image.new('RGB',self.image.size,(120,120,120)))
        self.assertEqual(overlay.visible(),[])

    def test_expired_detection_is_hidden(self):
        overlay=LiveOverlay(max_age=30);overlay.set_detections(self.image,1,[self.item])
        overlay.tracks[0]['created']-=31
        self.assertEqual(overlay.visible(),[])

    def test_candidates_are_display_only_and_opt_in(self):
        overlay=LiveOverlay();candidate=dict(self.item,preview=True,quality='review')
        overlay.set_detections(self.image,1,[],[candidate])
        self.assertEqual(overlay.visible(),[])
        overlay.show_candidates=True
        self.assertTrue(overlay.visible()[0]['preview'])

    def test_model_input_remains_unannotated(self):
        camera=Camera('test',{'name':'test','enabled':False,'source':''},lambda *a,**k:None)
        camera.publish(self.image);raw=camera.jpeg
        camera.overlay.set_detections(self.image,1,[self.item]);camera.publish(self.image)
        self.assertEqual(camera.jpeg,raw)
        self.assertNotEqual(camera.display_jpeg,raw)
        image,_,_=camera.snapshot()
        self.assertEqual(image.size,self.image.size)

if __name__=='__main__':unittest.main()
