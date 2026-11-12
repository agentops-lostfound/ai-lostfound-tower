"""Planner 모델 출력이 실행 권한·임의 입력·저장 명령으로 변하지 않는지 검증."""
import contextlib
import json
import unittest
from unittest import mock

from agents.chat_agents import AgentBrain
from agents.chat_planner import (
    WorkInstruction, allowed_instructions, allowed_plans, instruction_for, output_schema, parse_proposal, safe_proposal,
)


def proposal(*workers, scoped=False):
    return {'version': 2, 'steps': [instruction_for(worker, scoped).public_contract() for worker in workers]}


class PlannerContractTest(unittest.TestCase):
    def brain(self, value):
        brain = AgentBrain('synthetic-model')
        brain._ask = mock.Mock(return_value=value)
        return brain

    def test_schema_binds_worker_task_and_input_reference_together(self):
        schema = output_schema()
        allowed = schema['properties']['steps']['items']['enum']
        self.assertEqual(allowed, allowed_instructions())
        self.assertEqual(schema['enum'], allowed_plans())
        self.assertEqual(len(schema['enum']), 3)
        self.assertNotIn(proposal('guidance', 'guidance'), schema['enum'])
        self.assertTrue(all(len(parse_proposal(plan)[1]) == len({step['worker'] for step in plan['steps']})
                            for plan in schema['enum']))
        self.assertNotIn({'worker': 'guidance', 'task': 'search_candidates', 'input_ref': 'search_part'}, allowed)
        allowed[0]['worker'] = 'intake'
        self.assertNotIn('intake', [step['worker'] for step in allowed_instructions()])

    def test_structured_instructions_reach_decision_and_required_workers_remain(self):
        brain = self.brain(proposal('guidance'))
        decision = brain.plan_contract('파란 휴대폰 찾아줘 그리고 본센터 가는 법 알려줘', [], ['item_search'])
        self.assertEqual(decision.workers, ('item_search', 'guidance'))
        self.assertEqual(decision.audit['required_added'], ['item_search'])
        self.assertEqual(decision.audit['input_refined'], ['guidance'])
        self.assertEqual(decision.instructions[1].input_ref, 'guidance_part')
        self.assertEqual(decision.audit['reason'], 'structured_v2')
        request = brain._ask.call_args.args[3]
        self.assertEqual(request['required_workers'], ['item_search'])
        self.assertEqual(request['allowed_instructions'], allowed_instructions())

    def test_unknown_fields_free_text_and_cross_worker_instructions_are_rejected(self):
        valid = proposal('guidance')
        bad = [None, [], {'version': True, 'steps': valid['steps']}, {**valid, 'save': True},
               {'version': 2, 'steps': []}, {'version': 2, 'steps': valid['steps'] * 3},
               proposal('guidance', 'guidance'), {'steps': ['intake']},
               {'steps': ['guidance'], 'sql': 'private-model-output'},
               {'version': 2, 'steps': [{'worker': 'item_search', 'task': 'answer_guidance', 'input_ref': 'question'}]},
               {'version': 2, 'steps': [{'worker': 'guidance', 'task': 'answer_guidance', 'input_ref': 'search_part'}]},
               {'version': 2, 'steps': [{**valid['steps'][0], 'input': 'private-model-output'}]}]
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_proposal(value)
                decision = self.brain(value).plan_contract('운영시간 알려줘')
                self.assertEqual(decision.instructions, ())
                self.assertEqual(decision.audit['validation'], 'rejected')
                self.assertNotIn('private-model-output', json.dumps(safe_proposal(value)))

    def test_old_worker_only_response_has_explicit_bounded_adapter(self):
        decision = self.brain({'steps': ['guidance']}).plan_contract('운영시간 알려줘')
        self.assertEqual(decision.workers, ('guidance',))
        self.assertEqual(decision.audit['reason'], 'bounded_legacy_v1')
        self.assertEqual(decision.instructions[0], instruction_for('guidance'))

    def test_found_side_search_addition_is_removed_but_required_search_is_preserved(self):
        brain = self.brain(proposal('item_search', 'guidance', scoped=True))
        decision = brain.plan_contract('휴대폰은 상자에 어떻게 놓아요?', [], ['guidance'])
        self.assertEqual(decision.workers, ('guidance',))
        self.assertEqual(decision.audit['removed'], ['item_search'])
        self.assertEqual(decision.instructions[0].input_ref, 'question')
        self.assertIn('item_search', brain.plan('휴대폰 넣은 가방 잃어버림', [], ['item_search']))

    def test_model_trace_cannot_keep_rejected_arbitrary_instruction(self):
        value = {'steps': ['guidance'], 'sql': 'private-model-output'}
        brain = AgentBrain('synthetic-model', request=lambda _: {'message': {'content': json.dumps(value)}})
        trace = mock.Mock()
        with mock.patch('agents.chat_agents.step', return_value=contextlib.nullcontext(trace)), \
             mock.patch('agents.prompts.resolve', return_value=('planner', None,
                        {'model': 'synthetic-model', 'temperature': 0, 'use_llm': True})), \
             mock.patch('agents.prompts.record_usage', return_value={}):
            decision = brain.plan_contract('운영시간 알려줘')
        self.assertEqual(decision.instructions, ())
        self.assertNotIn('private-model-output', repr(trace.update.call_args_list))


