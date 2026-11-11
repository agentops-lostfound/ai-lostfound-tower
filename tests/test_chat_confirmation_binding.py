"""확인 값 누락·이전 초안·다른 세션·만료·재전송을 실제 엔진/HTTP 경계에서 검사."""
import json
import threading
import unittest
from unittest import mock

from agents.chat_intake import IntakeAgent, IntakeSessions, check_action
from test_chat_intake import FakeDesk


def ready(agent, sid):
    for q in ('습득 신고하기', '흰색 보조배터리', '해운대', '승강장'):
        result = agent.step(sid, q)
    assert result['status'] == 'intake_confirm'
    return agent.confirmation(sid)


class ConfirmationBindingTest(unittest.TestCase):
    def setUp(self):
        self.desk = FakeDesk()
        self.agent = IntakeAgent(desk=self.desk)

    def test_plain_yes_cannot_write(self):
        ready(self.agent, 'one')
        for q in ('네', '접수할게요', 'ㅇㅇ'):
            self.assertEqual(self.agent.step('one', q)['status'], 'intake_confirm')
        self.assertEqual(self.desk.calls, [])

    def test_old_draft_and_other_session_cannot_write(self):
        old = ready(self.agent, 'one')
        ready(self.agent, 'two')
        self.agent.step('one', '아 서면이었어요')
        current = self.agent.confirmation('one')
        self.assertNotEqual(old, current)
        self.assertEqual(self.agent.step('one', '접수할게요', action=old)['status'], 'intake_confirm')
        self.assertEqual(self.agent.step('two', '접수할게요', action=current)['status'], 'intake_confirm')
        self.assertEqual(self.desk.calls, [])
        self.assertEqual(self.agent.step('one', '접수할게요', action=current)['status'], 'intake_done')
        self.assertIn('서면', self.desk.calls[0][1])

    def test_replay_and_concurrent_requests_write_once(self):
        proof = ready(self.agent, 'one')
        results = []
        def send():
            results.append(self.agent.step('one', '접수할게요', action=proof))
        threads = [threading.Thread(target=send) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r['status'] == 'intake_done' for r in results))
        self.assertEqual(len(self.desk.calls), 1)

    def test_cancel_and_expiry_invalidate_proof(self):
        proof = ready(self.agent, 'one')
        self.agent.step('one', '취소')
        self.assertEqual(self.agent.step('one', '접수할게요', action=proof)['status'], 'intake_failed')
        clock = [0]
        agent = IntakeAgent(desk=self.desk, sessions=IntakeSessions(ttl=10, clock=lambda: clock[0]))
        proof = ready(agent, 'expired')
        clock[0] = 11
        self.assertEqual(agent.step('expired', '접수할게요', action=proof)['status'], 'intake_failed')
        self.assertEqual(self.desk.calls, [])

    def test_wrong_token_and_strict_shape(self):
        proof = ready(self.agent, 'one')
        wrong = {**proof, 'confirmation_token': 'x' * 43}
        self.assertEqual(self.agent.step('one', '네', action=wrong)['status'], 'intake_confirm')
        for bad in ({**proof, 'draft_version': True}, {**proof, 'extra': 1},
                    {**proof, 'confirmation_token': 'short'}, {'type': 'confirm'}):
            with self.assertRaises(ValueError):
                check_action(bad)
        self.assertEqual(self.desk.calls, [])

    def test_claim_cancellation_also_requires_bound_confirmation(self):
        from test_chat_intake import ID
        calls = []
        self.desk.cancel_claim = lambda claim_id, **kwargs: calls.append(claim_id) or {'item_id': 'S-test'}
        self.agent.step('cancel-proof', 'C-20261111-0001 취소해 주세요')
        self.agent.step('cancel-proof', '본인 확인', action=ID)
        proof = self.agent.confirmation('cancel-proof')
        self.assertEqual(self.agent.step('cancel-proof', '네')['status'], 'intake_confirm')
        self.assertEqual(calls, [])
        self.assertEqual(self.agent.step('cancel-proof', '네', action=proof)['status'], 'intake_done')
        self.agent.step('cancel-proof', '네', action=proof)
        self.assertEqual(calls, ['C-20261111-0001'])

    def test_ambiguous_desk_failure_cannot_automatically_repeat_write(self):
        def interrupted(text):
            self.desk.calls.append(('found', text))
            raise TimeoutError('after write')
        self.desk.found = interrupted
        proof = ready(self.agent, 'one')
        self.assertEqual(self.agent.step('one', '네', action=proof)['status'], 'intake_uncertain')
        self.assertEqual(self.agent.step('one', '네', action=proof)['status'], 'intake_uncertain')
        self.assertEqual(len(self.desk.calls), 1)


class ConfirmationHttpTest(unittest.TestCase):
    def test_http_and_stream_supply_proof_without_graph_exposure(self):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        svc = build_sim_service({'TOWER_SIM_SEED': 'full', 'TOWER_SIM_SPEED': '0',
                                 'TOWER_GPU_LEASE': '0', 'TOWER_SEND': '0', 'TOWER_AGENT_TALK': '0'})
        with mock.patch.dict('os.environ', {'LF_CHAT_RAG_MODEL': '', 'LF_LANGFUSE': '0'}):
            client = TestClient(build_app(service=svc))
            def post(q, sid='http-proof', **extra):
                return client.post('/chat/questions', json={'question': q, 'session_id': sid, **extra})
            for q in ('습득 신고하기', '흰색 보조배터리', '해운대', '승강장'):
                result = post(q).json()
            proof = result['confirmation']
            self.assertEqual(post('접수할게요').json()['status'], 'intake_confirm')
            self.assertEqual(post('접수할게요', intake_action={'type': 'confirm'}).status_code, 422)
            done = post('접수할게요', intake_action=proof).json()
            self.assertEqual(done['status'], 'intake_done')
            self.assertNotIn(proof['confirmation_token'], json.dumps(done))
            self.assertEqual(post('접수할게요', intake_action=proof).json()['intake']['item_id'], done['intake']['item_id'])
            for q in ('습득 신고하기', '흰색 보조배터리', '해운대'):
                post(q, 'stream-proof')
            stream = post('승강장', 'stream-proof', stream=True)
            frames = [json.loads(line) for line in stream.text.splitlines() if line.strip()]
            self.assertTrue(any(f.get('done') and 'confirmation' in f for f in frames))

    def test_confirmation_token_stays_out_of_graph_state(self):
        from test_deerflow_langfuse import bot
        b = bot()
        b.intake = IntakeAgent(desk=FakeDesk())
        for q in ('습득 신고하기', '흰색 보조배터리', '해운대', '승강장'):
            result = b.ask(q, session_id='graph-proof')
        proof = result['confirmation']
        original = b.graph.invoke
        seen = []
        def invoke(state, **kwargs):
            seen.append(json.dumps(state))
            out = original(state, **kwargs)
            seen.append(json.dumps(out))
            return out
        with mock.patch.object(b.graph, 'invoke', side_effect=invoke):
            self.assertEqual(b.ask('접수할게요', session_id='graph-proof', intake_action=proof)['status'], 'intake_done')
        self.assertTrue(seen)
        self.assertTrue(all(proof['confirmation_token'] not in s for s in seen))
