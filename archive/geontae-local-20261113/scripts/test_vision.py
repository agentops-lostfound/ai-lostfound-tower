"""Single-image CLI; ArUco-only mode never imports torch or downloads weights."""
import argparse
import json
from vision_pipeline import run_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image")
    parser.add_argument("--config")
    parser.add_argument("--device", default=None, help="auto, cpu, or CUDA index such as 0")
    parser.add_argument("--aruco-only", action="store_true")
    parser.add_argument("--check-environment", action="store_true")
    args = parser.parse_args()
    if args.check_environment:
        from importlib.metadata import version
        from yolo.detector import runtime_info
        print(json.dumps({**runtime_info(args.device or "auto"), "versions": {
            name: version(name) for name in ["ultralytics", "opencv-python", "numpy", "PyYAML"]}}, indent=2))
        return
    if not args.image:
        parser.error("--image is required unless --check-environment is used")
    try:
        report, path = run_image(args.image, args.config, args.device, args.aruco_only)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"Vision failed: {error}\n")
    print(json.dumps({"result": str(path), "objects": len(report["objects"]),
                      "calibration": report["calibration"]}, indent=2))


if __name__ == "__main__":
    main()
