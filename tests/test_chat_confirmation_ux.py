"""Current-summary explicit text consent, recovery, and unchanged write boundaries."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from agents.chat_intake import IntakeAgent, confirmation_requested
from test_chat_intake import FakeDesk

CASES = json.loads((Path(__file__).with_name('confirmation_language_cases.json')).read_text(encoding='utf-8'))


def ready(agent, sid):
    for q in ('습득 신고하기', '흰색 보조배터리', '초량', '승강장'):
        result = agent.step(sid, q)
    assert result['status'] == 'intake_confirm', result
    return agent.confirmation(sid)


class ConfirmationUxTests(unittest.TestCase):
    def test_affirmations_require_proof_then_write_once(self):
        for i, q in enumerate(CASES['affirmative']):
            with self.subTest(q=q):
                desk = FakeDesk(); agent = IntakeAgent(desk=desk); sid = 'clear-'+str(i)
                proof = ready(agent, sid)
                self.assertTrue(confirmation_requested(q))
                before = dict(agent.active(sid)['slots'])
                denied = agent.step(sid, q)
                self.assertEqual(denied['status'], 'intake_confirm')
                self.assertIn('아직 접수 전', denied['answer'])
                self.assertEqual(desk.calls, [])
                self.assertEqual(agent.active(sid)['slots'], before)
                self.assertEqual(agent.step(sid, q, action=proof)['status'], 'intake_done')
                self.assertEqual(agent.step(sid, q, action=proof)['status'], 'intake_done')
                self.assertEqual(len(desk.calls), 1)

    def test_mixed_negative_questions_and_instructions_never_confirm_even_with_proof(self):
        for i, q in enumerate(CASES['not_affirmative']):
            with self.subTest(q=q):
                self.assertFalse(confirmation_requested(q))
                desk = FakeDesk(); agent = IntakeAgent(desk=desk); sid = 'mixed-'+str(i)
                proof = ready(agent, sid)
                agent.step(sid, q, action=proof)
                self.assertEqual(desk.calls, [])

    def test_stale_proof_after_correction_requires_latest_summary(self):
        desk = FakeDesk(); agent = IntakeAgent(desk=desk)
        old = ready(agent, 'corrected')
        agent.step('corrected', '색은 검정으로 바꿔줘')
        current = agent.confirmation('corrected')
        self.assertNotEqual(old, current)
        r = agent.step('corrected', '네 이대로 접수해주세요', action=old)
        self.assertEqual(r['status'], 'intake_confirm')
        self.assertIn('최신 요약', r['answer'])
        self.assertEqual(desk.calls, [])
        self.assertEqual(agent.step('corrected', '네 이대로 접수해주세요', action=current)['status'], 'intake_done')
        self.assertEqual(len(desk.calls), 1)

    def test_confusion_and_status_questions_keep_slots_and_do_not_write(self):
        desk = FakeDesk(); agent = IntakeAgent(desk=desk); proof = ready(agent, 'help')
        before = dict(agent.active('help')['slots'])
        for q in ('접수된거야?', '접수 안돼요', '왜 자꾸 확인하래', '버튼 눌렀는데 안돼요'):
            r = agent.step('help', q)
            self.assertEqual(r['status'], 'intake_confirm')
            self.assertIn('아직 접수되지', r['answer'])
            self.assertEqual(agent.active('help')['slots'], before)
            self.assertEqual(agent.confirmation('help'), proof)
        self.assertEqual(desk.calls, [])

    def test_http_natural_confirmation_still_requires_current_bound_action(self):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        svc = build_sim_service({'TOWER_SIM_SEED': 'empty', 'TOWER_SIM_SPEED': '0',
                                 'TOWER_GPU_LEASE': '0', 'TOWER_SEND': '0', 'TOWER_AGENT_TALK': '0'})
        with patch.dict('os.environ', {'LF_CHAT_RAG_MODEL': '', 'LF_LANGFUSE': '0'}), TestClient(build_app(service=svc)) as client:
            def post(q, **extra):
                return client.post('/chat/questions', json={'question': q, 'session_id': 'typed-proof', **extra})
            for q in ('습득 신고하기', '흰색 보조배터리', '초량', '승강장'):
                r = post(q).json()
            proof = r['confirmation']
            with patch.object(svc.sim, 'found', wraps=svc.sim.found) as found:
                help_reply = post('접수된거야?').json()
                self.assertEqual(help_reply['status'], 'intake_confirm')
                self.assertIn('아직 접수되지', help_reply['answer'])
                r = post('네 이대로 접수해주세요').json()
                self.assertEqual(r['status'], 'intake_confirm')
                found.assert_not_called()
                r = post('네 이대로 접수해주세요', intake_action=proof).json()
                self.assertEqual(r['status'], 'intake_done')
                found.assert_called_once()

    def test_registration_phrase_cannot_confirm_pending_cancellation(self):
        from test_chat_intake import ID
        desk = FakeDesk(); calls = []
        desk.cancel_claim = lambda claim_id, **kwargs: calls.append(claim_id) or {'item_id': 'S-test'}
        agent = IntakeAgent(desk=desk)
        agent.step('cancel-kind', 'C-20261111-0001 취소해 주세요')
        agent.step('cancel-kind', '본인 확인', action=ID)
        proof = agent.confirmation('cancel-kind')
        missing = agent.step('cancel-kind', '네')
        self.assertIn('아직 취소 전', missing['answer'])
        self.assertNotIn('[접수할게요]', missing['answer'])
        help_reply = agent.step('cancel-kind', '왜 자꾸 확인하래')
        self.assertIn('아직 취소되지', help_reply['answer'])
        self.assertNotIn('[접수할게요]', help_reply['answer'])
        for q in ('접수할게요', '네 이대로 접수해주세요', '신고 부탁드려요'):
            result = agent.step('cancel-kind', q, action=proof)
            self.assertEqual(result['status'], 'intake_confirm')
            self.assertIn('유지하려면 [아니요]', result['answer'])
            self.assertNotIn('[접수할게요]', result['answer'])
        self.assertEqual(calls, [])
        self.assertEqual(agent.step('cancel-kind', '네', action=proof)['status'], 'intake_done')
        self.assertEqual(calls, ['C-20261111-0001'])
