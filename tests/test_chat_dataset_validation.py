import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.validate_chat_datasets import audit_file, isolated_env, check_guidance, guidance_result, run_rules, main


class DatasetValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, obj):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
        return path

    def test_historical_summary_mismatch_is_reported_without_modifying_original(self):
        path = self.write('old-run.json', {'results': [{'no': 1, 'score': 0}], 'summary': {'total': 1, 'passed': 1}})
        before = path.read_bytes()
        result = audit_file(path, self.root)
        self.assertIn('summary_passed_mismatch', result['errors'])
        self.assertEqual(path.read_bytes(), before)

    def test_malformed_500_numbers_do_not_crash_or_claim_full_coverage(self):
        cases = [{'no': {'invalid': True}, 'turns': [{'say': 'synthetic'}]} for _ in range(500)]
        result = audit_file(self.write('chat_eval_500.json', cases), self.root)
        self.assertIn('invalid_500_case_coverage', result['errors'])

    def test_csv_audit_does_not_echo_row_contents(self):
        path = self.root / 'records.csv'
        path.write_text('a,a\nprivate-row-value,value\n', encoding='utf-8')
        result = audit_file(path, self.root)
        self.assertEqual(result['records'], 1)
        self.assertIn('duplicate_csv_header', result['errors'])
        self.assertNotIn('private-row-value', str(result))

    def test_existing_output_is_never_overwritten(self):
        path = self.write('existing.json', {'original': True})
        before = path.read_bytes()
        with self.assertRaises(SystemExit) as caught:
            main(['--mode', 'audit', '--out', str(path)])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(path.read_bytes(), before)

    def test_stop_file_prevents_next_case_and_preserves_partial_state(self):
        self.write('evaluation/chat_eval_500.json', [{'no': 1, 'turns': [{'say': 'synthetic'}]}])
        stop = self.root / 'stop.flag'
        stop.touch()
        report = {'meta': {'state': 'running'}, 'suites': []}
        out = self.root / 'partial.json'
        with mock.patch('evaluation.chat_eval.Runner') as runner:
            self.assertFalse(run_rules(self.root, report, out, stop))
            runner.return_value.run_item.assert_not_called()
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['meta']['state'], 'stopped')

    def test_external_credentials_and_models_are_not_inherited(self):
        with mock.patch.dict('os.environ', {'LANGFUSE_SECRET_KEY': 'synthetic-secret', 'DATABASE_URL': 'synthetic-db',
                                          'LF_CHAT_RAG_MODEL': 'unexpected-model'}):
            env = isolated_env()
        for name in ('LANGFUSE_SECRET_KEY', 'DATABASE_URL', 'LF_CHAT_RAG_MODEL'):
            self.assertNotIn(name, env)
        self.assertEqual(env['LF_LANGFUSE'], '0')

    def test_guidance_uses_original_status_and_topic_expectations(self):
        expected = {'expected_status': 'answered', 'expected_topics': ['pickup']}
        self.assertEqual(check_guidance(expected, {'status': 'answered', 'sources': [{'topic': 'pickup'}]}), [])
        reasons = check_guidance(expected, {'status': 'policy_pending', 'sources': []})
        self.assertEqual(set(reasons), {'expected_status_mismatch', 'expected_topics_missing'})

    def test_expected_input_rejection_is_a_result_and_does_not_abort_the_suite(self):
        guide = mock.Mock()
        guide.ask.side_effect = ValueError('synthetic-private-input')
        result = guidance_result(guide, 'synthetic question')
        self.assertEqual(check_guidance({'expected_status': 'rejected', 'expected_topics': []}, result), [])
        self.assertNotIn('synthetic-private-input', str(result))

    def test_unexpected_runtime_error_does_not_masquerade_as_input_rejection(self):
        guide = mock.Mock()
        guide.ask.side_effect = RuntimeError('synthetic-private-error')
        result = guidance_result(guide, 'synthetic question')
        self.assertEqual(result['status'], 'error')
        self.assertNotEqual(result['status'], 'rejected')
        self.assertNotIn('synthetic-private-error', str(result))

    def test_partial_historical_report_is_distinguished_from_a_complete_run(self):
        result = audit_file(self.write('partial.json', {'meta': {'state': 'running'}, 'results': []}), self.root)
        self.assertEqual(result['completion_state'], 'running')
        self.assertEqual(result['warnings'], ['partial_run'])
