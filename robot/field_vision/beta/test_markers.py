import unittest
import cv2
import numpy as np
from PIL import Image
from .markers import exclude_markers, is_marker_box


class MarkerTests(unittest.TestCase):
    def test_four_markers_and_original_preserved(self):
        image=np.full((600,800,3),255,np.uint8)
        dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
        for ident,(x,y) in enumerate([(50,50),(650,50),(50,450),(650,450)]):
            code=cv2.aruco.generateImageMarker(dictionary,ident,70)
            image[y:y+70,x:x+70]=code[:,:,None]
        original=Image.fromarray(image)
        masked,boxes=exclude_markers(original)
        self.assertEqual(len(boxes),4)
        self.assertTrue(np.array_equal(np.asarray(original),image))
        self.assertFalse(np.array_equal(np.asarray(masked),image))
        self.assertTrue(is_marker_box([50,50,120,120],boxes))
        self.assertFalse(is_marker_box([300,250,400,350],boxes))

    def test_no_marker(self):
        _,boxes=exclude_markers(Image.new('RGB',(640,480),'green'))
        self.assertEqual(boxes,[])
