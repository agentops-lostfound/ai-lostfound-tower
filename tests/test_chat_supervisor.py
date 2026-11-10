"""감독의 악성·장애 출력이 실제 업무 권한으로 바뀌지 않는지 검증."""
import json
import contextlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_color_multiturn import setUpModule, tearDownModule  # noqa: F401
from test_deerflow_langfuse import bot
from agents.chat_supervisor import candidates, decide, proposal, validate


def stage(agent='researcher', no=1, **kw):
    return {'no': no, 'agent': agent, 'status': 'todo', 'by': 'planner', **kw}


class SupervisorGuardTest(unittest.TestCase):
    def test_five_actions_only_and_strict_json_types(self):
        allowed = [proposal('run_step', 1, 'researcher')]
        for bad in (None, [], {}, {'action': 'save', 'step': 1, 'agent': 'intake'},
                    {**allowed[0], 'sql': 'DROP TABLE item'},
                    {**allowed[0], 'step': True}, {**allowed[0], 'step': 1.0},
                    {**allowed[0], 'step': '1'}):
            self.assertFalse(validate(bad, allowed)[0], bad)

    def test_intake_and_staff_require_server_permission(self):
        self.assertEqual(candidates([stage('intake')]), [proposal('ask_user')])
        self.assertEqual(candidates([stage('ops_analyst')]), [proposal('finish')])
        self.assertEqual(candidates([stage('intake')], intake_allowed=True), [proposal('run_step', 1, 'intake')])
        self.assertEqual(candidates([stage('ops_analyst')], ops_allowed=True), [proposal('run_step', 1, 'ops_analyst')])

    def test_no_early_finish_or_repeat_completed_work(self):
        pending = stage()
        allowed = candidates([pending, stage('item_search', 2, status='done')])
        self.assertFalse(validate(proposal('finish'), allowed)[0])
        self.assertFalse(validate(proposal('run_step', 2, 'item_search'), allowed)[0])

    def test_actual_execution_limit_even_with_one_result_type(self):
        self.assertEqual(candidates([stage()], executions=6), [proposal('finish')])

    def test_wait_and_report_are_terminal(self):
        self.assertEqual(candidates([stage()], stop=True), [proposal('ask_user')])
        self.assertEqual(candidates([stage()], reported=True), [proposal('finish')])

    def test_add_and_replan_only_server_approved_tasks(self):
        self.assertEqual(candidates([stage(by='supervisor', note='add_guidance')]),
                         [proposal('add_step', 1, 'researcher')])
        allowed = candidates([stage('item_search', by='supervisor', note='replan_item_search')])
        self.assertEqual(allowed, [proposal('replan', 1, 'item_search')])
        self.assertFalse(validate(proposal('replan', 2, 'intake'), allowed)[0])

    def test_rejection_does_not_store_arbitrary_model_text(self):
        class Brain:
            def supervise(self, *_):
                return {'action': '홍길동 010-1234-5678', 'step': 999999, 'agent': 'secret'}
        chosen, audit = decide(Brain(), [proposal('ask_user')], {})
        self.assertEqual(chosen, proposal('ask_user'))
        self.assertEqual(audit['validation'], 'rejected')
        self.assertNotIn('010-', json.dumps(audit))
        self.assertNotIn('secret', json.dumps(audit))

    def test_model_exception_uses_code_fallback(self):
        class Brain:
            def supervise(self, *_):
                raise TimeoutError('private')
        _, audit = decide(Brain(), [proposal('finish')], {})
        self.assertEqual(audit['reason'], 'model_error')

    def test_generation_trace_also_discards_arbitrary_model_fields(self):
        from agents.chat_agents import AgentBrain
        events = []
        class Observation:
            def update(self, **kw):
                events.append(kw)
        @contextlib.contextmanager
        def trace(*a, **kw):
            yield Observation()
        raw = {'action': 'run_step', 'step': 1, 'agent': 'intake', 'private': 'sensitive-name'}
        with mock.patch.dict(os.environ, {'LF_LANGFUSE': '0', 'LF_AGENT_SUPERVISOR_USE_LLM': '1'}), \
             mock.patch('agents.chat_agents.step', trace):
            b = AgentBrain('test', request=lambda p: {'message': {'content': json.dumps(raw)}})
            b.supervise([proposal('finish')], {})
        self.assertNotIn('sensitive-name', json.dumps(events))
        self.assertNotIn('private', json.dumps(events))


class SupervisorIntegrationTest(unittest.TestCase):
    def test_model_can_reorder_read_tasks_but_cannot_skip_them(self):
        from agents.chat_agents import AgentBrain
        calls = []
        def request(payload):
            system = payload['messages'][0]['content']
            if 'supervisor' not in system[:80]:
                raise OSError('no model')
            data = json.loads(payload['messages'][1]['content'])
            calls.append(data)
            allowed = data['allowed']
            chosen = next((a for a in allowed if a['agent'] == 'researcher'), allowed[0])
            return {'message': {'content': json.dumps(chosen)}}
        with mock.patch.dict(os.environ, {'LF_LANGFUSE': '0', 'LF_AGENT_SUPERVISOR_USE_LLM': '1'}):
            r = bot(AgentBrain('test', request=request)).ask('검정 지갑 찾고 본센터 가는 법도 알려줘')
        self.assertLess(r['agent_path'].index('researcher'), r['agent_path'].index('item_search'))
        self.assertEqual(r['worker_executions'], 2)
        self.assertTrue(all(x['validation'] == 'accepted' for x in r['supervisor_checks']))
        self.assertEqual(r['supervisor_checks'][-1]['executed']['action'], 'finish')
        self.assertTrue(calls)

    def test_malicious_model_cannot_execute_storage_or_ops(self):
        from agents.chat_agents import AgentBrain
        def request(payload):
            return {'message': {'content': json.dumps(proposal('run_step', 1, 'intake'))}}
        with mock.patch.dict(os.environ, {'LF_LANGFUSE': '0', 'LF_AGENT_SUPERVISOR_USE_LLM': '1'}):
            r = bot(AgentBrain('test', request=request)).ask('운영시간 알려줘')
        self.assertNotIn('intake', r['agent_path'])
        self.assertNotIn('ops_analyst', r['agent_path'])
        self.assertTrue(all(x['validation'] == 'rejected' for x in r['supervisor_checks']))

    def test_graph_caps_actual_execution_without_counting_result_keys(self):
        b = bot()
        state = {'question': '운영시간 알려줘', 'plan': ['guidance'], 'steps': [
            stage(plan_name='guidance', task='안내')], 'results': {}, 'worker_executions': 6}
        r = b._supervisor(state)
        self.assertEqual(r['next'], 'reporter')
        self.assertEqual(r['worker_executions'], 6)
        self.assertEqual(r['steps'][0]['status'], 'skipped')


if __name__ == '__main__':
    unittest.main()
