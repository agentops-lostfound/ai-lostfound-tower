"""공통 대화 상태의 수명·순서·권한 경계와 현재 입력 단계 해석."""
import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agents.chatbot import Chatbot
from agents.chat_dialogue import DialogueMemory, bound_dialogue, model_context, social_kind
from agents.chat_intake import IntakeAgent
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance
from chat_confirmation_helpers import ui_ask
from test_chat_intake import FakeDesk, ID


class DialogueMemoryTest(unittest.TestCase):
    def test_capacity_expiry_and_channel_isolation(self):
        now = [0]
        memory = DialogueMemory(capacity=2, ttl=10, clock=lambda: now[0])
        with memory.turn('one', 'web') as first:
            first.thread = 'search'
        with memory.turn('one', 'staff') as second:
            self.assertIsNone(second.thread)
        with memory.turn('third'):
            self.assertEqual(len(memory._entries), 2)
        self.assertNotIn(('web', 'one'), memory._entries)
        now[0] = 11
        with memory.turn('third') as fresh:
            self.assertIsNone(fresh.thread)
            self.assertEqual(len(memory._entries), 1)

    def test_same_session_cannot_overtake_or_evict_active_request(self):
        memory = DialogueMemory(capacity=1, wait=0.02)
        seen = []
        def pending():
            with memory.turn('same') as value:
                seen.append(value)
        with memory.turn('same') as frame:
            with memory.turn('other') as blocked:
                self.assertIsNone(blocked)
            thread = threading.Thread(target=pending)
            thread.start()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(seen, [None])
            self.assertIs(memory._entries[('web', 'same')], frame)
        self.assertEqual(frame.pins, 0)

    def test_contextvars_restore_and_task_summary_is_live_without_identity(self):
        memory = DialogueMemory()
        task = {'kind': 'lost', 'stage': 'collect', 'asked': 'color', 'slots': {'category': '립밤', 'identity': ID}}
        with memory.turn('one') as frame, bound_dialogue(frame, lambda: task):
            self.assertEqual(model_context()['current_task']['asked'], 'color')
            task['asked'] = 'station'
            self.assertEqual(model_context()['current_task']['asked'], 'station')
            self.assertNotIn('name_masked', json.dumps(model_context()))
            self.assertNotIn('id_no_masked', json.dumps(model_context()))
        self.assertEqual(model_context(), {})

    def test_identity_and_receipt_values_are_not_remembered(self):
        with DialogueMemory().turn('one') as frame:
            frame.observe('가상테스트이름', {'intake': {'kind': 'lost', 'stage': 'collect'}, 'answer': '홍*동 ******-1******'}, {'asked': 'identity'})
            frame.observe('C-20261112-9999', {'answer': '찾기 번호 C-20261112-9999', 'status': 'answered'})
            stored = json.dumps(frame.turns, ensure_ascii=False)
            for value in ('가상테스트이름', '홍*동', '******-1******', '9999'):
                self.assertNotIn(value, stored)
            self.assertIsNone(frame.receipt)  # 사용자 입력만으로 실제 발급 상태를 만들지 않는다.

    def test_recent_turns_are_bounded(self):
        with DialogueMemory().turn('one') as frame:
            for i in range(30):
                frame.observe(f'질문 {i}', {'answer': '안내'})
            self.assertEqual(len(frame.turns), 8)
            self.assertEqual(len(frame.history([])), 4)


class StatefulDialogueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.desk = FakeDesk()
        self.bot = Chatbot(Guidance(), search=SearchAgent(DemoItemDatabase(Path(self.tmp.name)/'items.sqlite')),
                           intake=IntakeAgent(desk=self.desk))

    def ask(self, q, sid='dialogue-owner', **kw):
        return ui_ask(self.bot, q, session_id=sid, **kw)

    def test_search_returns_after_long_detour_without_browser_history(self):
        self.ask('검정 립밤 찾아줘')
        self.ask('운영시간 알려줘')
        for q in ['안녕', '고마워요', '응', '알겠어', '다녀왔어']:
            self.ask(q)
        r = self.ask('아까 찾던 물건 다시 찾아줘')
        self.assertTrue(r['item_search_performed'])
        self.assertEqual(r['search_filter']['category'], '립밤')
        self.assertEqual(r['search_filter']['color'], '검정')

    def test_server_current_context_beats_stale_browser_history(self):
        self.ask('검정 립밤 찾아줘')
        r = self.ask('흰색으로 다시 찾아줘', history=[{'q': '파란 휴대폰 찾아줘', 'a': '인증 완료'}])
        self.assertEqual(r['search_filter']['category'], '립밤')
        self.assertEqual(r['search_filter']['color'], '흰색')
        with self.assertRaises(ValueError):
            self.ask('안녕', history=['질문']*5)

    def test_search_to_intake_keeps_item_but_never_identity_or_confirmation(self):
        self.ask('흰색 립밤 찾아줘')
        for q in ['안녕', '고마워요', '응', '알겠어', '다녀왔어']:
            self.ask(q)
        r = self.ask('분실 접수하기')
        self.assertEqual(r['intake']['asked'], 'station')
        slots = self.bot.intake.active('dialogue-owner')['slots']
        self.assertEqual(slots, {'category': '립밤', 'color': '흰색'})
        self.assertFalse(r.get('confirmation'))
        self.assertEqual(self.desk.calls, [])

    def test_sessions_and_channels_do_not_share_search_context(self):
        self.ask('검정 립밤 찾아줘')
        for kw in ({'sid': 'other-person'}, {'channel': 'kiosk'}, {'staff': True, 'channel': 'staff'}):
            with self.subTest(kw=kw):
                r = self.ask('흰색으로 다시 찾아줘', **kw)
                self.assertFalse(r.get('item_search_performed'))

    def test_channels_do_not_share_intake_or_confirmation(self):
        self.ask('분실 접수하기')
        self.ask('립밤')
        before = copy.deepcopy(self.bot.intake.active('dialogue-owner'))
        r = self.ask('안녕', channel='kiosk')
        self.assertFalse(r.get('intake'))
        self.assertEqual(before, self.bot.intake.active('dialogue-owner'))
        r = self.ask('습득 신고하기', channel='kiosk')
        self.assertEqual(r['intake']['asked'], 'category')
        self.assertEqual(self.bot.intake.active('dialogue-owner')['kind'], 'lost')
        self.assertEqual(self.bot.intake.active('kiosk:dialogue-owner')['kind'], 'found')
        self.assertFalse(r.get('confirmation'))

    def test_staff_analysis_followup_reuses_subject_but_public_chat_cannot(self):
        ops = Mock()
        ops.run.return_value = {'accepted': True, 'facts': {'returns': 1}, 'report': '반환 1건을 확인했어요.'}
        self.bot.ops = ops
        self.ask('오늘 반환 현황 분석해줘', staff=True, channel='staff')
        r = self.ask('그거 다시 설명해줘', staff=True, channel='staff')
        self.assertEqual(r['agent'], 'ops')
        self.assertIn('오늘 반환 현황', ops.run.call_args.args[0])
        self.ask('짧게 말해줘', staff=True, channel='staff')
        self.assertIn('오늘 반환 현황', ops.run.call_args.args[0])
        calls = ops.run.call_count
        self.assertNotEqual(self.ask('그거 다시 설명해줘')['agent'], 'ops')
        self.assertEqual(ops.run.call_count, calls)

    def test_ambiguous_multiple_topics_asks_which_without_search(self):
        self.ask('운영시간하고 택배 수령도 알려줘')
        r = self.ask('그거 다시 설명해줘')
        self.assertEqual(r['status'], 'clarification_needed')
        self.assertFalse(r['item_search_performed'])
        self.assertTrue(r['choices'])

    def test_current_field_is_explained_and_not_saved_as_a_feature(self):
        stages = [(['분실 접수하기'], 'category'), (['분실 접수하기', '립밤'], 'color'),
                  (['분실 접수하기', '립밤', '흰색', '초량', '오늘'], 'detail'),
                  (['분실 접수하기', '립밤', '흰색', '초량', '오늘', '없어요'], 'identity')]
        for setup, asked in stages:
            for follow in ('그거', '왜?', '무슨 뜻이야?', '그다음엔?', '다시 설명해줘'):
                sid = 'field-'+asked+str(len(follow))
                for q in setup:
                    self.ask(q, sid=sid)
                before = copy.deepcopy(self.bot.intake.active(sid))
                r = self.ask(follow, sid=sid)
                self.assertEqual(r['intake']['asked'], asked, (asked, follow, r['answer']))
                self.assertEqual(self.bot.intake.active(sid)['slots'], before['slots'])
                self.assertNotIn(follow, self.bot.intake.active(sid)['slots'].values())
        self.assertEqual(self.desk.calls, [])

    def test_jamo_and_ack_are_social_and_never_free_text_slots(self):
        for index, q in enumerate(('ㅎㅇ', 'ᄒᄋ', 'ㅇㅇ', 'ㅇㅋ', '네 알겠어', '아하', '응')):
            self.assertTrue(social_kind(q), q)
            sid = 'social-'+str(index)
            for setup in ('습득 신고하기', '흰색 보조배터리', '초량'):
                self.ask(setup, sid=sid)
            self.assertEqual(self.bot.intake.active(sid)['asked'], 'place')
            r = self.ask(q, sid=sid)
            self.assertEqual(r['intake']['asked'], 'place')
            self.assertNotIn('place', self.bot.intake.active(sid)['slots'])

    def test_history_never_caches_authentication_or_skips_confirmation(self):
        db = Mock(mode='postgres')
        self.bot.search = SearchAgent(db, authorize=lambda token: token == 'valid-synthetic')
        self.ask('검정 립밤 찾아줘', access_token='valid-synthetic')
        db.search.reset_mock()
        r = self.ask('흰색으로 다시 찾아줘')
        self.assertEqual(r['status'], 'authentication_required')
        db.search.assert_not_called()
        self.assertNotIn('valid-synthetic', repr(self.bot.dialogue._entries))

    def test_transient_error_does_not_erase_search_summary(self):
        self.ask('검정 립밤 찾아줘')
        with patch.object(self.bot.rag, 'ask', side_effect=RuntimeError('synthetic fault')):
            with self.assertRaises(RuntimeError):
                self.ask('택배 수령 가능해?')
        r = self.ask('아까 찾던 물건 다시 찾아줘')
        self.assertEqual(r['search_filter']['category'], '립밤')

    def test_model_workers_receive_same_live_summary(self):
        from agents.chat_agents import AgentBrain
        seen = []
        def request(payload):
            seen.append(json.loads(payload['messages'][1]['content']))
            return {'message': {'content': '{}'}}
        brain = AgentBrain('synthetic-model', request=request)
        active = {'kind': 'lost', 'stage': 'collect', 'asked': 'color', 'slots': {'category': '립밤', 'identity': ID}}
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LF_', 'LANGFUSE_'))}
        env['LF_LANGFUSE'] = '0'
        env.update({f'LF_AGENT_{worker.upper()}_USE_LLM': '1' for worker in ('coordinator', 'planner', 'supervisor', 'intake', 'reporter')})
        with patch.dict(os.environ, env, clear=True), DialogueMemory().turn('one') as frame, bound_dialogue(frame, lambda: active):
            for worker in ('coordinator', 'planner', 'supervisor', 'intake', 'reporter'):
                brain._ask('summary-test', worker, {'type': 'object'}, {'message': '질문'})
                active['asked'] = 'station'
        self.assertEqual(len(seen), 5)
        self.assertEqual(seen[0]['conversation_context']['current_task']['asked'], 'color')
        self.assertEqual(seen[-1]['conversation_context']['current_task']['asked'], 'station')
        self.assertNotIn('name_masked', json.dumps(seen))


class FixedDialogueJourneysTest(unittest.TestCase):
    def test_fixed_http_dialogue_journeys(self):
        from evaluation.dialogue_context_cases import cases
        from evaluation.dialogue_context_eval import run_case
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LF_', 'TOWER_', 'LANGFUSE_', 'DISCORD_')) and k != 'DATABASE_URL'}
        env.update(LF_LANGFUSE='0', LF_CHAT_RAG_MODEL='', LF_CHAT_AGENT_MODEL='', TOWER_SEND='0', TOWER_GPU_LEASE='0')
        with patch.dict(os.environ, env, clear=True), tempfile.TemporaryDirectory() as tmp:
            for case in cases():
                with self.subTest(journey=case['id'], group=case['group']):
                    result = run_case(case, tmp)
                    self.assertTrue(result['ok'], [(t['say'], t['why']) for t in result['turns'] if t['why']])


if __name__ == '__main__':
    unittest.main()
