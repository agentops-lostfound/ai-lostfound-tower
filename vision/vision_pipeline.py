import json
from importlib.metadata import PackageNotFoundError, version as _dist_version


def version(name):
    """설치된 패키지 버전. opencv 는 headless 판(CI 등)도 같은 것으로 본다(11/5)."""
    names = [name, name + "-headless"] if name.startswith("opencv-") else [name]
    for n in names:
        try:
            return _dist_version(n)
        except PackageNotFoundError:
            continue
    return "unknown"
from pathlib import Path
from uuid import uuid4
import cv2
import numpy as np
import yaml
from .yolo.detector import YoloDetector
from .yolo.cropper import save_crop
from .aruco.detector import detect_markers
from .aruco.calibration import calibrate, transform_center

VISION_ROOT = Path(__file__).resolve().parent
ROOT = VISION_ROOT.parent


def run_image(image_path, config_path=None, device=None, aruco_only=False):
    config_path = Path(config_path or VISION_ROOT / "configs/vision.yaml").resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    image_path = Path(image_path).resolve()
    image = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read image: {image_path}")
    output = Path(config.get("output_dir", "outputs"))
    if not output.is_absolute():
        output = ROOT / output
    run_dir = output / uuid4().hex
    run_dir.mkdir(parents=True)
    markers = detect_markers(image, config["aruco"].get("dictionary", "DICT_4X4_50"))
    calibration = calibrate(markers, config["aruco"])
    objects, runtime = [], None
    if not aruco_only:
        model = Path(config["model"])
        if not model.is_absolute():
            model = ROOT / model
        detector = YoloDetector(model, device or config.get("device", "auto"),
                                config.get("confidence", 0.25), config.get("imgsz", 640))
        runtime = detector.runtime
        objects = detector.detect(image)
    debug = image.copy()
    for obj in objects:
        obj["crop_path"] = save_crop(image, obj["bbox"], run_dir / "crops" / f'object_{obj["id"]}.jpg',
                                     config.get("crop_padding_px", 0))
        obj.update(transform_center(obj["center_px"], calibration))
        x1, y1, x2, y2 = map(round, obj["bbox"])
        center = tuple(map(round, obj["center_px"]))
        cv2.rectangle(debug, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.circle(debug, center, 4, (0, 0, 255), -1)
        cv2.putText(debug, f'{obj["id"]}: {obj["class_name"]} {obj["confidence"]:.2f} {center}',
                    (x1, max(15, y1-5)), cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 255, 0), 1)
    if markers:
        cv2.aruco.drawDetectedMarkers(debug, [np.float32(m["corners_px"]).reshape(1, 4, 2) for m in markers],
                                     np.int32([m["marker_id"] for m in markers]).reshape(-1, 1))
    debug_path = run_dir / "debug.jpg"
    ok, encoded = cv2.imencode(".jpg", debug)
    if not ok:
        raise OSError("Cannot encode debug image")
    encoded.tofile(str(debug_path))
    report = {"image_path": str(image_path), "mode": "aruco_only" if aruco_only else "full",
              "runtime": runtime, "versions": {name: version(name) for name in ["opencv-python", "numpy", "PyYAML"] + ([] if aruco_only else ["ultralytics"])},
              "objects": objects, "markers": markers,
              "calibration": calibration, "debug_path": str(debug_path)}
    from .installation_coordinates import work_context, coordinate_chain, load_installation
    report['coordinate_context']=work_context(config['aruco'])
    report['coordinate_chain']=coordinate_chain(report,load_installation())
    (run_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report, run_dir / "result.json"
