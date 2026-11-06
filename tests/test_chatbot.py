import base64
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from agents.guidance import Guidance
from agents.chatbot import Chatbot
from agents.chat_rag import GroundedRag
from agents.chat_search import SearchAgent, DemoItemDatabase, PostgresItemSearch, SQL_SEARCH, public_candidates
from agents.lost_input import DescriptionService
from agents.lost_api import create_app


class ChatbotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = DemoItemDatabase(Path(self.tmp.name) / 'demo.sqlite3')
        self.guide = Guidance()
        self.bot = Chatbot(self.guide, search=SearchAgent(self.database))

    def test_router_distinguishes_help_policy_and_search(self):
        for question, expected in [('검정 지갑 찾아줘', 'search'), ('USB 있나요?', 'search'),
                ('물건 검색 방법 알려줘', 'guidance'), ('수령 절차 알려줘', 'guidance'),
                ('주말 운영시간은?', 'guidance'), ('개인정보 어떻게 저장해?', 'guidance')]:
            self.assertEqual(self.bot.ask(question)['agent'], expected, question)

    def test_demo_db_returns_only_public_matching_candidates(self):
        result = self.bot.ask('검정 지갑 찾아줘')
        self.assertTrue(result['item_search_performed'])
        self.assertEqual(result['database_mode'], 'demo_sqlite')
        self.assertIn('실제 습득물이 아닙니다', result['answer'])
        self.assertEqual(result['candidates'], [{'candidate_no': 1, 'category': '지갑', 'color': '검정'}])
        self.assertNotIn('DEMO-001', str(result))
        self.assertFalse(result['reservation_created'])
        self.assertIn('추가 특징', result['answer'])
        self.assertIn('반영하지', result['answer'])

    def test_empty_result_is_not_assertion_that_item_does_not_exist(self):
        result = self.bot.ask('빨간 지갑 찾아줘')
        self.assertEqual(result['status'], 'items_not_found')
        self.assertIn('확정한 것은 아닙니다', result['answer'])

    def test_all_six_categories_can_be_queried_in_demo_database(self):
        for category in ['지갑', '휴대폰', 'USB', '립밤', '보조배터리', '핸드크림']:
            self.assertEqual(self.bot.ask(category + ' 찾아줘')['status'], 'items_found', category)

    def test_mixed_question_keeps_both_guidance_and_search(self):
        result = self.bot.ask('검정 지갑 찾아줘. 수령 절차도 알려줘')
        self.assertEqual(result['agent'], 'both')
        self.assertTrue(result['sources'])
        self.assertTrue(result['candidates'])
        self.assertIn('시연용 가상 DB', result['answer'])
        result = self.bot.ask('검정 지갑 찾아줘. 주말 운영시간은?')
        self.assertEqual(result['status'], 'answered')          # 11/6 시연 운영 기준
        self.assertTrue(result['candidates'])
        self.assertIn('시연 기준', result['answer'])

    def test_ambiguous_and_missing_item_require_details(self):
        for question in ['내 물건 찾아줘', '지갑 말고 USB 찾아줘', '지갑과 립밤 찾아줘']:
            result = self.bot.ask(question)
            self.assertEqual(result['status'], 'search_needs_details')
            self.assertFalse(result['item_search_performed'])

    def test_real_db_requires_trusted_authorization_before_any_query(self):
        database = MagicMock(mode='postgres')
        result = SearchAgent(database).ask('검정 지갑 찾아줘', access_token='forged')
        self.assertEqual(result['status'], 'authentication_required')
        database.search.assert_not_called()
        database.search.return_value = []
        self.assertEqual(SearchAgent(database, authorize=lambda token: token == 'trusted').ask(
            '검정 지갑 찾아줘', 'trusted', {'lost_date': '2026-11-01', 'lost_line': '2호선', 'lost_station': '해운대역'})['status'], 'items_not_found')

    def test_db_error_never_falls_back_to_invented_demo_items(self):
        database = MagicMock(mode='postgres')
        database.search.side_effect = RuntimeError('database secret')
        result = SearchAgent(database, authorize=lambda _: True).ask('지갑 찾아줘', 'trusted',
            {'lost_date': '2026-11-01', 'lost_line': '2호선', 'lost_station': '해운대역'})
        self.assertEqual(result['status'], 'search_unavailable')
        self.assertNotIn('secret', str(result))
        self.assertFalse(result['item_search_performed'])

    def test_pii_rejected_before_agent_or_database(self):
        with self.assertRaises(ValueError):
            self.bot.ask('010-1234-5678 지갑 찾아줘')

    def test_policy_question_is_not_answered_with_demo_items(self):
        result = self.bot.ask('지갑 보관기간은 며칠인가요?')
        self.assertEqual([s['topic'] for s in result['sources']], ['retention'])
        self.assertFalse(result['item_search_performed'])

    def test_public_projection_rejects_secret_or_invalid_db_values(self):
        rows = [('DEMO-001', '지갑', '검정', '본센터 보관'),
                ('SECRET', '지갑', '검정', '본센터 보관'),
                ('DEMO-002', '지갑', '전화번호 비밀', '본센터 보관'),
                ('DEMO-003', '지갑', '검정', '인계 완료')]
        self.assertEqual(len(public_candidates(rows)), 1)

    def test_postgres_uses_read_only_fixed_query_and_bound_parameters(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [('A-W01', '지갑', '검정', '본센터 보관')]
        connect = MagicMock(return_value=connection)
        database = PostgresItemSearch('secret-dsn', connect=connect)
        result = database.search('지갑', '검정')
        self.assertTrue(connection.read_only)
        self.assertEqual(result[0]['item_id'], 'A-W01')
        sql, params = cursor.execute.call_args.args
        self.assertEqual(sql, SQL_SEARCH)
        self.assertEqual(params[:3], ('지갑', '검정', '검정'))
        for forbidden in ['private_features', 'finder_contact', 'claim', 'photo_path']:
            self.assertNotIn(forbidden, sql)
        self.assertNotIn('secret-dsn', repr(database))

    def test_api_ignores_caller_claims_of_identity_verification(self):
        database = MagicMock(mode='postgres')
        bot = Chatbot(self.guide, search=SearchAgent(database))
        client = TestClient(create_app(DescriptionService(), self.guide, bot), base_url='http://127.0.0.1')
        result = client.post('/chat/questions', json={'question': '검정 지갑 찾아줘', 'id_verified': True, 'consent': True})
        self.assertEqual(result.json()['status'], 'authentication_required')
        database.search.assert_not_called()


class RagTests(unittest.TestCase):
    def test_model_selects_relevant_atomic_paragraph_with_its_qualifier(self):
        generate = lambda _: {'message': {'content': json.dumps({'passage_ids': [1]})}}
        result = GroundedRag(Guidance(), 'local-test', request=generate).ask('사진은 어떻게 올려요?')
        self.assertTrue(result['generation_used'])
        self.assertIn('추측하지 않습니다', result['answer'])
        self.assertNotIn('녹음 파일 입력', result['answer'])

    def test_retrieved_evidence_reaches_model_and_answer_keeps_caveats(self):
        payloads = []
        def generate(payload):
            payloads.append(payload)
            passages = json.loads(payload['messages'][1]['content'])['retrieved_passages']
            return {'message': {'content': json.dumps({'passage_ids': list(range(len(passages)))})}}
        result = GroundedRag(Guidance(), model='local-test', request=generate).ask('수령 절차 알려줘')
        self.assertTrue(result['generation_used'])
        self.assertIn('부산역 본센터', result['answer'])                # 11/6 수령 근거: 찾기 번호 → 신분증 → 부산역 본센터
        self.assertIn('찾기 번호', result['answer'])
        self.assertIn('retrieved_passages', payloads[0]['messages'][1]['content'])
        self.assertTrue(result['sources'])

    def test_model_cannot_omit_qualifiers_or_invent_sentences(self):
        for value in [{'passage_ids': []}, {'passage_ids': [999]}, {'passage_ids': [True]}, {'answer': '24시간 운영합니다'}]:
            result = GroundedRag(Guidance(), 'local-test', request=lambda _: {'message': {'content': json.dumps(value)}}).ask('수령 절차 알려줘')
            self.assertFalse(result['generation_used'])
            self.assertNotIn('24시간', result['answer'])

    def test_unknown_policy_never_calls_model(self):
        generate = MagicMock()
        result = GroundedRag(Guidance(), 'local-test', request=generate).ask('주말 운영시간은?')
        self.assertEqual((result['status'], result['generation_status']), ('answered', 'fixed_policy_text'))
        generate.assert_not_called()                             # 시연 운영 기준은 모델이 고르거나 바꾸지 않음
        self.assertEqual(GroundedRag(Guidance(), 'local-test', request=generate).ask('몇 시에 열어? 아니면 모르는 거야?')['status'], 'answered')
        generate.assert_not_called()

    def test_offline_model_falls_back_to_document_evidence(self):
        generate = MagicMock(side_effect=OSError('secret host'))
        result = GroundedRag(Guidance(), 'local-test', request=generate).ask('수령 절차 알려줘')
        self.assertFalse(result['generation_used'])
        self.assertTrue(result['sources'])
        self.assertNotIn('secret', str(result))


class ChatVoiceTests(unittest.TestCase):
    @staticmethod
    def wav():
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
            audio.writeframes(b'\0\0' * 16000)
        return base64.b64encode(buf.getvalue()).decode()

    def test_transcription_does_not_send_question_or_create_proposal(self):
        worker = MagicMock()
        worker.__enter__.return_value = worker
        worker.transcribe.return_value = {'status': 'transcribed', 'text': '수령 절차 알려주세요'}
        service = DescriptionService(transcriber=lambda: worker)
        client = TestClient(create_app(service), base_url='http://127.0.0.1')
        result = client.post('/chat/transcriptions', json={'audio_base64': self.wav()})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {'text': '수령 절차 알려주세요', 'sent': False})
        self.assertEqual(service._pending, {})
        worker.__exit__.assert_called_once()

    def test_invalid_audio_and_missing_transcriber_have_clear_errors(self):
        client = TestClient(create_app(DescriptionService()), base_url='http://127.0.0.1')
        self.assertEqual(client.post('/chat/transcriptions', json={'audio_base64': 'bad'}).status_code, 422)
        self.assertEqual(client.post('/chat/transcriptions', json={'audio_base64': self.wav()}).status_code, 503)

    def test_private_transcription_and_overlong_text_are_not_returned(self):
        for text in ['010-1234-5678', '가' * 501]:
            worker = MagicMock(); worker.__enter__.return_value = worker
            worker.transcribe.return_value = {'status': 'transcribed', 'text': text}
            client = TestClient(create_app(DescriptionService(transcriber=lambda: worker)), base_url='http://127.0.0.1')
            result = client.post('/chat/transcriptions', json={'audio_base64': self.wav()})
            self.assertEqual(result.status_code, 422)
            self.assertNotIn(text, result.text)
