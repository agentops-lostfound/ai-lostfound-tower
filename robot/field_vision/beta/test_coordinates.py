import unittest
import cv2
import numpy as np
from PIL import Image
from .coordinates import DEFAULT,convert,validate


class CoordinateTests(unittest.TestCase):
    def test_temporary_center_and_mm(self):
        config=dict(DEFAULT,points=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],width_mm=800,height_mm=400)
        r=convert(Image.new('RGB',(1000,600)),[500,300],config)
        np.testing.assert_allclose(r['normalized'],[.5,.5],atol=1e-5)
        np.testing.assert_allclose(r['mm'],[400,200],atol=1e-4)
        self.assertTrue(r['temporary']);self.assertFalse(r['robot_ready'])
        self.assertFalse(convert(Image.new('RGB',(1000,600)),[0,0],config)['inside'])

    def test_crossed_points_rejected(self):
        with self.assertRaises(ValueError): validate(dict(DEFAULT,points=[[0,0],[1,1],[1,0],[0,1]]))

    def test_missing_real_markers_has_no_fallback(self):
        with self.assertRaises(ValueError): convert(Image.new('RGB',(800,600),'white'),[400,300],dict(DEFAULT,mode='aruco'))

    def test_four_real_markers(self):
        image=np.full((600,800,3),255,np.uint8)
        dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
        for ident,(x,y) in enumerate([(50,50),(650,50),(650,450),(50,450)]):
            image[y:y+70,x:x+70]=cv2.aruco.generateImageMarker(dictionary,ident,70)[:,:,None]
        r=convert(Image.fromarray(image),[384.5,284.5],dict(DEFAULT,mode='aruco'))
        np.testing.assert_allclose(r['normalized'],[.5,.5],atol=.005)
        self.assertFalse(r['temporary']);self.assertEqual(set(r['detected_ids']),{0,1,2,3})
