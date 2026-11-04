"""LF-3 full inference test: real image -> YOLO/ArUco -> Qwen -> Adapter -> CompositeBackend.

NO robot, database, matching, or automated return is called.
Unsafe, uncalibrated detections are displayed only in explicitly labeled inspection mode.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.backends import CompositeBackend, check_part
from agents.vision_adapter import SequenceFileVisionPart, adapt_report
from vision.sequence import run_sequence


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-image LF-3 full sequence and adapter handshake")
    parser.add_argument("--image", type=Path, required=True, help="Existing image file")
    parser.add_argument("--qwen-python", type=Path, required=True)
    parser.add_argument("--qwen-root", type=Path, default=Path("qwen"))
    parser.add_argument("--qwen-site-packages", type=Path)
    parser.add_argument("--qwen-cache-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--device", default="cpu", help="YOLO device: cpu or 0")
    args = parser.parse_args()

    if not args.image.is_file():
        parser.error(f"Image not found: {args.image}")

    print("[START] Real image -> YOLO/ArUco -> crops -> Qwen", flush=True)
    report, report_path = run_sequence(
        image=args.image,
        qwen_root=args.qwen_root,
        qwen_python=args.qwen_python,
        config=args.config,
        device=args.device,
        site_packages=args.qwen_site_packages,
        cache_dir=args.qwen_cache_dir,
    )
    print("[REPORT]", report_path)
    print("[SEQUENCE STATUS]", report.get("sequence", {}).get("status"))
    print("[DETECTED OBJECTS]", len(report.get("objects", [])))

    # Canonical team adapter; detections without validated center_mm are for
    # matching/staff review only. NEVER drive a robot from this test script.
    inspection = adapt_report(report)
    print("[ADAPTER / INSPECTION ONLY]", len(inspection))
    print("[CATEGORIES]", [d["features"]["category"] for d in inspection])
    print("[PIXEL CENTERS]", [d["center"] for d in inspection])

    # Robot-target candidates must additionally pass mm-coordinate safety.
    safe = [d for d in inspection if "center_mm" in d]
    print("[ADAPTER / CALIBRATION GATE]", len(safe))
    print("[CALIBRATION VALID]", bool(report.get("calibration", {}).get("valid", False)))

    # This is the actual production-facing file adapter (not the legacy LF-3 one).
    # max_age_s=None only for the offline smoke test of already stored photos.
    part = SequenceFileVisionPart(report_path, max_age_s=None)
    backend = CompositeBackend(vision=part)
    handshake = backend.vision_topview()
    print("[MISSING INTERFACE METHODS]", check_part(part, "vision"))
    print("[BACKEND VISION SOURCE]", backend.sources()["vision_topview"])
    print("[BACKEND / INSPECTION ONLY]", len(handshake))
    print("[OTHER BACKENDS]", {k: v for k, v in backend.sources().items() if k != "vision_topview"})

    # Save both separate lists, with explicit warnings, for manual inspection.
    output_path = Path(report_path).with_name("adapter_handshake_inspection.json")
    output_path.write_text(json.dumps({
        "notice": "INSPECTION ONLY; no robot motion is authorized by this output",
        "source_result": str(report_path),
        "sequence_status": report.get("sequence", {}).get("status"),
        "calibration_valid": bool(report.get("calibration", {}).get("valid", False)),
        "inspection_detections": inspection,
        "calibration_gated_detections": safe,
        "backend_source": backend.sources()["vision_topview"],
        "missing_methods": check_part(part, "vision"),
    }, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("[ADAPTER OUTPUT]", output_path)

    if report.get("sequence", {}).get("status") != "complete":
        print("[FAIL] Model sequence incomplete; do not use for downstream action")
        return 1
    if len(inspection) != len(report.get("objects", [])):
        print("[WARN] Some objects were excluded from the canonical adapter output")
    if handshake != inspection:
        print("[FAIL] Adapter / CompositeBackend mismatch")
        return 3
    print("[PASS] Real-image sequence and read-only CompositeBackend handshake verified")
    print("[NOTE] This does NOT validate vision accuracy or robot coordinates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
