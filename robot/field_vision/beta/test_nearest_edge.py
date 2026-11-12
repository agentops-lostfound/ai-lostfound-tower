"""v0.2.78: wide items — the object edge nearest to the fixed finger (scan outward)."""
import unittest
import numpy as np
from .partial_boundary import nearest_edge
from .object_reference import large_item

FINGER={'frame_size':[640,480],'contour':[[60,357],[196,357],[196,479],[60,479]]}


def scene(edge=230,pale=True,patch=False):
    im=np.zeros((480,640,3),np.uint8);im[:]=(120,200,160)          # foam (H~75, S~100)
    if pale:im[:,100:edge]=(200,215,205)                              # bleached foam, S~18
    im[:,edge:600]=(175,170,215)                                      # lavender phone body
    if patch:im[200:260,400:460]=(120,200,160)                        # foam-coloured logo patch
    return im


class NearestEdgeTests(unittest.TestCase):
    def test_edge_found_next_to_finger_despite_bleached_foam(self):
        e=nearest_edge(scene(),{'fixed_finger':FINGER})
        self.assertTrue(e['usable_for_gap']);self.assertAlmostEqual(e['points'][1][0],230,delta=2)
        self.assertEqual(e['source'],'nearest_to_finger')
    def test_inner_patch_does_not_move_edge(self):
        e=nearest_edge(scene(patch=True),{'fixed_finger':FINGER})
        self.assertAlmostEqual(e['points'][0][0],230,delta=2)
    def test_object_over_finger_gives_edge_left_of_finger(self):
        e=nearest_edge(scene(edge=170,pale=False),{'fixed_finger':FINGER})
        self.assertLess(e['points'][1][0],196);self.assertGreater(e['overlap_rows'],100)
    def test_finger_on_right_is_mirrored(self):
        im=np.ascontiguousarray(scene()[:,::-1])
        right=dict(FINGER,contour=[[639-x,y] for x,y in FINGER['contour']])
        e=nearest_edge(im,{'fixed_finger':right})
        self.assertAlmostEqual(e['points'][1][0],639-230,delta=3)
    def test_no_finger_registration_raises(self):
        with self.assertRaises(ValueError):nearest_edge(scene(),{})
    def test_large_item_is_by_measured_width(self):
        self.assertTrue(large_item({'physical_size_mm':{'width':72}}))
        self.assertFalse(large_item({'physical_size_mm':{'width':22}}));self.assertFalse(large_item({}))


if __name__=='__main__':unittest.main()
