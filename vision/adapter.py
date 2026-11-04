"""LF-3: Convert verified YOLO/Qwen reports into the team's detection contract.

Read-only conversion. No camera, Qwen, robot, database, or network operation occurs here.
For live operation, require measured ArUco calibration and a separate robot safety gate.
"""
import math

from agents.contracts import UNKNOWN, NONE, validate_detection

CATEGORY = {
    "wallet": "지갑",
    "card_wallet": "지갑",
    "usb": "USB",
    "lip_balm": "립밤",
    "phone": "모형폰",
    "power_bank": "보조배터리",
    "hand_cream": "핸드크림",  # Project mock-phone category, not a claim of real-vs-mock recognition.
}
COLOR = {
    "black": "검정", "white": "흰색", "gray": "회색", "grey": "회색",
    "red": "빨강", "blue": "파랑", "navy": "남색", "green": "초록",
    "yellow": "노랑", "brown": "갈색",
}


def _single_string(value):
    """Only one affirmative string is unambiguous; never invent a list summary."""
    if isinstance(value, str):
        return value.strip() if value.strip() and value.lower() not in ("unknown", "other") else None
    if isinstance(value, list) and len(value) == 1:
        return _single_string(value[0])
    return None


def _finite_numbers(value, length):
    return (isinstance(value, (list, tuple)) and len(value) == length
            and all(type(v) in (int, float) and math.isfinite(v) for v in value))


def adapt_report(report, *, require_calibration=True):
    """Return valid detections only; fail closed if the full sequence is incomplete.

    The contract's confidence field is populated from YOLO detection confidence,
    NOT Qwen feature accuracy or a calibrated match probability. Do not use it
    as a feature-confidence gate without a team contract change.
    """
    if not isinstance(report, dict):
        return []
    sequence = report.get("sequence")
    if not isinstance(sequence, dict) or sequence.get("status") != "complete":
        return []
    calibration = report.get("calibration")
    if require_calibration and (not isinstance(calibration, dict) or not calibration.get("valid", False)):
        return []
    objects = report.get("objects")
    if not isinstance(objects, list):
        return []

    results, seen = [], set()
    for obj in objects:
        if not isinstance(obj, dict):
            return []
        object_id = obj.get("id")
        if type(object_id) is not int or object_id in seen:
            return []
        seen.add(object_id)
        qwen = obj.get("qwen")
        if not isinstance(qwen, dict) or qwen.get("status") != "ok":
            return []
        raw = qwen.get("features")
        if not isinstance(raw, dict):
            return []
        bbox, center = obj.get("bbox"), obj.get("center_px")
        conf = obj.get("confidence")
        if (not _finite_numbers(bbox, 4) or not _finite_numbers(center, 2)
                or type(conf) not in (float, int) or not math.isfinite(conf)
                or not (0 <= conf <= 1)):
            return []
        raw_category = raw.get("category")
        category = CATEGORY.get(raw_category) if isinstance(raw_category, str) else None
        if category is None:
            # Unsupported categories (e.g. power_bank, hand_cream) cannot be
            # represented in the present team contract.
            return []

        raw_color = _single_string(raw.get("colors"))
        color = COLOR.get(raw_color.lower(), UNKNOWN) if raw_color else UNKNOWN
        shape = _single_string(raw.get("shape")) or UNKNOWN
        material = _single_string(raw.get("materials")) or UNKNOWN

        sticker_status = raw.get("sticker_status")
        if sticker_status == "absent":
            mark = NONE
        elif sticker_status == "present":
            # The presence is source-supported, but sticker descriptions may
            # be uncertain and are not synthesized from other fields.
            mark = "스티커 있음"
        else:
            mark = UNKNOWN

        features = {
            "category": category,
            "color": color,
            "shape": shape,
            "mark": mark,
            # No verified OCR/PII redaction path is integrated yet.
            "visible_text": UNKNOWN,
            "material": material,
            "confidence": float(conf),
        }
        detection = {
            "box": list(bbox),
            "center": list(center),  # PIXELS ONLY. Never center_world_mm.
            "features": features,
            "object_id": object_id,
        }
        if validate_detection(detection):
            return []
        results.append(detection)
    return results


class VisionPart:
    """Supply a fresh report via a caller-owned function.

    The caller is responsible for camera capture and model lifecycle.
    Default calibration gate prohibits live robot targeting before survey.
    """

    def __init__(self, report_provider, *, require_calibration=True):
        if not callable(report_provider):
            raise TypeError("report_provider must be callable")
        self.report_provider = report_provider
        self.require_calibration = require_calibration

    def vision_topview(self):
        try:
            return adapt_report(
                self.report_provider(),
                require_calibration=self.require_calibration,
            )
        except (OSError, RuntimeError, ValueError, TypeError):
            return []
