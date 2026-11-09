import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import numpy as np

from run_storage_check import check_counts, crop_section, inspect_storage
from vision.scripts.preview_section import save_selections
from vision.section_regions import load_regions


class StorageCheckTests(unittest.TestCase):
    def test_crop_uses_worktable_to_image_projection_and_rejects_partial_sections(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[20:41, 30:71] = 255
        px_to_mm = [[0.5, 0, -5], [0, 0.5, 0], [0, 0, 1]]
        crop = crop_section(image, px_to_mm, [10, 10, 30, 20])
        self.assertEqual(crop.shape, (20, 40, 3))
        self.assertTrue((crop == 255).all())
        self.assertIsNone(crop_section(image, px_to_mm, [10, 10, 50, 20]))

    @patch('run_storage_check.check_counts')
    def test_selected_section_only_and_count_match_preserves_review(self, check_counts):
        check_counts.return_value = [{'status': 'count_match', 'detected_count': 1}]
        sections = {'phones': {'bounds_mm': [10, 20, 30, 40], 'slots': {'2': 'pose_2'}}}
        inventory = {'phone-id': {'section': 'phones', 'slot': '2'},
                     'wallet-id': {'section': 'wallets', 'slot': '1'}}
        items = {'phone-id': {'category': '모형폰', 'status': '본센터 보관', 'features': {'color': '흰색'}},
                 'wallet-id': {'category': '지갑', 'status': '본센터 보관', 'features': {}}}
        parser = Mock()
        parser.parse.return_value = {'features': {'category': 'phone'}, 'requires_review': True,
                                     'needs_clarification': False}
        matcher = Mock()
        matcher.match.return_value = ([{'id': 'phone-id', 'eligible': True, 'final_score': 1.0}],
                                      {'status': 'matched', 'selected_id': 'phone-id'}, {})

        result = inspect_storage('휴대폰', ['frame'], sections, inventory, items.get, parser, matcher, {}, 'cpu')

        check_counts.assert_called_once_with(['frame'], [10, 20, 30, 40], 1, {}, 'cpu')
        self.assertEqual(result['candidate']['pose'], 'pose_2')
        self.assertEqual(result['status'], 'count_match')
        self.assertEqual(result['matching']['status'], 'needs_confirmation')
        self.assertFalse(result['robot_authorized'])

        parser.parse.return_value['match_block_reasons'] = ['ambiguous_category']
        result = inspect_storage('휴대폰', ['frame'], sections, inventory, items.get, parser, matcher, {}, 'cpu')
        self.assertEqual(result['status'], 'match_held')
        self.assertNotIn('candidate', result)
        check_counts.assert_called_once()

        parser.parse.return_value['match_block_reasons'] = []
        regions = {'image_size_px': [100, 100], 'regions': {'phones': [12, 13, 35, 40]}}
        result = inspect_storage('휴대폰', ['frame'], sections, inventory, items.get, parser, matcher, {}, 'cpu',
                                 regions=regions)
        self.assertEqual(result['status'], 'count_match')
        check_counts.assert_called_with(['frame'], [12, 13, 35, 40], 1, {}, 'cpu', image_size_px=[100, 100])

        regions['regions'].clear()
        result = inspect_storage('휴대폰', ['frame'], sections, inventory, items.get, parser, matcher, {}, 'cpu',
                                 regions=regions)
        self.assertEqual(result['reason'], 'missing_saved_region')
        self.assertEqual(check_counts.call_count, 2)

    @patch('run_storage_check.YoloDetector')
    @patch('run_storage_check.cv2.imdecode', return_value=np.zeros((100, 120, 3), dtype=np.uint8))
    @patch('run_storage_check.np.fromfile')
    def test_saved_region_rejects_resolution_change_before_loading_yolo(self, _, __, detector):
        attempts = check_counts(['frame'], [0, 0, 50, 50], 1, {}, 'cpu', image_size_px=[100, 100])
        self.assertEqual(attempts[0]['status'], 'resolution_mismatch')
        self.assertIsNone(attempts[0]['detected_count'])
        detector.assert_not_called()

    @patch('vision.scripts.preview_section.edit_regions')
    def test_save_named_regions_and_cancel_without_overwriting(self, edit_regions):
        image = np.zeros((100, 120, 3), dtype=np.uint8)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'regions.json'
            edit_regions.return_value = {'image_size_px': [120, 100], 'cabinet_bounds_px': [5, 5, 100, 90],
                                         'regions': {'phone': [10, 10, 30, 30], 'usb': [40, 30, 80, 70]}}
            self.assertEqual(save_selections(image, path, ['phone', 'usb']), 0)
            saved = load_regions(path)
            self.assertEqual(saved['image_size_px'], [120, 100])
            self.assertEqual(saved['cabinet_bounds_px'], [5, 5, 100, 90])
            self.assertEqual(saved['regions'], {'phone': [10, 10, 30, 30], 'usb': [40, 30, 80, 70]})

            edit_regions.return_value = None
            self.assertEqual(save_selections(image, path, ['phone', 'wallet']), 2)
            self.assertEqual(load_regions(path), saved)
