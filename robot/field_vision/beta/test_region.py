import unittest
from PIL import Image, ImageDraw
from .region import find_region, pixel_box


class RegionTests(unittest.TestCase):
    def test_green_board_with_object_inside(self):
        image=Image.new('RGB',(1000,600),'#654321')
        draw=ImageDraw.Draw(image)
        draw.rectangle((100,100,900,500),fill='#55c49a')
        draw.rectangle((300,200,400,300),fill='pink')
        roi=find_region(image)
        box=pixel_box(image,roi)
        self.assertLessEqual(box[0],100)
        self.assertGreaterEqual(box[2],900)
        self.assertGreater(image.crop(box).width,800)

    def test_no_board_does_not_guess(self):
        with self.assertRaises(ValueError):
            find_region(Image.new('RGB',(640,480),'white'))
