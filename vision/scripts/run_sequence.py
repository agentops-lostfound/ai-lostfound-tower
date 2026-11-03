"""CLI: photo -> YOLO/crops -> isolated Qwen -> combined JSON."""
import argparse
import json
from vision.sequence import run_sequence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--qwen-root", required=True)
    parser.add_argument("--qwen-python", required=True)
    parser.add_argument("--qwen-site-packages", help="Optional: reuse packages when the old venv launcher has a stale base path")
    parser.add_argument("--config")
    parser.add_argument("--device", default="cpu", help="YOLO device (Qwen uses its existing CUDA configuration)")
    args = parser.parse_args()
    try:
        report, path = run_sequence(args.image, args.qwen_root, args.qwen_python,
                                    args.config, args.device, args.qwen_site_packages)
    except KeyboardInterrupt:
        parser.exit(130, "Sequence cancelled during detection.\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Sequence failed: {error}\n")
    print(json.dumps({"result": str(path), "objects": len(report["objects"]),
                      "sequence": report["sequence"]}, ensure_ascii=False, indent=2))
    if report["sequence"]["status"] == "cancelled":
        return 130
    return 1 if report["sequence"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
