"""저장 후 응답 유실은 실패로 단정하거나 같은 요청을 다시 실행하지 않는다."""
import json
import unittest
from unittest import mock

from agents.chat_intake import IntakeAgent, IntakeSessions
from agents.service import RequestError
from test_chat_intake import FakeDesk, ID
from test_chat_confirmation_binding import ready


def lost_ready(agent, sid):
    for q in ('검정 지갑 서면에서 잃어버려서 접수해 주세요', '어제', '없어요'):
        agent.step(sid, q)
    agent.step(sid, '본인 확인', action=ID)
    return agent.confirmation(sid)


class UncertainWriteTest(unittest.TestCase):
    def test_found_response_loss_blocks_repeat_new_start_cancel_and_expiry(self):
        clock = [0]
        desk = FakeDesk()
        def lost_reply(text):
            desk.calls.append(('found', text))
            raise TimeoutError('private-error-text')
        desk.found = lost_reply
        sessions = IntakeSessions(ttl=10, clock=lambda: clock[0])
        a = IntakeAgent(desk=desk, sessions=sessions)
        proof = ready(a, 'one')
        first = a.step('one', '접수할게요', action=proof)
        self.assertEqual(first['status'], 'intake_uncertain')
        self.assertFalse(first['intake']['retry_allowed'])
        self.assertNotIn('private-error-text', json.dumps(first))
        for q in ('접수할게요', '취소', '습득 신고하기', '처리됐어요?'):
            self.assertEqual(a.step('one', q)['status'], 'intake_uncertain')
        clock[0] = 1000
        sessions.put('other', {'stage': 'collect'})
        self.assertEqual(a.step('one', '접수할게요', action=proof)['status'], 'intake_uncertain')
        self.assertEqual(len(desk.calls), 1)
        self.assertEqual(sessions.get('one')['slots'], {})
        self.assertNotIn(proof['confirmation_token'], json.dumps(sessions.get('one')))
        self.assertIsNone(a.confirmation('one'))

    def test_malformed_success_response_does_not_allow_second_write(self):
        for reply in ({}, {'item_id': None}, {'item_id': ' '}, {'item_id': True}):
            with self.subTest(reply=reply):
                desk = FakeDesk()
                def malformed(text):
                    desk.calls.append(('found', text))
                    return reply
                desk.found = malformed
                a = IntakeAgent(desk=desk)
                proof = ready(a, 'one')
                for _ in range(2):
                    self.assertEqual(a.step('one', '네', action=proof)['status'], 'intake_uncertain')
                self.assertEqual(len(desk.calls), 1)

    def test_lost_and_followup_answer_response_loss_are_held(self):
        for followup in (False, True):
            with self.subTest(followup=followup):
                desk = FakeDesk(ask_first=followup)
                a = IntakeAgent(desk=desk)
                def interrupted(*args):
                    desk.calls.append(('interrupted',))
                    raise ConnectionError('after write')
                if not followup:
                    desk.lost = interrupted
                proof = lost_ready(a, 'one')
                result = a.step('one', '접수할게요', action=proof)
                if followup:
                    self.assertEqual(result['intake']['stage'], 'quiz')
                    desk.answer = interrupted
                    result = a.step('one', '별 스티커')
                self.assertEqual(result['status'], 'intake_uncertain')
                a.step('one', '별 스티커')
                self.assertEqual(desk.calls.count(('interrupted',)), 1)

    def test_cancel_response_loss_is_not_reported_as_failure_or_repeated(self):
        desk = FakeDesk()
        def interrupted(*args, **kwargs):
            desk.calls.append(('cancel',))
            raise TimeoutError('after cancellation')
        desk.cancel_claim = interrupted
        a = IntakeAgent(desk=desk)
        a.step('one', 'C-20261111-0001 취소해 주세요')
        a.step('one', '본인 확인', action=ID)
        proof = a.confirmation('one')
        result = a.step('one', '네', action=proof)
        self.assertEqual(result['status'], 'intake_uncertain')
        self.assertIn('취소 결과', result['answer'])
        self.assertEqual(a.step('one', '아니요')['status'], 'intake_uncertain')
        self.assertEqual(a.step('one', '네', action=proof)['status'], 'intake_uncertain')
        self.assertEqual(len(desk.calls), 1)

    def test_known_business_rejection_remains_failure(self):
        desk = FakeDesk()
        desk.found = mock.Mock(side_effect=RequestError('형식 거절'))
        a = IntakeAgent(desk=desk)
        proof = ready(a, 'one')
        self.assertEqual(a.step('one', '네', action=proof)['status'], 'intake_failed')
        self.assertIsNone(a.active('one'))

    def test_exception_name_alone_cannot_claim_known_rejection(self):
        FakeRequestError = type('RequestError', (Exception,), {})
        desk = FakeDesk()
        desk.found = mock.Mock(side_effect=FakeRequestError('sensitive'))
        a = IntakeAgent(desk=desk)
        proof = ready(a, 'one')
        self.assertEqual(a.step('one', '네', action=proof)['status'], 'intake_uncertain')

    def test_http_repeat_stops_at_engine_and_supervisor(self):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        svc = build_sim_service({'TOWER_SIM_SEED': 'full', 'TOWER_SIM_SPEED': '0',
                                 'TOWER_GPU_LEASE': '0', 'TOWER_SEND': '0', 'TOWER_AGENT_TALK': '0'})
        with mock.patch.dict('os.environ', {'LF_CHAT_RAG_MODEL': '', 'LF_LANGFUSE': '0'}):
            client = TestClient(build_app(service=svc))
            def post(q, **extra):
                return client.post('/chat/questions', json={'question': q, 'session_id': 'unknown-http', **extra}).json()
            for q in ('습득 신고하기', '흰색 보조배터리', '해운대', '승강장'):
                result = post(q)
            proof = result['confirmation']
            with mock.patch.object(svc.sim, 'found', side_effect=TimeoutError('write response missing')) as write:
                first = post('접수할게요', intake_action=proof)
                self.assertEqual(first['status'], 'intake_uncertain')
                for q in ('네', '취소', '습득 신고하기'):
                    result = post(q, intake_action=proof)
                    self.assertEqual(result['status'], 'intake_uncertain')
                    self.assertNotIn('confirmation', result)
                self.assertEqual(write.call_count, 1)
                self.assertTrue(any('미확정' in str(d) or '불명' in str(d) for d in first['decisions']))
