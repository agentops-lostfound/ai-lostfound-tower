"""Real subprocess protocol test with a lightweight fake vision implementation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tools.vision_cpu_client import ResidentDetector


class ResidentDetectorTests(unittest.TestCase):
    def test_reuses_detector_propagates_error_and_shuts_down(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'vision').mkdir()
            (root / 'vision/__init__.py').write_text('')
            (root / 'vision/vision_pipeline.py').write_text('''
import json
from pathlib import Path
created = 0
class YoloDetector:
    def __init__(self, *args):
        global created
        created += 1
def run_image(image, config, device):
    if image.endswith('fail.jpg'):
        raise ValueError('test error')
    YoloDetector('weights.pt', device, 0.1, 640)
    p = Path('result.json')
    report = {'objects': [], 'created': created}
    p.write_text(json.dumps(report))
    return report, p.resolve()
''', encoding='utf-8')
            detector = ResidentDetector(root, Path(sys.executable), timeout=10)
            try:
                a, _ = detector.detect(root / 'a.jpg', None)
                b, _ = detector.detect(root / 'b.jpg', None)
                self.assertEqual(a['created'], 1)
                self.assertEqual(b['created'], 1)
                with self.assertRaisesRegex(RuntimeError, 'test error'):
                    detector.detect(root / 'fail.jpg', None)
            finally:
                detector.close()
            self.assertIsNotNone(detector.process.poll())
