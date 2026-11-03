import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

try:
    from vision.sequence import run_sequence
except ImportError as error:
    raise unittest.SkipTest(f"Install vision/requirements_inference.txt: {error}") from error


class SequenceTests(unittest.TestCase):
    def fixture(self, root, objects):
        (root / "src").mkdir()
        (root / "src/feature_extractor.py").write_text("")
        output = root / "result.json"
        report = {"objects": objects, "markers": [], "calibration": {"valid": False}}
        return report, output

    def test_no_detections_does_not_launch_qwen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report, output = self.fixture(root, [])
            with mock.patch("vision.sequence.run_image", return_value=(report, output)), \
                 mock.patch("vision.sequence._run_qwen") as launch:
                merged, target = run_sequence("unused.jpg", root, sys.executable)
            launch.assert_not_called()
            self.assertEqual(merged["sequence"]["status"], "no_detections")
            self.assertTrue(target.is_file())

    def test_worker_startup_failure_retains_detection_and_null_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = {"id": 0, "center_px": [10,20], "crop_path": "crop.jpg"}
            report, output = self.fixture(root, [obj])
            with mock.patch("vision.sequence.run_image", return_value=(report, output)), \
                 mock.patch("vision.sequence._run_qwen", return_value=mock.Mock(returncode=1)):
                merged, target = run_sequence("unused.jpg", root, sys.executable)
            self.assertEqual(merged["sequence"]["status"], "failed")
            self.assertEqual(merged["objects"][0]["center_px"], [10,20])
            self.assertIsNone(merged["objects"][0]["qwen"]["features"])
            self.assertEqual(json.loads(target.read_text())["sequence"]["qwen_failed"], 1)

    def test_success_keeps_features_attached_to_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report, output = self.fixture(root, [{"id": 3, "crop_path": "crop3.jpg"}])
            def child(command, **kwargs):
                target = Path(command[command.index("--report")+1])
                data = json.loads(target.read_text())
                data["objects"][0]["qwen"] = {"status": "ok", "features": {"colors": ["black"]}}
                target.write_text(json.dumps(data))
                return mock.Mock(returncode=0)
            with mock.patch("vision.sequence.run_image", return_value=(report, output)), \
                 mock.patch("vision.sequence._run_qwen", side_effect=child):
                merged, _ = run_sequence("unused.jpg", root, sys.executable)
            self.assertEqual(merged["sequence"]["status"], "complete")
            self.assertEqual(merged["objects"][0]["id"], 3)
            self.assertEqual(merged["objects"][0]["qwen"]["features"]["colors"], ["black"])

    def test_cancel_saves_partial_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report, output = self.fixture(root, [{"id": 0, "crop_path": "crop.jpg"}])
            with mock.patch("vision.sequence.run_image", return_value=(report, output)), \
                 mock.patch("vision.sequence._run_qwen", side_effect=KeyboardInterrupt):
                merged, target = run_sequence("unused.jpg", root, sys.executable)
            self.assertEqual(merged["sequence"]["status"], "cancelled")
            self.assertEqual(merged["objects"][0]["qwen"]["status"], "cancelled")
            self.assertTrue(target.is_file())

    def test_wait_interrupt_terminates_child(self):
        from vision.sequence import _run_qwen
        process = mock.Mock()
        process.wait.side_effect = [KeyboardInterrupt, 1]
        process.poll.return_value = None
        with mock.patch("vision.sequence.subprocess.Popen") as launch:
            launch.return_value.__enter__.return_value = process
            with self.assertRaises(KeyboardInterrupt):
                _run_qwen(["python"], report_path="unused.json")
        process.terminate.assert_called_once()
