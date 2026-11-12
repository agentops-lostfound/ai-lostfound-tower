import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
from .grasp_alignment import measure

class AlignmentTests(unittest.TestCase):
    def test_visible_jaws_decide_rotation(self):
        im=Image.new('RGB',(640,480),'#609e80');d=ImageDraw.Draw(im)
        d.rectangle((40,300,140,470),fill='white');d.rectangle((500,300,600,470),fill='white')
        for angle,aligned in [(90,True),(35,False)]:
            with patch('beta.grasp_alignment.pink_tube',return_value={'long_axis_deg':angle}):
                self.assertEqual(measure(im)['aligned'],aligned)
    def test_missing_jaws_blocks_descent(self):
        with patch('beta.grasp_alignment.pink_tube',return_value={'long_axis_deg':90}):
            with self.assertRaises(ValueError):measure(Image.new('RGB',(640,480),'green'))

    def test_overlap_veto_and_center(self):
        from .grasp_alignment import descent_clearance
        r={'method':'separated_jaws','object_box':[[250,200],[390,200],[390,430],[250,430]],'jaw_boxes':[[100,300,80,100],[460,300,80,100]],'jaw_centers':[[140,350],[500,350]]}
        self.assertTrue(descent_clearance(r,(640,480))['clear'])
        r['jaw_boxes'][0]=[260,300,80,100]
        self.assertFalse(descent_clearance(r,(640,480))['clear'])
    def test_partial_jaw_evidence_never_allows_descent(self):
        from .grasp_alignment import descent_clearance
        self.assertFalse(descent_clearance({'method':'closed_jaws_two_lower_bands'},(640,480))['clear'])
