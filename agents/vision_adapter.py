"""비전 결과 변환기 — 김건태 LF-3 시퀀스 결과를 관제탑 vision 부품으로 꽂기 (docs/design/integration.md).

한줄 설명: vision/sequence.py 가 만든 result_with_qwen.json(YOLO 박스 + Qwen general_items_v1 특징, 영어)을
관제탑 계약 모양 [{box, center, features}] (agents/contracts.py, 한국어 값)으로 바꾼다.

- Qwen 이 물건 하나에 수십 초 걸리므로(11/3 측정 약 50초/2개) 반환 중에 다시 돌리지 않는다.
  보관함을 찍을 때 시퀀스를 미리 돌려 두고, 관제탑은 가장 최근 결과 파일을 읽는다(SequenceFileVisionPart)
- 결과가 너무 오래됐거나(max_age_s) 읽을 수 없으면 빈 목록 → 흐름이 직원 확인으로 넘긴다(약속된 실패 값)
- Qwen 실패(status != ok)한 물건은 특징을 전부 '확인 불가'로 둔다(박스·중심은 살림)
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from agents.contracts import NONE, UNKNOWN, validate_detection

CATEGORY = {"wallet": "지갑", "card_wallet": "지갑", "usb": "USB", "lip_balm": "립밤", "phone": "모형폰",
            "hand_cream": "핸드크림", "power_bank": "보조배터리"}
COLOR = {"black": "검정", "white": "흰색", "gray": "회색", "grey": "회색", "silver": "회색", "red": "빨강",
         "blue": "파랑", "navy": "남색", "dark blue": "남색", "green": "초록", "yellow": "노랑", "brown": "갈색",
         "tan": "갈색", "beige": "갈색", "pink": "분홍", "rose": "분홍"}   # 11/4 분홍 추가(pink sand 등 꾸밈말 포함)
RESULT_NAME = "result_with_qwen.json"


def _color(colors: list[str]) -> str:
    for c in colors or []:
        key = c.strip().lower()
        if key in COLOR:
            return COLOR[key]
        for word, ko in COLOR.items():          # "dark brown", "matte black" 같은 꾸밈말
            if word in key:
                return ko
    return "기타" if colors else UNKNOWN


def to_features(qwen: dict | None, confidence: float) -> dict:
    """Qwen general_items_v1 특징 → 계약 특징(category·color·shape·material·mark·visible_text·confidence)."""
    conf = round(min(max(float(confidence or 0.0), 0.0), 1.0), 3)
    if not isinstance(qwen, dict):
        return {"category": UNKNOWN, "color": UNKNOWN, "shape": UNKNOWN, "material": UNKNOWN,
                "mark": UNKNOWN, "visible_text": UNKNOWN, "confidence": conf}
    status = qwen.get("sticker_status")
    stickers = [s for s in qwen.get("stickers") or [] if isinstance(s, dict)]
    if status == "present" and stickers:
        mark = ", ".join(" ".join(x for x in (s.get("shape"), "sticker", s.get("position") and f"({s['position']})") if x)
                         for s in stickers)
    elif status == "absent":
        mark = NONE
    else:
        mark = UNKNOWN
    texts = [t for t in qwen.get("logos_or_text") or [] if isinstance(t, str) and t.strip()]
    materials = [m for m in qwen.get("materials") or [] if isinstance(m, str) and m.strip()]
    return {"category": CATEGORY.get(qwen.get("category"), UNKNOWN),
            "color": _color(qwen.get("colors") or []),
            "shape": qwen.get("shape") or UNKNOWN,
            "material": ", ".join(materials) if materials else UNKNOWN,
            "mark": mark,
            # 글자를 못 읽었으면 비어 있다 → '없음'이 아니라 '확인 불가'(Qwen 프롬프트: 흐리면 비워 둠)
            "visible_text": ", ".join(texts) if texts else UNKNOWN,
            "confidence": conf}


# 11/4 결정(이순필·변재원): 작업대 표식(ArUco) 2개가 모두 보여야 보정을 믿는다.
#   표식 1개 = 모서리 4점이면 보정 공식이 4점에 딱 맞아 오차 검사(max_reprojection_error_mm)가 항상 통과 → 검증 불가
#   그래서 대응점 8개(표식 2개 × 4) 이상 + 오차 3mm 이하 + 물체별 calibration_valid 일 때만 center_mm 를 넘긴다.
#   보정이 안 되면 검출·특징은 그대로 넘기되(매칭은 가능) center_mm 를 빼서 로봇은 움직이지 않는다(supervisor.approach).
MIN_CALIB_POINTS = 8
MAX_REPROJ_MM = 3.0


def calibration_ok(report: dict) -> tuple[bool, str]:
    """보정을 믿어도 되는지 (결과, 이유). vision/aruco/calibration.py 의 calibrate() 결과 모양을 읽는다."""
    c = report.get("calibration") if isinstance(report, dict) else None
    if not isinstance(c, dict) or c.get("valid") is not True:
        return False, "보정 없음(표식을 못 찾음)"
    n = c.get("correspondence_count")
    if not isinstance(n, int) or n < MIN_CALIB_POINTS:
        return False, f"표식 2개가 모두 보이지 않음(대응점 {n}개 < {MIN_CALIB_POINTS})"
    err = c.get("max_reprojection_error_mm")
    if (not isinstance(err, (int, float)) or isinstance(err, bool)
            or not math.isfinite(err) or err < 0):
        return False, "보정 오차 측정값 없음/무효"
    if err > MAX_REPROJ_MM:
        return False, f"보정 오차 큼({err:.1f}mm > {MAX_REPROJ_MM}mm)"
    return True, ""


def adapt_report(report: dict) -> list[dict]:
    """시퀀스 결과 전체 → 계약 모양 검출 목록. 계약에 안 맞는 물건은 뺀다.
    보정을 믿을 수 있을 때(calibration_ok)만 center_mm 를 붙인다."""
    # LF3_UNIFIED_SAFETY_V1: only confirmed full analysis may authorize coordinates.
    # Partial reports may retain features for staff review, never center_mm.
    if not isinstance(report, dict):
        return []
    sequence_complete = report.get("sequence", {}).get("status") == "complete" if isinstance(report.get("sequence"), dict) else False
    objects = report.get("objects")
    if not isinstance(objects, list):
        return []
    ids = [obj.get("id") for obj in objects if isinstance(obj, dict)]
    if len(ids) != len(objects) or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
        return []  # Ambiguous object identity cannot be matched to a robot target.
    out = []
    calib_ok, _ = calibration_ok(report)
    for obj in objects:
        bbox, center = obj.get("bbox"), obj.get("center_px")
        conf = obj.get("confidence")
        def finite_numbers(values, count):
            return (isinstance(values, (list, tuple)) and len(values) == count
                    and all(type(v) in (int, float) and math.isfinite(v) for v in values))
        if (not finite_numbers(bbox, 4) or not (bbox[0] < bbox[2] and bbox[1] < bbox[3])
                or not finite_numbers(center, 2) or type(conf) not in (int, float)
                or not math.isfinite(conf) or not 0 <= conf <= 1):
            continue  # Keep other objects for staff investigation; no invalid coordinates.
        q = obj.get("qwen") or {}
        if not isinstance(q, dict):
            q = {}
        feats = to_features(q.get("features") if q.get("status") == "ok" else None, conf)
        det = {"box": [round(float(v), 1) for v in obj.get("bbox") or []],
               "center": [round(float(v), 1) for v in obj.get("center_px") or []],
               "features": feats, "vision_id": obj.get("id")}
        mm = obj.get("center_world_mm")
        if (sequence_complete and q.get("status") == "ok" and feats["category"] != UNKNOWN and calib_ok and obj.get("calibration_valid") is True and isinstance(mm, (list, tuple)) and len(mm) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in mm)):
            det["center_mm"] = [round(float(v), 1) for v in mm]
        if not validate_detection(det):
            out.append(det)
    return out


def captured_age(value, now: float | None = None) -> float | None:
    """captured_at(예: "2026-11-04T10:45:12+09:00") → 지금부터 몇 초 전인지. 없거나 형식이 틀리거나 시간대가 없으면 None."""
    if not isinstance(value, str) or not value.strip():
        return None
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:          # 시간대가 없으면 PC 시간대와 헷갈릴 수 있어 쓰지 않음
        return None
    age = (time.time() if now is None else now) - dt.timestamp()
    return age if age >= -5 else None    # 미래 시각(PC 시계 어긋남)이면 믿지 않음


def _diagnose(report: dict) -> dict | None:
    """김건태 vision/adapter_diagnostics.py 의 진단(검출 실패·미지원 품목·Qwen 오류 개수). 없거나 실패하면 None.
    진단은 원인 파악용이다 — 로봇·자동 반환 판단에는 쓰지 않는다."""
    try:
        from vision.adapter_diagnostics import diagnose_report
        d = diagnose_report(report, require_calibration=True)
        return {k: d.get(k) for k in ("scene_complete", "calibration_valid", "detected_count", "reason_counts")}
    except Exception:
        return None


class SequenceFileVisionPart:
    """CompositeBackend(vision=...) 에 꽂는 부품: 가장 최근 시퀀스 결과 파일을 읽는다.

    path: result_with_qwen.json 파일 또는 그 파일들이 들어 있는 outputs 폴더(하위 폴더까지 찾음)
    max_age_s: 결과가 이보다 오래됐으면 쓰지 않는다(보관함이 바뀌었을 수 있음). None 이면 검사 안 함
    """

    def __init__(self, path: str | Path, max_age_s: float | None = 600):
        self.path = Path(path)
        self.max_age_s = max_age_s
        self.last_reason = ""
        self.last_diagnosis: dict | None = None

    def _latest(self) -> Path | None:
        if self.path.is_file():
            return self.path
        if self.path.is_dir():
            files = sorted(self.path.rglob(RESULT_NAME), key=lambda p: p.stat().st_mtime)
            return files[-1] if files else None
        return None

    def vision_topview(self) -> list[dict]:
        try:
            f = self._latest()
            if f is None:
                self.last_reason = "탑뷰 결과 파일 없음"
                return []
            report = json.loads(f.read_text(encoding="utf-8"))
            # 나이 기준(11/4): 결과에 촬영 시각(captured_at, ISO 8601 + 시간대)이 있으면 그 값, 없으면 파일 저장 시각
            #   분석(45~76초) 뒤에 저장되므로 저장 시각은 실제 촬영보다 늦다 → captured_at 이 더 정확하다
            age = captured_age(report.get("captured_at"))
            if age is None:
                age = time.time() - f.stat().st_mtime
            if self.max_age_s is not None and age > self.max_age_s:
                self.last_reason = f"탑뷰 결과가 오래됨(촬영 {int(age)}초 전) — 보관함을 다시 찍기"
                return []
            if report.get("sequence", {}).get("status") not in ("complete", "failed", "no_detections"):
                self.last_reason = "탑뷰 분석이 아직 끝나지 않음"
                return []
            dets = adapt_report(report)
            ok, why = calibration_ok(report)
            self.last_reason = ("" if ok else f"{why} — 로봇은 움직이지 않음") if dets else "검출된 물건 없음"
            self.last_diagnosis = _diagnose(report)
            return dets
        except Exception as e:   # 약속: 예외를 던지지 않고 빈 목록
            self.last_reason = f"탑뷰 결과 읽기 실패({type(e).__name__})"
            return []


def vision_part_from_env(env: dict | None = None) -> SequenceFileVisionPart | None:
    """환경값 TOWER_VISION_FILE 이 있으면 그 결과 파일(또는 폴더)을 읽는 탑뷰 부품, 없으면 None(가짜 부품 유지).

    TOWER_VISION_MAX_AGE: 결과를 몇 초까지 믿을지(기본 600). 0 이면 나이 검사 안 함(저장해 둔 파일로 시험할 때)
    """
    import os
    env = os.environ if env is None else env
    path = str(env.get("TOWER_VISION_FILE") or "").strip()
    if not path:
        return None
    raw = str(env.get("TOWER_VISION_MAX_AGE") or "600").strip()
    try:
        age = float(raw)
    except ValueError:
        age = 600.0
    return SequenceFileVisionPart(path, max_age_s=None if age <= 0 else age)


__all__ = ["to_features", "adapt_report", "SequenceFileVisionPart", "vision_part_from_env", "CATEGORY", "COLOR"]
