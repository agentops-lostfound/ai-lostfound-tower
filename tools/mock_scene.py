"""가짜 보관함 시나리오로 관제탑 끝까지 돌리기 — LF-14 (docs/design/swap_guide.md).

한줄 설명: 카메라·Qwen·로봇 없이, Qwen 이 냈을 법한 결과 파일(result_with_qwen.json)을 만들어
"탑뷰 결과 파일 읽기 → 변환 → 매칭 → 로봇 명령(가짜)" 전체 흐름이 맞게 도는지 사례별 표로 보여 준다.

사용법 (저장소 폴더, .venv 켠 상태)
    python tools/mock_scene.py                       # 시나리오 8개 실행 → 결과 표
    python tools/mock_scene.py --write outputs/mock_scene   # 결과 파일만 만들기(API 의 TOWER_VISION_FILE 로 쓸 때)

- 물건 구성은 구매 예정 목록 기준(카드지갑 검정·빨강, 같은 제품 쌍 + USB). 특징 값은 가상(추정)이다
- 등록기계 특징도 Qwen 이 뽑는다고 보고(architecture.md 3-3 ②), 등록 때 결과와 보관함 결과를 각각 만든다.
  같은 물건이라도 두 번 찍으면 Qwen 표현이 달라질 수 있어 그런 사례를 일부러 넣었다
- 판정: 기대 결과와 같으면 ✅. "다른 물건"은 반환은 했지만 엉뚱한 물건을 집은 경우(가장 위험)
- 진짜 결과 파일이 생기면 같은 흐름에 경로만 바꿔 넣는다(swap_guide.md 2장)
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.backends import CompositeBackend  # noqa: E402
from agents.supervisor import ReturnRequest, run_return  # noqa: E402
from agents.tools import MockBackend  # noqa: E402
from agents.vision_adapter import RESULT_NAME, SequenceFileVisionPart, to_features  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402


def qwen(category, colors, shape="rectangular", materials=("synthetic leather",), text=(), stickers=(), extra=()):
    """Qwen general_items_v1 모양(영어) 특징 하나"""
    st = [{"shape": s, "position": p} for s, p in stickers]
    return {"category": category, "colors": list(colors), "shape": shape, "materials": list(materials),
            "logos_or_text": list(text), "sticker_status": "present" if st else "absent", "stickers": st,
            "distinctive_features": list(extra)}


# 물건: 접수 번호 → 등록 때 Qwen(reg) / 보관함에서 찍은 Qwen(bin: None = 보관함에 없음, "failed" = Qwen 실패)
ITEMS: dict[str, dict] = {
    "A-20261103-0001": {"name": "카드지갑 검정(별 스티커)",
                        "reg": qwen("card_wallet", ["black"], stickers=[("star", "front corner")])},
    "A-20261103-0002": {"name": "카드지갑 검정(하트 스티커) — 0001 과 같은 제품",
                        "reg": qwen("card_wallet", ["black"], stickers=[("heart", "front corner")])},
    "A-20261103-0003": {"name": "카드지갑 빨강(스티커 없음)",
                        "reg": qwen("card_wallet", ["red"]),
                        # 같은 물건을 다시 찍었더니 표현이 흔들림: red→dark red, rectangular→rectangle
                        "bin": qwen("card_wallet", ["dark red"], shape="rectangle")},
    "A-20261103-0004": {"name": "카드지갑 빨강(작은 원 스티커)",
                        "reg": qwen("card_wallet", ["red"], stickers=[("small circle", "back center")])},
    "B-20261103-0001": {"name": "USB 은색(SanDisk 글자)",
                        "reg": qwen("usb", ["silver"], shape="stick", materials=["metal", "plastic"], text=["SanDisk"])},
    "A-20261103-0005": {"name": "카드지갑 빨강(스티커 없음) — 아직 보관함에 안 옴",
                        "reg": qwen("card_wallet", ["red"]), "bin": None},
    "A-20261103-0006": {"name": "카드지갑 검정(글자 MIYUON) — 보관함 사진에서 Qwen 실패",
                        "reg": qwen("card_wallet", ["black"], text=["MIYUON"]), "bin": "failed"},
}

# 사례: (번호, 설명, 찾는 물건, 기대 결과, 시나리오 옵션)
CASES = [
    ("S01", "정상 반환", "A-20261103-0001", "returned", {}),
    ("S02", "같은 제품, 스티커만 다름", "A-20261103-0002", "returned", {}),
    ("S03", "같은 물건인데 Qwen 표현이 흔들림", "A-20261103-0003", "returned", {}),
    ("S04", "다른 품목(USB)", "B-20261103-0001", "returned", {}),
    ("S05", "물건이 아직 보관함에 없음(비슷한 빨강 지갑만 있음)", "A-20261103-0005", "staff_check", {}),
    ("S06", "보관함 사진에서 Qwen 실패", "A-20261103-0006", "staff_check", {}),
    ("S07", "집기 1번 실패 → 다시 집기 성공", "A-20261103-0004", "returned", {"grasp_plan": [False, True]}),
    ("S08", "탑뷰 결과 파일이 오래됨(보관함이 바뀌었을 수 있음)", "A-20261103-0001", "staff_check", {"stale": True}),
]

# 아직 해결하지 않은 한계(결정 필요). 표에 ❌ 와 함께 이유를 보여 준다 — 기대 결과를 바꿔 숨기지 않는다
KNOWN_GAPS = {
    "S05": "생김새가 똑같은 물건은 사진만으로 구별 불가 → 보관 위치 기록 또는 닮은 물건 검사 필요(결정 필요)",
}


def build_report(items: dict = ITEMS) -> tuple[dict, dict]:
    """보관함 사진 1장에 대한 result_with_qwen.json(김건태 vision/sequence.py 모양)과 vision_id → 접수 번호 정답표"""
    objects, truth = [], {}
    for item_id, it in items.items():
        bin_q = it.get("bin", it["reg"])
        if bin_q is None:
            continue
        vid = len(objects)
        cx, cy = 120 + 110 * vid, 240
        q = {"status": "failed", "features": None} if bin_q == "failed" else {"status": "ok", "features": copy.deepcopy(bin_q)}
        objects.append({"id": vid, "class_name": "cell phone" if it["reg"]["category"] != "usb" else "remote",
                        "confidence": 0.8, "bbox": [cx - 45, cy - 30, cx + 45, cy + 30], "center_px": [cx, cy],
                        "center_world_mm": [round(40.0 * vid, 1), 150.0], "qwen": q})
        truth[vid] = item_id
    return {"sequence": {"status": "complete"}, "objects": objects}, truth


def write_report(folder: str | Path, items: dict = ITEMS, age_s: float = 0) -> Path:
    """폴더/mock_scene/result_with_qwen.json 을 쓰고 경로를 돌려준다(age_s 만큼 오래된 파일로 만들 수 있음)."""
    report, _ = build_report(items)
    path = Path(folder) / "mock_scene" / RESULT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if age_s:
        t = time.time() - age_s
        os.utime(path, (t, t))
    return path


def registered_db(items: dict = ITEMS) -> dict:
    """등록기계 Qwen 결과를 같은 변환기로 바꾼 물건 기록(진짜로는 팀 DB item 표)"""
    db = {}
    for item_id, it in items.items():
        f = to_features(it["reg"], 0.9)
        f.pop("confidence", None)
        db[item_id] = {"status": "본센터 보관", "features": f}
    return db


def run_case(case: tuple, folder: Path, items: dict = ITEMS, max_age_s: float = 600) -> dict:
    cid, kind, item_id, expected, opt = case
    path = write_report(folder / cid, items, age_s=max_age_s * 2 if opt.get("stale") else 0)
    _, truth = build_report(items)
    part = SequenceFileVisionPart(path, max_age_s=max_age_s)
    mock = MockBackend(db=registered_db(items), grasp_plan=opt.get("grasp_plan", [True]))
    be = CompositeBackend(vision=part, fallback=mock)
    out = run_return(ReturnRequest(case_id=cid, item_id=item_id), be, Reporter(dry_run=True))
    picked = truth.get(out.matched_index) if out.matched_index is not None else None
    decision = out.decision
    if decision == "returned" and picked != item_id:
        decision = "wrong_object"
    return {"case_id": cid, "kind": kind, "item_id": item_id, "expected": expected, "decision": decision,
            "ok": decision == expected, "picked": picked, "reason": out.reason or part.last_reason,
            "robot_moved": any(c.startswith("robot_approach") for c in mock.calls), "steps": out.steps}


def run_all(items: dict = ITEMS, cases=CASES) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        return [run_case(c, Path(tmp), items) for c in cases]


LABEL = {"returned": "반환", "staff_check": "직원 확인", "rejected": "거절", "stopped": "정지", "wrong_object": "다른 물건 ⚠️"}


def table(results: list[dict]) -> str:
    lines = ["사례 | 상황 | 기대 | 결과 | 판정 | 이유",
             "--- | --- | --- | --- | --- | ---"]
    for r in results:
        gap = "" if r["ok"] else KNOWN_GAPS.get(r["case_id"], "")
        reason = f"{r['reason']} · 알려진 한계: {gap}" if gap else r["reason"]
        lines.append(f"{r['case_id']} | {r['kind']} | {LABEL.get(r['expected'], r['expected'])} | "
                     f"{LABEL.get(r['decision'], r['decision'])} | {'✅' if r['ok'] else '❌'} | {reason}")
    ok = sum(r["ok"] for r in results)
    wrong = sum(r["decision"] == "wrong_object" for r in results)
    lines += ["", f"맞음 {ok}/{len(results)} · 다른 물건 집음 {wrong}건 (가짜 시나리오, 특징 값은 가상)"]
    if wrong:
        lines.append("⚠️ 다른 물건을 집은 사례가 있습니다 — 실물 시연 전에 반드시 해결")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="가짜 보관함 시나리오로 관제탑 끝까지 돌리기")
    ap.add_argument("--write", metavar="폴더", help="결과 파일만 만들고 끝(TOWER_VISION_FILE 에 그 폴더를 넣어 쓰기)")
    a = ap.parse_args(argv)
    if a.write:
        path = write_report(a.write)
        print(f"만듦: {path}")
        print("API 에서 쓰려면 .env 에 TOWER_VISION_FILE=" + str(path.parent) + " , TOWER_VISION_MAX_AGE=0")
        return 0
    results = run_all()
    print(table(results))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
