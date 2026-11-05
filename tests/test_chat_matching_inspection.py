"""Real team parser/bridge/hybrid policy; explicit doubles only for semantic models."""
import copy
import unittest
from unittest.mock import MagicMock
from agents.chatbot import Chatbot
from agents.guidance import Guidance
from agents.matching_inspection import MatchingInspection
from matching.hybrid import HybridMatcher
from matching.korean_query import KoreanFirstParser
from matching.policy import load_config
from tools.check_chat_matching import synthetic_scene


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.bot = Chatbot(Guidance())

    def test_real_structured_policy_and_scene_indices_without_public_identifiers(self):
        for text, numbers in [('검정 지갑 찾아줘', [1]), ('회색 USB 찾아줘', [2]),
                              ('빨간 지갑 찾아줘', []), ('빨간색 아니고 검정 지갑', [1])]:
            with self.subTest(text=text):
                scene = synthetic_scene()
                scene['objects'][0]['qwen']['features']['logos_or_text'] = ['SYNTHETIC_PRIVATE_TEXT']
                output = self.bot.inspect_matching(text, scene)
                self.assertEqual(output['status'], 'review_required')
                self.assertEqual(output['candidate_numbers'], numbers)
                self.assertTrue(output['matching_performed'])
                for private in ['710', 'SYNTHETIC_PRIVATE_TEXT', 'bbox', 'score', 'center_px', text]:
                    self.assertNotIn(private, str(output))
                self.assertFalse(output['robot_authorized'])
                self.assertFalse(output['identity_verified'])
                self.assertFalse(output['reservation_created'])

    def test_ambiguous_unsupported_and_negated_descriptions_never_call_models_or_matcher(self):
        parser, matcher = MagicMock(), MagicMock()
        inspector = MatchingInspection(parser, matcher)
        for text in ['빨간 우산', '검정 물건인데 모르겠어', '휴대폰처럼 생긴 검정 물건',
                     '검정인지 남색인지 모르는 지갑', '지갑이 아니에요', '지갑과 USB',
                     '지갑 뒷면에는 스티커가 없어요']:
            with self.subTest(text=text):
                self.assertEqual(inspector.ask(text, synthetic_scene())['status'], 'clarification_needed')
        parser.parse.assert_not_called()
        matcher.match.assert_not_called()

    def test_missing_models_do_not_drop_detail_constraints(self):
        output = self.bot.inspect_matching('검정 지갑에 꽃 스티커가 있어요', synthetic_scene())
        self.assertEqual(output['status'], 'feature_models_required')
        self.assertFalse(output['matching_performed'])
        output = self.bot.inspect_matching('검정 VOVA 보조배터리', synthetic_scene())
        self.assertEqual(output['reason'], 'embedding_not_configured')

    def test_incomplete_failed_and_invalid_scenes_are_held(self):
        for damage in ['sequence', 'qwen', 'geometry', 'empty', 'nan', 'duplicate']:
            scene = synthetic_scene()
            if damage == 'sequence': scene['sequence']['status'] = 'failed'
            elif damage == 'qwen': scene['objects'][0]['qwen']['status'] = 'failed'
            elif damage == 'geometry': scene['objects'][0]['center_px'] = [1]
            elif damage == 'empty': scene['objects'] = []
            elif damage == 'nan': scene['objects'][0]['center_px'][0] = float('nan')
            else: scene['objects'].append(copy.deepcopy(scene['objects'][0]))
            with self.subTest(damage=damage):
                output = self.bot.inspect_matching('검정 지갑', scene)
                self.assertEqual(output['status'], 'inspection_unavailable')
                self.assertFalse(output['matching_performed'])

    def test_private_input_and_oversized_input_are_rejected_before_parser(self):
        inspector = MatchingInspection(MagicMock(), MagicMock())
        for text in ['지갑 010-1234-5678', '가'*501]:
            with self.subTest(text=text[:10]), self.assertRaises(ValueError):
                inspector.ask(text, synthetic_scene())
        inspector.parser.parse.assert_not_called()

    def test_translator_and_embedding_wiring_keeps_source_and_never_authorizes(self):
        class Translator:
            model_id, init_seconds = 'explicit-test-double', 0
            def parse(self, text, **_kwargs):
                self.received = text
                return {'translation': 'A flower sticker.', 'timing': {'output_tokens': 4, 'parse_seconds': 0}}
        class Ranker:
            def prepare(self, candidates):
                self.candidates = candidates
                return {}
            def rank(self, text):
                self.received = text
                return ([{**c, 'cosine_similarity': .8} for c in self.candidates], {})
        translator, ranker = Translator(), Ranker()
        inspector = MatchingInspection(KoreanFirstParser(translator=translator),
                                       HybridMatcher(load_config(), offline=True, ranker=ranker))
        scene = synthetic_scene()
        scene['objects'][0]['qwen']['features'].update(sticker_status='present', stickers=[{'shape': 'flower'}])
        output = self.bot.inspect_matching('검정 지갑에 꽃 스티커가 있어요', scene, inspector)
        self.assertIn('꽃 스티커', translator.received)
        self.assertIn('flower sticker', ranker.received)
        self.assertTrue(output['matching_performed'])
        self.assertEqual(output['status'], 'review_required')
        self.assertFalse(output['robot_authorized'])

    def test_parser_cannot_override_source_attributes_and_errors_are_sanitized(self):
        parser, matcher = MagicMock(), MagicMock()
        parser.parse.return_value = {'features': {'category': 'phone', 'colors': ['black'],
            'sticker_status': 'unknown', 'free_text': ''}, 'needs_clarification': False, 'warnings': []}
        inspector = MatchingInspection(parser, matcher)
        self.assertEqual(inspector.ask('검정 지갑', synthetic_scene())['status'], 'clarification_needed')
        matcher.match.assert_not_called()
        parser.parse.side_effect = OSError('PRIVATE_PATH_AND_TOKEN')
        output = inspector.ask('검정 지갑', synthetic_scene())
        self.assertEqual(output['status'], 'inspection_unavailable')
        self.assertNotIn('PRIVATE_PATH_AND_TOKEN', str(output))

    def test_existing_public_chat_does_not_accept_scene_injection_or_inspection_access(self):
        from fastapi.testclient import TestClient
        from agents.lost_api import create_app
        client = TestClient(create_app(chatbot=self.bot), base_url='http://127.0.0.1')
        output = client.post('/chat/questions', json={'question': '검정 지갑 찾아줘', 'report': synthetic_scene()})
        self.assertEqual(output.status_code, 200)
        self.assertEqual(output.json()['status'], 'search_unavailable')
        self.assertEqual(client.post('/chat/matching-inspection', json={}).status_code, 404)

    def test_concurrent_requests_do_not_mix_mutable_model_state(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        inspector = MatchingInspection()
        original = inspector.parser.parse
        def blocked(text):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('test timeout')
            return original(text)
        inspector.parser.parse = blocked
        with ThreadPoolExecutor(1) as worker:
            first = worker.submit(inspector.ask, '검정 지갑', synthetic_scene())
            try:
                self.assertTrue(entered.wait(1))
                output = inspector.ask('회색 USB', synthetic_scene())
                self.assertEqual(output['status'], 'inspection_busy')
                self.assertFalse(output['matching_performed'])
            finally:
                release.set()
            self.assertEqual(first.result()['candidate_numbers'], [1])
        self.assertEqual(inspector.ask('회색 USB', synthetic_scene())['candidate_numbers'], [2])
