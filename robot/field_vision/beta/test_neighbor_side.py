"""flow-41bc1bd2 regressions: dark neighbor chosen as a white phone, 30mm offset cap, side space."""
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from .object_reference import dominant_colors, target_component
from .gap_learning import offset_amount
from .partial_boundary import side_free_mm


class NeighborSideTests(unittest.TestCase):
    def test_minor_lens_color_is_not_used_for_localization(self):
        colors = [[235, 128, 128], [12, 128, 128], [210, 130, 120]]
        weights = [.70, .03, .27]   # black lens is a small detail of a white phone
        chosen = dominant_colors(colors, weights)
        self.assertNotIn([12, 128, 128], chosen)
        self.assertEqual(dominant_colors(colors, None), colors)  # old references unchanged

    def test_region_entirely_beyond_fixed_finger_is_not_the_target(self):
        mask = np.zeros((480, 640), np.uint8)
        mask[:, 0:130] = 255        # dark neighbor left of the fixed finger (bigger)
        mask[100:300, 220:400] = 255  # actual target right of the finger
        ref = {'fixed_finger': {'frame_size': [640, 480], 'contour': [[120, 340], [190, 340], [190, 479], [120, 479]]}}
        kept = target_component(mask, ref)
        self.assertEqual(kept[:, :130].max(), 0)
        self.assertEqual(kept[200, 300], 255)
        # Overlap case (target under the finger) is kept.
        overlap = np.zeros((480, 640), np.uint8); overlap[100:470, 150:420] = 255
        self.assertEqual(target_component(overlap, ref)[400, 160], 255)

    def test_offset_cap_scales_with_width(self):
        settings = {'preoffset_k': .585, 'preoffset_c_mm': -1.06}
        phone = offset_amount(74.4, 4.0, settings, 'k', path=Path('missing.json'))
        self.assertAlmostEqual(abs(phone['signed_mm']), .585 * 74.4 - 1.06, places=3)  # 42.5, no longer 30
        tube = offset_amount(47.6, 4.0, settings, 'k', path=Path('missing.json'))
        self.assertAlmostEqual(abs(tube['signed_mm']), .585 * 47.6 - 1.06, places=3)
        self.assertLessEqual(offset_amount(200, 4.0, settings, 'k', path=Path('missing.json'))['cap_mm'], 60)

    def test_side_space_sees_undetected_neighbor(self):
        rgb = np.zeros((300, 400, 3), np.uint8); rgb[:] = (80, 200, 140)   # green foam
        rgb[100:200, 150:250] = (240, 240, 240)                              # target, 100px wide
        rgb[100:200, 290:330] = (20, 20, 20)                                 # neighbor 40px to the right
        box = [[150, 100], [250, 100], [250, 200], [150, 200]]
        space = side_free_mm(Image.fromarray(rgb), box, [100, 0], 100.0, max_mm=80)  # 1px = 1mm
        self.assertLess(space['positive_mm'], 45)
        self.assertGreaterEqual(space['negative_mm'], 80)


if __name__ == '__main__':
    unittest.main()
