"""LF-3 inspection-only diagnostics for the existing fail-closed Vision Adapter.

Does not change adapt_report(), VisionPart, team contracts, or robot authorization.
The partial previews here MUST NEVER be used as detections for autonomous return.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

from vision.adapter import CATEGORY, adapt_report


def _numbers(values, count):
    return (isinstance(values, (list, tuple)) and len(values) == count
            and all(type(v) in (int, float) and math.isfinite(v) for v in values))


def _reason(obj):
    """Predict the concrete rejection code using only non-private metadata."""
    if not isinstance(obj, dict):
        return "invalid_object"
    if type(obj.get("id")) is not int:
        return "invalid_object_id"
    qwen = obj.get("qwen")
    if not isinstance(qwen, dict):
        return "missing_qwen_result"
    if qwen.get("status") != "ok":
        return "qwen_" + (qwen.get("status") if qwen.get("status") in ("failed", "pending", "cancelled") else "not_ok")
    raw = qwen.get("features")
    if not isinstance(raw, dict):
        return "invalid_qwen_features"
    cat = raw.get("category")
    if type(cat) is not str:
        return "invalid_category"
    if cat == "unknown":
        return "unknown_category"
    if cat == "other":
        return "other_category"
    if cat not in CATEGORY:
        return "unsupported_category"
    box, center, confidence = obj.get("bbox"), obj.get("center_px"), obj.get("confidence")
    if not _numbers(box, 4) or not (box[0] < box[2] and box[1] < box[3]):
        return "invalid_bbox"
    if not _numbers(center, 2):
        return "invalid_center_px"
    if type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        return "invalid_yolo_confidence"
    return "contract_validation_failed"


def diagnose_report(report, *, require_calibration=False):
    """Inspect every object independently, then compare with *actual* adapter output.

    accepted_preview contains standard contract detections for diagnosis ONLY.
    It is explicitly NOT a safe partial substitute for vision_topview().
    Raw Qwen distinctive text / logo contents are not copied to this report.
    """
    if not isinstance(report, dict):
        return {"inspection_only": True, "scene_complete": False,
                "sequence_status": "invalid_report", "reason": "invalid_report",
                "objects": [], "accepted_preview": [], "actual_adapter_count": 0,
                "calibration_valid": False, "reason_counts": {"invalid_report": 1}}
    sequence = report.get("sequence")
    status = sequence.get("status") if isinstance(sequence, dict) else None
    calib = report.get("calibration")
    calibrated = isinstance(calib, dict) and calib.get("valid") is True
    objects = report.get("objects")
    if not isinstance(objects, list):
        objects = []
        malformed_scene = True
    else:
        malformed_scene = False
    seen = set()
    object_reports, preview = [], []
    for index, obj in enumerate(objects):
        object_id = obj.get("id") if isinstance(obj, dict) else None
        reason = None
        if type(object_id) is int:
            if object_id in seen:
                reason = "duplicate_object_id"
            seen.add(object_id)
        if reason is None:
            reason = _reason(obj)
        if reason == "contract_validation_failed":
            # Test this object's format in isolation without changing the full-scene
            # gate. A synthetic COMPLETE status is used only for diagnosis.
            partial = {"sequence": {"status": "complete"},
                       "calibration": {"valid": calibrated}, "objects": [obj]}
            converted = adapt_report(partial, require_calibration=False)
            if len(converted) == 1:
                reason = None
                preview.append(converted[0])
        entry = {"index": index, "object_id": object_id if type(object_id) is int else None,
                 "status": "accepted_preview" if reason is None else "rejected",
                 "reason": reason}
        if reason in ("unsupported_category", "unknown_category", "other_category"):
            # Only bounded, known diagnostic labels; do not include unbounded
            # Qwen text, OCR, candidate descriptions, or exception messages.
            category = obj.get("qwen", {}).get("features", {}).get("category")
            entry["category"] = category if category in ("unknown", "other", "power_bank", "hand_cream") else "unsupported"
        object_reports.append(entry)

    reasons = Counter(o["reason"] for o in object_reports if o["reason"])
    if malformed_scene:
        reasons["invalid_objects_list"] += 1
    if not objects:
        reasons["no_detections"] += 1
    if status != "complete":
        reasons["sequence_incomplete"] += 1
    if require_calibration and not calibrated:
        reasons["calibration_unavailable"] += 1
    actual = adapt_report(report, require_calibration=require_calibration)
    scene_complete = (status == "complete" and not malformed_scene and bool(objects)
                      and len(preview) == len(objects) and not reasons
                      and (calibrated or not require_calibration)
                      and len(actual) == len(objects))
    return {"inspection_only": True, "scene_complete": scene_complete,
            "sequence_status": status, "calibration_valid": calibrated,
            "calibration_required": require_calibration,
            "detected_count": len(objects), "accepted_preview_count": len(preview),
            "actual_adapter_count": len(actual), "reason_counts": dict(sorted(reasons.items())),
            "objects": object_reports,
            "warning": "Accepted previews are for analysis only; never send partial previews to robot or autonomous-return flow."}


def main():
    parser = argparse.ArgumentParser(description="Inspect existing Qwen JSON; NO model inference or robot motion")
    parser.add_argument("--input", type=Path, required=True, help="Existing result_with_qwen.json")
    parser.add_argument("--output", type=Path, help="Default: alongside input, adapter_diagnostics.json")
    parser.add_argument("--require-calibration", action="store_true", help="also enforce measured calibration gate")
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8-sig"))
    diagnosis = diagnose_report(report, require_calibration=args.require_calibration)
    output = args.output or args.input.with_name("adapter_diagnostics.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "detected": diagnosis["detected_count"],
                      "accepted_preview": diagnosis["accepted_preview_count"],
                      "actual_adapter": diagnosis["actual_adapter_count"],
                      "scene_complete": diagnosis["scene_complete"],
                      "reasons": diagnosis["reason_counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
