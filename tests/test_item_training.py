import tempfile
import unittest
from pathlib import Path
try:
    from vision.scripts.train_item import training_plan, main
except ImportError as error:
    raise unittest.SkipTest(f"Install vision/requirements_inference.txt: {error}") from error


class ItemTrainingTests(unittest.TestCase):
    def test_path_resolution_and_separate_taxonomy(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data.yaml"
            data.write_text("path: dataset\ntrain: images/train\nval: images/val\nnames: {0: item}\n")
            config, output = training_plan(data, "item_baseline")
            self.assertEqual(Path(config["path"]), Path(tmp) / "dataset")
            self.assertEqual(config["names"], {0:"item"})
            self.assertEqual(output.name, "item_baseline")
            for name in ("..", "../outside"):
                with self.assertRaises(ValueError):
                    training_plan(data, name)
            data.write_text("path: dataset\nnames: {0: wallet, 1: usb}\n")
            with self.assertRaises(ValueError):
                training_plan(data, "item_baseline")

    def test_missing_training_data_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data.yaml"
            data.write_text("path: missing\ntrain: images/train\nval: images/val\nnames: {0: item}\n")
            with self.assertRaises(SystemExit) as error:
                main(["--data",str(data),"--name","item_missing_data_test"])
            self.assertEqual(error.exception.code, 1)
