import unittest
from PIL import Image,ImageDraw
from .grasp_geometry import pink_tube


class GraspGeometryTests(unittest.TestCase):
    def test_vertical_and_horizontal_tube_need_different_wrist_alignment(self):
        for box,ready in [((200,80,260,350),True),((100,180,500,250),False)]:
            image=Image.new('RGB',(640,480),'#60aa83');ImageDraw.Draw(image).rectangle(box,fill='#e7a8bf')
            result=pink_tube(image)
            self.assertEqual(result['arm_camera_orientation_candidate'],ready)
            self.assertGreater(result['length_pixels'],result['width_pixels'])

    def test_empty_scene_is_not_grasp_candidate(self):
        with self.assertRaises(ValueError):pink_tube(Image.new('RGB',(640,480),'green'))

    def test_tight_blue_detector_crop_keeps_external_border(self):
        image=Image.new('RGB',(97,260),'#609e80')
        ImageDraw.Draw(image).rectangle((5,2,91,250),fill='#a6bfd9')
        result=pink_tube(image,cropped=True,color='blue')
        self.assertLess(result['area_pixels'],97*260*.98)
        self.assertGreater(result['length_pixels']/result['width_pixels'],1.6)
