"""라벨 격리·원자적 본문/config 선택·실제 사용 이력의 독립 검증."""
import concurrent.futures
import json
import os
import unittest
from unittest import mock

from agents import observability, prompts
from agents.chat_agents import AgentBrain


class Prompt:
    is_fallback = False

    def __init__(self, text, version, config=None):
        self.prompt, self.version, self.config = text, version, config or {}

    def compile(self, **kw):
        return prompts._compile(self.prompt, kw)


class Client:
    def __init__(self):
        self.calls = []

    def get_prompt(self, name, **kw):
        self.calls.append((name, kw['label']))
        version = 7 if kw['label'] == 'staging' else 3
        return Prompt(f'{kw["label"]}-{version}', version, {'model': f'model-{version}', 'temperature': .2})


class StagingTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'LF_LANGFUSE': '0', 'LF_PROMPT_LABEL': 'production'})
        self.env.start()
        prompts._CACHE.clear()
        prompts._SEEN.clear()
        prompts._READ_CACHE.clear()

    def tearDown(self):
        self.env.stop()
        prompts._CACHE.clear()
        prompts._SEEN.clear()
        prompts._READ_CACHE.clear()
        observability.reset_for_tests()

    def test_label_caches_and_status_do_not_mix(self):
        c = Client()
        with mock.patch.object(observability, 'client', return_value=c):
            a = prompts.resolve('planner', model='base', temperature=0)
            with mock.patch.dict(os.environ, {'LF_PROMPT_LABEL': 'staging'}):
                b = prompts.resolve('planner', model='base', temperature=0)
                self.assertEqual(prompts.status()['label'], 'staging')
            a2 = prompts.resolve('planner', model='base', temperature=0)
        self.assertEqual((a[0], b[0], a2[0]), ('production-3', 'staging-7', 'production-3'))
        self.assertEqual(c.calls, [('chat-planner', 'production'), ('chat-planner', 'staging')])
        self.assertEqual((a[2]['model'], b[2]['model']), ('model-3', 'model-7'))

    def test_unknown_label_fails_before_network(self):
        c = Client()
        with mock.patch.dict(os.environ, {'LF_PROMPT_LABEL': 'stagign'}), \
             mock.patch.object(observability, 'client', return_value=c):
            with self.assertRaises(ValueError):
                prompts.resolve('planner')
        self.assertEqual(c.calls, [])

    def test_missing_staging_never_tries_production(self):
        c = Client()
        def missing(name, **kw):
            c.calls.append((name, kw['label']))
            raise OSError('private internal address')
        with mock.patch.dict(os.environ, {'LF_PROMPT_LABEL': 'staging'}), \
             mock.patch.object(observability, 'client', return_value=c), mock.patch.object(c, 'get_prompt', missing), \
             prompts.usage_scope():
            text, obj, cfg = prompts.resolve('planner', model='base', temperature=0)
            prompts.record_usage('planner', cfg, obj)
            receipts = prompts.loaded_versions()
        self.assertEqual(c.calls, [('chat-planner', 'staging')])
        self.assertEqual(text, prompts.DEFAULTS['chat-planner'])
        self.assertEqual((cfg['prompt_source'], cfg['label'], cfg['prompt_version']), ('code', 'staging', None))
        self.assertNotIn('private', json.dumps(receipts))

    def test_one_fetch_snapshot_keeps_text_model_version_together(self):
        c = Client()
        def changing(name, **kw):
            c.calls.append((name, kw['label']))
            n = len(c.calls)
            return Prompt(f'prompt-{n}', n, {'model': f'model-{n}', 'use_llm': True})
        payloads = []
        with mock.patch.object(observability, 'client', return_value=c), mock.patch.object(c, 'get_prompt', changing), \
             mock.patch.object(prompts, '_CACHE_TTL', -1), prompts.usage_scope():
            brain = AgentBrain('base', request=lambda p: payloads.append(p) or {'message': {'content': '{"steps":["guidance"]}'}})
            self.assertEqual(brain.plan('사용법 알려줘'), ['guidance'])
            receipt = prompts.loaded_versions()[0]
        self.assertEqual(len(c.calls), 1)
        self.assertEqual((payloads[0]['model'], payloads[0]['messages'][0]['content'], receipt['version']),
                         ('model-1', 'prompt-1', 1))

    def test_bad_compilation_drops_remote_config_as_well(self):
        c = Client()
        with mock.patch.object(observability, 'client', return_value=c), \
             mock.patch.object(c, 'get_prompt', return_value=Prompt('{{missing}}', 99, {'model': 'bad-model'})):
            text, obj, cfg = prompts.resolve('planner', model='base', temperature=0)
        self.assertIsNone(obj)
        self.assertEqual(cfg['model'], 'base')
        self.assertEqual(cfg['fallback_reason'], 'compile_failed')
        self.assertEqual(text, prompts.DEFAULTS['chat-planner'])

    def test_only_actual_attempts_are_counted_and_scopes_are_isolated(self):
        with prompts.usage_scope():
            text, obj, cfg = prompts.resolve('planner', model='base', temperature=0)
            self.assertEqual(prompts.loaded_versions(), [])
            prompts.record_usage('planner', cfg, obj)
            prompts.record_usage('planner', cfg, obj)
            self.assertEqual(prompts.loaded_versions()[0]['calls'], 2)
            with prompts.usage_scope():
                self.assertEqual(prompts.loaded_versions(), [])
            self.assertEqual(prompts.loaded_versions()[0]['calls'], 2)
        with prompts.usage_scope():
            self.assertEqual(prompts.loaded_versions(), [])

    def test_usage_metadata_has_no_conversation_or_arbitrary_config(self):
        c = Client()
        private = {'model': 'base', 'temperature': .3, 'secret': 'sensitive-value', 'question': 'private-name'}
        with mock.patch.object(observability, 'client', return_value=c), \
             mock.patch.object(c, 'get_prompt', return_value=Prompt('safe-template', 8, private)), prompts.usage_scope():
            _, obj, cfg = prompts.resolve('planner')
            prompts.record_usage('planner', cfg, obj)
            text = json.dumps(prompts.loaded_versions())
        for forbidden in ('sensitive-value', 'private-name', 'secret', 'question'):
            self.assertNotIn(forbidden, text)

    def test_independent_threads_do_not_share_eval_usage(self):
        def run(agent):
            with prompts.usage_scope():
                _, obj, cfg = prompts.resolve(agent, model='base', temperature=0)
                prompts.record_usage(agent, cfg, obj)
                return prompts.loaded_versions()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            a, b = list(pool.map(run, ['planner', 'supervisor']))
        self.assertEqual([r['agent'] for r in a], ['planner'])
        self.assertEqual([r['agent'] for r in b], ['supervisor'])

    def test_http_worker_usage_returns_to_eval_scope(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        @app.get('/test-usage')
        def route():
            _, obj, cfg = prompts.resolve('planner', model='base', temperature=0)
            prompts.record_usage('planner', cfg, obj)
            return {'ok': True}
        with prompts.usage_scope(), TestClient(app) as client:
            self.assertEqual(client.get('/test-usage').status_code, 200)
            self.assertEqual(prompts.loaded_versions()[0]['calls'], 1)

    def test_staging_receipts_not_scores_control_provenance_completeness(self):
        c = Client()
        with mock.patch.dict(os.environ, {'LF_PROMPT_LABEL': 'staging'}), prompts.usage_scope():
            _, obj, cfg = prompts.resolve('planner', model='base', temperature=0)
            prompts.record_usage('planner', cfg, obj)
            self.assertFalse(prompts.usage_summary()['staging_provenance_complete'])
        with mock.patch.dict(os.environ, {'LF_PROMPT_LABEL': 'staging'}), \
             mock.patch.object(observability, 'client', return_value=c), prompts.usage_scope():
            _, obj, cfg = prompts.resolve('planner', model='base', temperature=0)
            row = prompts.record_usage('planner', cfg, obj)
            row['setting_sources']['model'] = 'mutated'
            self.assertTrue(prompts.usage_summary()['staging_provenance_complete'])
            self.assertEqual(prompts.loaded_versions()[0]['setting_sources']['model'], 'langfuse')
            newer = Prompt('new-version', 9, {'model': 'model-9'})
            with mock.patch.object(c, 'get_prompt', return_value=newer), mock.patch.object(prompts, '_CACHE_TTL', -1):
                _, obj, cfg = prompts.resolve('planner', model='base', temperature=0)
                prompts.record_usage('planner', cfg, obj)
            self.assertFalse(prompts.usage_summary()['staging_provenance_complete'])
            self.assertEqual(prompts.usage_summary()['mixed_agents'], ['planner'])

    def test_ops_actual_calls_recorded_but_rule_hooks_are_not(self):
        from agents.ops_analyst import OpsAnalyst
        class Reader:
            def collect(self):
                return {'returns': [], 'live': {'stories': [], 'events': []}, 'chat': None}
        with prompts.usage_scope():
            OpsAnalyst(reader=Reader(), llm=lambda p: {'message': {'content': '{}'}}, model='base').run('오늘 반환 실패 원인')
            self.assertEqual({r['agent'] for r in prompts.loaded_versions()}, {'ops-planner', 'ops-reporter'})

    def test_eval_does_not_copy_arbitrary_model_named_secrets(self):
        from evaluation.chat_eval import model_info
        with prompts.usage_scope(), mock.patch.dict(os.environ, {'LF_CHAT_RAG_MODEL': 'base',
                                                                'LF_CHAT_MODEL_SECRET': 'do-not-record'}):
            out = model_info(False)
        self.assertEqual(out['LF_CHAT_RAG_MODEL'], 'base')
        self.assertNotIn('do-not-record', json.dumps(out))

    def test_read_only_client_explicitly_disables_tracing(self):
        c = Client()
        env = {'LF_PROMPT_FETCH': '1', 'LANGFUSE_PUBLIC_KEY': 'fake-public',
               'LANGFUSE_SECRET_KEY': 'fake-private', 'LANGFUSE_BASE_URL': 'http://127.0.0.1:1'}
        with mock.patch.dict(os.environ, env), mock.patch.object(observability, 'client', return_value=None), \
             mock.patch('langfuse.Langfuse', return_value=c) as factory:
            prompts.resolve('planner', model='base', temperature=0)
            prompts.resolve('supervisor', model='base', temperature=0)
        factory.assert_called_once_with(tracing_enabled=False)
        self.assertEqual(len(c.calls), 2)

    def test_read_only_client_does_not_retry_with_tracing_enabled(self):
        env = {'LF_PROMPT_FETCH': '1', 'LANGFUSE_PUBLIC_KEY': 'fake-public',
               'LANGFUSE_SECRET_KEY': 'fake-private', 'LANGFUSE_BASE_URL': 'http://127.0.0.1:1'}
        with mock.patch.dict(os.environ, env), mock.patch.object(observability, 'client', return_value=None), \
             mock.patch('langfuse.Langfuse', side_effect=TypeError('unsupported')) as factory:
            _, obj, cfg = prompts.resolve('planner', model='base', temperature=0)
        factory.assert_called_once_with(tracing_enabled=False)
        self.assertIsNone(obj)
        self.assertEqual(cfg['prompt_source'], 'code')


if __name__ == '__main__':
    unittest.main()
