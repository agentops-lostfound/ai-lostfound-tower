"""Synthetic single-scene links only; no team DB, real photos, or robot."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agents.chatbot import Chatbot
from agents.guidance import Guidance
from agents.matching_inspection import MatchingInspection
from agents.scene_bindings import bind_scene, scene_digest
from tools.check_chat_matching import synthetic_scene


class SceneBindingsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 5, 3, tzinfo=timezone.utc)
        self.report = synthetic_scene()
        self.items = ['A-20261105-0001', 'B-20261105-0001', 'S-20261105-0001']
        self.manifest = {'capture_id': 'synthetic-capture-001', 'captured_at': self.now.isoformat(),
            'report_sha256': scene_digest(self.report), 'bindings': [
                {'vision_id': obj['id'], 'item_id': iid} for obj, iid in zip(self.report['objects'], self.items)]}

    def bind(self):
        return bind_scene(self.report, self.manifest, clock=lambda: self.now)

    def resolve(self, scene, numbers, check=lambda _item: True, **kwargs):
        return scene.resolve_candidates(numbers, capture_id=kwargs.get('capture_id', self.manifest['capture_id']),
            report_sha256=kwargs.get('report_sha256', self.manifest['report_sha256']), inventory_check=check)

    def test_mapping_uses_explicit_ids_not_manifest_order_or_candidate_rank(self):
        self.manifest['bindings'].reverse()
        scene = self.bind()
        self.assertEqual(self.resolve(scene, [2, 1]), (self.items[1], self.items[0]))
        self.assertNotIn(self.items[0], repr(scene))

    def test_report_manifest_and_returned_snapshot_mutations_do_not_change_the_link(self):
        scene = self.bind()
        self.report['objects'].reverse()
        self.manifest['bindings'][0]['item_id'] = 'A-20261105-0099'
        first = scene.snapshot()
        first['objects'].clear()
        self.assertEqual(len(scene.snapshot()['objects']), 3)
        self.assertEqual(self.resolve(scene, [1]), (self.items[0],))

    def test_wrong_scene_hash_capture_and_modified_report_are_rejected(self):
        scene = self.bind()
        for key, value in [('capture_id', 'another-capture'), ('report_sha256', '0'*64)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.resolve(scene, [1], **{key: value})
        self.report['objects'][0]['qwen']['features']['colors'] = ['white']
        with self.assertRaises(ValueError):
            self.bind()

    def test_missing_extra_duplicate_and_invalid_receipt_links_are_rejected(self):
        mutations = [lambda m: m['bindings'].pop(),
            lambda m: m['bindings'].append(copy.deepcopy(m['bindings'][0])),
            lambda m: m['bindings'][0].update(vision_id=999),
            lambda m: m['bindings'][0].update(vision_id=True),
            lambda m: m['bindings'][0].update(item_id='not-a-receipt'),
            lambda m: m['bindings'][0].update(item_id=m['bindings'][1]['item_id']),
            lambda m: m['bindings'][0].update(vision_id=m['bindings'][1]['vision_id'])]
        for mutate in mutations:
            manifest = copy.deepcopy(self.manifest); mutate(manifest)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                bind_scene(self.report, manifest, clock=lambda: self.now)

    def test_expiry_future_time_timezone_and_capture_time_mismatch_are_rejected(self):
        scene = self.bind()
        self.now += timedelta(seconds=300)
        self.assertEqual(self.resolve(scene, [1]), (self.items[0],))
        self.now += timedelta(microseconds=1)
        with self.assertRaises(ValueError): self.resolve(scene, [1])
        for captured in [(self.now+timedelta(seconds=1)).isoformat(), '2026-11-05T03:00:00', 'bad-time']:
            manifest = {**self.manifest, 'captured_at': captured}
            with self.subTest(captured=captured), self.assertRaises(ValueError):
                bind_scene(self.report, manifest, clock=lambda: self.now)
        self.report['captured_at'] = '2026-11-05T03:01:00+00:00'
        self.manifest['report_sha256'] = scene_digest(self.report)
        with self.assertRaises(ValueError): self.bind()

        report = synthetic_scene()
        report['objects'][0]['center_px'][0] = 10**400
        manifest = {**self.manifest, 'report_sha256': scene_digest(report)}
        with self.assertRaises(ValueError): bind_scene(report, manifest, clock=lambda: self.now)

    def test_incomplete_or_malformed_scene_does_not_create_a_binding(self):
        for changed in [None, 'failed']:
            report = copy.deepcopy(self.report)
            report['sequence'] = None if changed is None else {'status': changed}
            manifest = {**self.manifest, 'report_sha256': scene_digest(report)}
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                bind_scene(report, manifest, clock=lambda: self.now)
        self.report['objects'][0]['qwen'] = 'invalid'
        self.manifest['report_sha256'] = scene_digest(self.report)
        with self.assertRaises(ValueError): self.bind()

    def test_candidate_validation_and_inventory_fail_closed_without_partial_results(self):
        scene = self.bind()
        for numbers in [[True], [0], [4], [1, 1], [1, 2, 3, 1], '1']:
            check = MagicMock(return_value=True)
            with self.subTest(numbers=numbers), self.assertRaises(ValueError): self.resolve(scene, numbers, check)
            check.assert_not_called()
        for check in [None, lambda _item: False, lambda _item: 1]:
            with self.subTest(check=check), self.assertRaises(ValueError): self.resolve(scene, [1], check)
        check = MagicMock(side_effect=[True, False])
        with self.assertRaises(ValueError): self.resolve(scene, [1, 2], check)
        self.assertEqual(check.call_count, 2)

    def test_real_matching_checks_the_selected_receipt_and_never_returns_it(self):
        check = MagicMock(return_value=True)
        output = Chatbot(Guidance()).inspect_inventory_matching('회색 USB 찾아줘', self.bind(), check)
        check.assert_called_once_with(self.items[1])
        self.assertTrue(output['inventory_link_checked'])
        self.assertEqual(output['candidate_numbers'], [2])
        self.assertFalse(output['identity_verified'])
        self.assertFalse(output['reservation_created'])
        self.assertFalse(output['robot_authorized'])
        for item in self.items: self.assertNotIn(item, str(output))

    def test_inventory_failure_is_sanitized_and_staleness_is_rechecked_after_matching(self):
        inspector = MatchingInspection()
        check = MagicMock(side_effect=RuntimeError('SYNTHETIC_PRIVATE_DSN'))
        output = inspector.ask_bound('검정 지갑', self.bind(), check)
        self.assertEqual(output['status'], 'inspection_unavailable')
        self.assertTrue(output['matching_performed'])
        self.assertFalse(output['inventory_link_checked'])
        self.assertNotIn('SYNTHETIC_PRIVATE_DSN', str(output))
        scene = self.bind()
        original = inspector.ask
        def delayed(question, report):
            output = original(question, report)
            self.now += timedelta(seconds=301)
            return output
        inspector.ask = delayed
        check = MagicMock(return_value=True)
        self.assertFalse(inspector.ask_bound('검정 지갑', scene, check)['inventory_link_checked'])
        check.assert_not_called()

    def test_no_candidates_or_ambiguous_description_does_not_call_inventory(self):
        inspector, scene = MatchingInspection(), self.bind()
        for text in ['빨간 지갑', '휴대폰처럼 생긴 물건']:
            check = MagicMock(return_value=True)
            output = inspector.ask_bound(text, scene, check)
            self.assertFalse(output['inventory_link_checked'])
            check.assert_not_called()
        self.assertFalse(inspector.ask_bound('검정 지갑', self.manifest, check)['inventory_link_checked'])

    def test_invalid_json_and_expiry_configuration_are_rejected(self):
        for limit in [True, 0, -1, 3601, float('nan')]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                bind_scene(self.report, self.manifest, clock=lambda: self.now, max_age=limit)
        report = copy.deepcopy(self.report)
        report['objects'][0]['center_px'][0] = float('nan')
        with self.assertRaises(ValueError): scene_digest(report)

    def test_expiry_during_inventory_check_rejects_the_entire_result(self):
        scene = self.bind()
        def slow_inventory(_item):
            self.now += timedelta(seconds=301)
            return True
        with self.assertRaises(ValueError): self.resolve(scene, [1], slow_inventory)
