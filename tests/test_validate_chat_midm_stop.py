from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.validate_chat_midm import main


class ModelValidationControlTest(unittest.TestCase):
    def test_preimported_agent_calls_are_included_in_actual_transport_counts(self):
        from agents import chat_agents, local_model
        from contextlib import redirect_stdout
        transport_calls = []
        def transport(payload, *args, **kwargs):
            transport_calls.append(payload)
            schema = payload.get('format') or {}
            value = schema['enum'][0] if isinstance(schema, dict) and schema.get('enum') else {}
            return {'message': {'content': json.dumps(value)}, 'eval_count': 1}
        with tempfile.TemporaryDirectory() as tmp:
            questions, out = Path(tmp) / 'questions.json', Path(tmp) / 'report.json'
            questions.write_text(json.dumps([{'q': '본센터 운영시간 알려줘', 'any': ['09:00']}]), encoding='utf-8')
            with mock.patch.object(local_model, 'ask_local_model', side_effect=transport), \
                 mock.patch.object(chat_agents, 'ask_local_model', side_effect=AssertionError('untracked transport')) as untracked, \
                 mock.patch('tools.chat_live_check.installed_models', return_value=[]), \
                 mock.patch('tools.chat_live_check.model_ready', return_value=None), \
                 mock.patch('tools.chat_live_check.model_probe', return_value=None), redirect_stdout(io.StringIO()):
                code = main(['--suite', 'live', '--questions', str(questions), '--out', str(out)])
            report = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(code, 0)
            untracked.assert_not_called()
            self.assertEqual(len(report['model_calls']), len(transport_calls))
            self.assertIn('planner', {row['role'] for row in report['model_calls']})
            self.assertIn('supervisor', {row['role'] for row in report['model_calls']})
            self.assertEqual(report['planner_checks'], {'accepted:structured_v2': 1})

    def test_stop_before_start_preserves_empty_partial_report_without_calling_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, stop = Path(tmp) / 'result.json', Path(tmp) / 'stop.flag'
            stop.touch()
            with mock.patch('tools.chat_live_check.installed_models') as models:
                code = main(['--suite', '500', '--out', str(out), '--stop-file', str(stop)])
                models.assert_not_called()
            report = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(code, 130)
            self.assertEqual(report['meta']['state'], 'stopped')
            self.assertEqual(report['summary']['total'], 0)

    def test_existing_model_report_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'original.json'
            out.write_text('{"original":true}', encoding='utf-8')
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['--suite', '500', '--out', str(out)])
            self.assertEqual(out.read_text(encoding='utf-8'), '{"original":true}')
