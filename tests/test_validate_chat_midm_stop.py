from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.validate_chat_midm import main


class ModelValidationControlTest(unittest.TestCase):
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
