"""CPU-only tests, using actual team contract shapes and mocked matcher arithmetic."""
import copy
import unittest
from unittest.mock import patch

from matching.qwen_bridge import QwenMatchingPart


def fixture():
    raw = {'sequence': {'status': 'complete'}, 'objects': [{
        'id': 9, 'bbox': [5, 6, 25, 40], 'center_px': [15, 23],
        'qwen': {'status': 'ok', 'features': {
            'category': 'phone', 'colors': ['dark blue'], 'shape': 'rectangular',
            'materials': ['plastic'], 'logos_or_text': ['PRIVATE 1234'],
            'sticker_status': 'present', 'stickers': [{'shape': 'cartoon', 'position': 'lower left'}],
            'distinctive_features': ['cartoon sticker lower left']}}}]}
    det = [{'object_id': 9, 'box': [5, 6, 25, 40], 'center': [15, 23],
            'features': {'category': '모형폰', 'color': '확인 불가', 'shape': 'rectangular',
                         'mark': '스티커 있음', 'visible_text': '확인 불가',
                         'material': 'plastic', 'confidence': .9}}]
    return raw, det


class FakeMatcher:
    def match(self, candidates, query):
        assert candidates[0]['features']['colors'] == ['dark blue']
        assert candidates[0]['features']['stickers'][0]['position'] == 'lower left'
        return ([{'id': 9, 'final_score': .91, 'eligible': True}],
                {'status': 'matched', 'selected_id': 9, 'top_candidate_id': 9, 'margin': None}, {})


class BridgeTests(unittest.TestCase):
    def test_original_features_and_no_robot(self):
        from agents.backends import CompositeBackend
        report, detections = fixture()
        bridge = QwenMatchingPart(report, FakeMatcher())
        backend = CompositeBackend(matcher=bridge)
        result = backend.match_item({'category': 'phone'}, detections)
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(result['index'], 0)
        self.assertFalse(bridge.last_diagnostics['robot_authorized'])
        self.assertNotIn('PRIVATE 1234', str(bridge.last_diagnostics))

    def test_partial_scene_denied(self):
        report, detections = fixture()
        report['objects'].append(copy.deepcopy(report['objects'][0]) | {'id': 10})
        self.assertEqual(QwenMatchingPart(report, FakeMatcher()).match_item({}, detections)['reason'], 'incomplete_scene')

    def test_qwen_failure_denied(self):
        report, detections = fixture()
        report['objects'][0]['qwen']['status'] = 'failed'
        self.assertEqual(QwenMatchingPart(report, FakeMatcher()).match_item({}, detections)['reason'], 'qwen_not_ok')

    def test_geometry_mismatch_denied(self):
        report, detections = fixture()
        detections[0]['center'] = [0, 0]
        self.assertEqual(QwenMatchingPart(report, FakeMatcher()).match_item({}, detections)['reason'], 'geometry_mismatch')

    def test_empty_scene_denied(self):
        report, _ = fixture()
        self.assertEqual(QwenMatchingPart(report, FakeMatcher()).match_item({}, [])['reason'], 'no_contract_detections')

    def test_mismatch_rank_id_denied(self):
        report, detections = fixture()
        class Wrong:
            def match(self, candidates, query):
                return ([{'id': 123, 'final_score': .7, 'eligible': True}], {'status': 'matched'}, {})
        self.assertEqual(QwenMatchingPart(report, Wrong()).match_item({}, detections)['reason'], 'unrecognized_ranked_id')


if __name__ == '__main__':
    unittest.main()
