import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from aruco.detector import detect_markers
from aruco.calibration import calibrate, transform_center
from yolo.cropper import save_crop
from vision_pipeline import run_image


class VisionTests(unittest.TestCase):
    def test_synthetic_marker_and_transform(self):
        image = np.full((400, 400, 3), 255, np.uint8)
        marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), 7, 200)
        image[100:300, 100:300] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        markers = detect_markers(image)
        self.assertEqual([m["marker_id"] for m in markers], [7])
        # Synthetic coordinates only; not surveyed workspace measurements.
        config = {"markers_mm": {7: [[0, 0], [100, 0], [100, 100], [0, 100]]}}
        result = calibrate(markers, config)
        self.assertTrue(result["valid"], result)
        np.testing.assert_allclose(transform_center([199.5, 199.5], result)["center_world_mm"], [50, 50], atol=.1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "marker.png"
            cv2.imwrite(str(path), image)
            config_path = Path(tmp) / "vision.yaml"
            config_path.write_text("output_dir: " + Path(tmp).as_posix() + "/out\naruco:\n  markers_mm: {}\n")
            report, output = run_image(path, config_path, aruco_only=True)
            self.assertTrue(output.exists())
            self.assertFalse(report["calibration"]["valid"])
            self.assertEqual(len(report["markers"]), 1)

    def test_calibration_failures(self):
        self.assertEqual(calibrate([], {})["reason"], "no_markers")
        marker = {"marker_id": 0, "corners_px": [[0,0],[10,0],[10,10],[0,10]]}
        self.assertEqual(calibrate([marker], {})["reason"], "insufficient_correspondences")
        self.assertFalse(calibrate([marker, marker], {})["valid"])
        cfg = {"markers_mm": {0: [[0,0],[1,0],[2,0],[3,0]]}}
        result = calibrate([marker], cfg)
        self.assertFalse(result["valid"])
        self.assertIsNone(transform_center([5,5], result)["center_world_mm"])
        self.assertFalse(transform_center([0,0], {"valid": True, "homography": [[1,0,0],[0,1,0],[0,0,0]]})["calibration_valid"])

    def test_conflicting_and_near_degenerate_calibration(self):
        marker = {"marker_id": 1, "corners_px": [[0,0],[100,0],[100,100],[0,100]]}
        second = {"marker_id": 2, "corners_px": [[200,0],[300,0],[300,100],[200,100]]}
        config = {"markers_mm": {1: marker["corners_px"],
                                   2: [[200,0],[300,0],[900,900],[200,100]]}}
        self.assertFalse(calibrate([marker, second], config)["valid"])
        config = {"markers_mm": {1: [[0,0],[1,0],[1,1e-9],[0,1e-9]]}}
        self.assertFalse(calibrate([marker], config)["valid"])

    def test_crop_clamping_and_padding(self):
        image = np.zeros((30, 40, 3), np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crop.png"
            save_crop(image, [-3, 2, 20, 25], path, padding=10)
            self.assertEqual(cv2.imread(str(path)).shape[:2], (30,30))
            with self.assertRaises(ValueError):
                save_crop(image, [50,50,60,60], path)


if __name__ == "__main__":
    unittest.main()