class PlannerGraphContractTest(unittest.TestCase):
    def test_required_search_addition_preserves_guidance_for_original_compound_cases(self):
        from agents.chat_api import build_chatbot_from_env
        from evaluation.chat_eval import QUESTIONS, Runner
        from tools.validate_chat_datasets import isolated_env
        items = json.loads(QUESTIONS.read_text(encoding='utf-8'))
        def factory(*args, **kwargs):
            chatbot = build_chatbot_from_env(*args, **kwargs)
            brain = AgentBrain('synthetic-model')
            brain._ask = mock.Mock(return_value=proposal('guidance'))
            chatbot.brain = brain
            return chatbot
        with mock.patch.dict('os.environ', isolated_env(), clear=True), \
             mock.patch('agents.chat_api.build_chatbot_from_env', factory):
            runner = Runner()
            for number in (222, 226):
                result = runner.run_item(next(item for item in items if item['no'] == number))
                self.assertEqual(result['score'], 1, result['why'])

    def test_removed_search_restores_whole_guidance_question_for_original_cases(self):
        from agents.chat_api import build_chatbot_from_env
        from evaluation.chat_eval import QUESTIONS, Runner
        from tools.validate_chat_datasets import isolated_env
        items = json.loads(QUESTIONS.read_text(encoding='utf-8'))
        def factory(*args, **kwargs):
            chatbot = build_chatbot_from_env(*args, **kwargs)
            brain = AgentBrain('synthetic-model')
            brain._ask = mock.Mock(return_value=proposal('item_search', 'guidance', scoped=True))
            chatbot.brain = brain
            return chatbot
        with mock.patch.dict('os.environ', isolated_env(), clear=True), \
             mock.patch('agents.chat_api.build_chatbot_from_env', factory):
            runner = Runner()
            for number in (107, 114, 277, 283, 468):
                result = runner.run_item(next(item for item in items if item['no'] == number))
                self.assertEqual(result['score'], 1, result['why'])

    def test_scoped_reference_is_resolved_by_code_and_sent_to_actual_worker(self):
        from test_deerflow_langfuse import bot
        brain = AgentBrain('synthetic-model')
        brain._ask = mock.Mock(return_value=proposal('item_search', 'guidance', scoped=True))
        chatbot = bot(brain)
        seen = []
        original = chatbot.search.ask
        def search(question, *args, **kwargs):
            seen.append(question)
            return original(question, *args, **kwargs)
        with mock.patch.object(chatbot.search, 'ask', side_effect=search):
            result = chatbot.ask('흰색 보조배터리 찾아줘 그리고 본센터 수령 절차 알려줘')
        self.assertTrue(seen)
        self.assertNotIn('수령 절차', seen[0])
        self.assertIn('보조배터리', seen[0])
        self.assertIn('item_search', result['agent_path'])
        self.assertIn('researcher', result['agent_path'])
        self.assertNotIn('input_ref', json.dumps(result))

    def test_step_boundary_revalidates_injected_instruction(self):
        from test_deerflow_langfuse import bot
        chatbot = bot()
        step = chatbot._step(1, 'guidance', {'question': '운영시간 알려줘'}, 'planner',
            instruction=WorkInstruction('guidance', 'execute_sql', 'private-model-output'))
        self.assertEqual(step['instruction'], instruction_for('guidance').public_contract())
        self.assertNotIn('private-model-output', json.dumps(step))
