import unittest
from PIL import Image
from .scene_filter import suppress_parts,is_support_preview


class SceneFilterTests(unittest.TestCase):
    def test_protruding_cap_removed_but_separate_object_kept(self):
        body=dict(category='hand_cream',bbox=[206,119,471,297],score=.5)
        cap=dict(category='hand_cream',bbox=[193,255,233,300],score=.18)
        separate=dict(category='hand_cream',bbox=[312,439,387,533],score=.36)
        self.assertEqual(suppress_parts([body,cap,separate]),[body,separate])

    def test_green_confirmed_object_is_preserved(self):
        image=Image.new('RGB',(200,200),'#55c49a')
        self.assertTrue(is_support_preview(image,dict(bbox=[20,20,120,120],preview=True)))
        self.assertFalse(is_support_preview(image,dict(bbox=[20,20,120,120],preview=False)))
