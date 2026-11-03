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
import time
from pathlib import Path

from agents.contracts import NONE, UNKNOWN, validate_detection

CATEGORY = {"wallet": "지갑", "card_wallet": "지갑", "usb": "USB", "lip_balm": "립밤", "phone": "모형폰"}
COLOR = {"black": "검정", "white": "흰색", "gray": "회색", "grey": "회색", "silver": "회색", "red": "빨강",
         "blue": "파랑", "navy": "남색", "dark blue": "남색", "green": "초록", "yellow": "노랑", "brown": "갈색",
         "tan": "갈색", "beige": "갈색"}
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


def adapt_report(report: dict) -> list[dict]:
    """시퀀스 결과 전체 → 계약 모양 검출 목록. 계약에 안 맞는 물건은 뺀다."""
    out = []
    for obj in report.get("objects") or []:
        q = obj.get("qwen") or {}
        feats = to_features(q.get("features") if q.get("status") == "ok" else None, obj.get("confidence", 0.0))
        det = {"box": [round(float(v), 1) for v in obj.get("bbox") or []],
               "center": [round(float(v), 1) for v in obj.get("center_px") or []],
               "features": feats, "vision_id": obj.get("id")}
        if obj.get("center_world_mm"):
            det["center_mm"] = [round(float(v), 1) for v in obj["center_world_mm"]]
        if not validate_detection(det):
            out.append(det)
    return out


class SequenceFileVisionPart:
    """CompositeBackend(vision=...) 에 꽂는 부품: 가장 최근 시퀀스 결과 파일을 읽는다.

    path: result_with_qwen.json 파일 또는 그 파일들이 들어 있는 outputs 폴더(하위 폴더까지 찾음)
    max_age_s: 결과가 이보다 오래됐으면 쓰지 않는다(보관함이 바뀌었을 수 있음). None 이면 검사 안 함
    """

    def __init__(self, path: str | Path, max_age_s: float | None = 600):
        self.path = Path(path)
        self.max_age_s = max_age_s
        self.last_reason = ""

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
            age = time.time() - f.stat().st_mtime
            if self.max_age_s is not None and age > self.max_age_s:
                self.last_reason = f"탑뷰 결과가 오래됨({int(age)}초 전) — 보관함을 다시 찍기"
                return []
            report = json.loads(f.read_text(encoding="utf-8"))
            if report.get("sequence", {}).get("status") not in ("complete", "failed", "no_detections"):
                self.last_reason = "탑뷰 분석이 아직 끝나지 않음"
                return []
            dets = adapt_report(report)
            self.last_reason = "" if dets else "검출된 물건 없음"
            return dets
        except Exception as e:   # 약속: 예외를 던지지 않고 빈 목록
            self.last_reason = f"탑뷰 결과 읽기 실패({type(e).__name__})"
            return []


__all__ = ["to_features", "adapt_report", "SequenceFileVisionPart", "CATEGORY", "COLOR"]
