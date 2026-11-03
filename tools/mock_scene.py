"""가짜 보관함 시나리오로 관제탑 끝까지 돌리기 — LF-14 (docs/design/swap_guide.md).

한줄 설명: 카메라·Qwen·로봇 없이, Qwen 이 냈을 법한 결과 파일(result_with_qwen.json)을 만들어
"탑뷰 결과 파일 읽기 → 변환 → 매칭 → 로봇 명령(가짜)" 전체 흐름이 맞게 도는지 사례별 표로 보여 준다.

사용법 (저장소 폴더, .venv 켠 상태)
    python tools/mock_scene.py                       # 시나리오 9개 실행 → 결과 표
    python tools/mock_scene.py --discord             # 디스코드에 붙일 짧은 요약(2조봇이 이 내용을 채팅에 답함)
    python tools/mock_scene.py --send                # AgentOps 관제 채널 3곳(진행·알림·점수)에도 전송(.env 웹후크)
    python tools/mock_scene.py --matcher simple      # 예전 단순 비교로 돌리기(기본은 김건태 정책, 11/3)
    python tools/mock_scene.py --compare             # 두 매칭 방식을 사례별로 나란히 비교
    python tools/mock_scene.py --write outputs/mock_scene   # 결과 파일만 만들기(API 의 TOWER_VISION_FILE 로 쓸 때)

- 물건 구성은 구매 예정 목록 기준(카드지갑 여러 색, 같은 제품 2세트, USB·보조배터리). 스티커는 쓰지 않는다(11/3 결정). 특징 값은 가상(추정)이다
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
from discord_ops.reporter import Reporter, find_pii  # noqa: E402

DISCORD_LIMIT = 1900


def qwen(category, colors, shape="rectangular", materials=("synthetic leather",), text=(), stickers=(), extra=()):
    """Qwen general_items_v1 모양(영어) 특징 하나"""
    st = [{"shape": s, "position": p} for s, p in stickers]
    return {"category": category, "colors": list(colors), "shape": shape, "materials": list(materials),
            "logos_or_text": list(text), "sticker_status": "present" if st else "absent", "stickers": st,
            "distinctive_features": list(extra)}


# 물건: 접수 번호 → 등록 때 Qwen(reg) / 보관함에서 찍은 Qwen(bin: None = 보관함에 없음, "failed" = Qwen 실패)
# 11/3 결정: 스티커는 구별에 쓰지 않는다 → 모든 물건 스티커 없음, 색·품목·보이는 글자로만 구별한다. 색은 가상(추정)
ITEMS: dict[str, dict] = {
    "A-20261103-0001": {"name": "카드지갑 검정", "reg": qwen("card_wallet", ["black"])},
    "A-20261103-0002": {"name": "카드지갑 빨강", "reg": qwen("card_wallet", ["red"])},
    "A-20261103-0003": {"name": "카드지갑 갈색",
                        "reg": qwen("card_wallet", ["brown"]),
                        # 같은 물건을 다시 찍었더니 표현이 흔들림: brown→dark brown, rectangular→rectangle
                        "bin": qwen("card_wallet", ["dark brown"], shape="rectangle")},
    "A-20261103-0004": {"name": "카드지갑 남색", "reg": qwen("card_wallet", ["navy"])},
    "B-20261103-0001": {"name": "USB 은색(SanDisk 글자)",
                        "reg": qwen("usb", ["silver"], shape="stick", materials=["metal", "plastic"], text=["SanDisk"])},
    "B-20261103-0002": {"name": "보조배터리 검정(VOVA 글자)",
                        "reg": qwen("power_bank", ["black"], materials=["plastic"], text=["VOVA"])},
    "A-20261103-0005": {"name": "카드지갑 남색 — 0004 와 같은 제품(2세트 구매), 아직 보관함에 안 옴",
                        "reg": qwen("card_wallet", ["navy"]), "bin": None},
    "A-20261103-0006": {"name": "카드지갑 노랑 — 보관함 사진에서 Qwen 실패",
                        "reg": qwen("card_wallet", ["yellow"]), "bin": "failed"},
}

# 사례: (번호, 설명, 찾는 물건, 기대 결과, 시나리오 옵션)
CASES = [
    ("S01", "정상 반환", "A-20261103-0001", "returned", {}),
    ("S02", "같은 검정이지만 품목이 다름(지갑 옆에 보조배터리)", "B-20261103-0002", "returned", {}),
    ("S03", "같은 물건인데 Qwen 표현이 흔들림(dark brown)", "A-20261103-0003", "returned", {}),
    ("S04", "다른 품목(USB)", "B-20261103-0001", "returned", {}),
    ("S05", "물건이 아직 보관함에 없음(똑같은 제품만 있음)", "A-20261103-0005", "staff_check", {}),
    ("S06", "보관함 사진에서 Qwen 실패", "A-20261103-0006", "staff_check", {}),
    ("S07", "집기 1번 실패 → 다시 집기 성공", "A-20261103-0002", "returned", {"grasp_plan": [False, True]}),
    ("S08", "탑뷰 결과 파일이 오래됨(보관함이 바뀌었을 수 있음)", "A-20261103-0001", "staff_check", {"stale": True}),
    ("S09", "똑같은 제품이 둘 다 보관 중 → 진짜 주인 물건이어도 직원 확인", "A-20261103-0004", "staff_check", {}),
]

# 아직 해결하지 않은 한계(매칭 부품별). 표에 ❌ 와 함께 이유를 보여 준다 — 기대 결과를 바꿔 숨기지 않는다
# (S05 '똑같이 생긴 다른 물건을 집음'은 11/3 닮은 물건 검사로 해결 → 직원 확인)
KNOWN_GAPS: dict[str, dict[str, str]] = {"policy": {}, "simple": {
    # 예전 단순 비교에서만 생김. 김건태 정책(기본)은 색을 먼저 걸러 통과
    "S03": "단순 비교는 색을 5칸 중 1칸으로만 봐서, 모양 표현이 흔들리면 다른 색 지갑과 동점 → 직원 확인(안전). 정책 매칭은 통과",
}}


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


def run_case(case: tuple, folder: Path, items: dict = ITEMS, max_age_s: float = 600, matcher=None) -> dict:
    cid, kind, item_id, expected, opt = case
    path = write_report(folder / cid, items, age_s=max_age_s * 2 if opt.get("stale") else 0)
    _, truth = build_report(items)
    part = SequenceFileVisionPart(path, max_age_s=max_age_s)
    mock = MockBackend(db=registered_db(items), grasp_plan=opt.get("grasp_plan", [True]))
    be = CompositeBackend(vision=part, matcher=matcher, fallback=mock)
    out = run_return(ReturnRequest(case_id=cid, item_id=item_id), be, Reporter(dry_run=True))
    picked = truth.get(out.matched_index) if out.matched_index is not None else None
    decision = out.decision
    if decision == "returned" and picked != item_id:
        decision = "wrong_object"
    return {"case_id": cid, "kind": kind, "item_id": item_id, "expected": expected, "decision": decision,
            "ok": decision == expected, "picked": picked, "reason": out.reason or part.last_reason,
            "robot_moved": any(c.startswith("robot_approach") for c in mock.calls), "steps": out.steps}


def run_all(items: dict = ITEMS, cases=CASES, matcher="policy") -> list[dict]:
    """matcher: 'policy'(기본) · 'simple' · 매칭 부품 객체 · None(= simple)"""
    if isinstance(matcher, str):
        matcher = make_matcher(matcher)
    with tempfile.TemporaryDirectory() as tmp:
        return [run_case(c, Path(tmp), items, matcher=matcher) for c in cases]


def make_matcher(name: str):
    """'simple'(기존 단순 비교) 또는 'policy'(김건태 matching/policy.py)"""
    if name == "policy":
        from agents.matcher_part import PolicyMatcherPart
        return PolicyMatcherPart()
    return None


LABEL = {"returned": "반환", "staff_check": "직원 확인", "rejected": "거절", "stopped": "정지", "wrong_object": "다른 물건 ⚠️"}


def table(results: list[dict], matcher: str = "policy") -> str:
    lines = ["사례 | 상황 | 기대 | 결과 | 판정 | 이유",
             "--- | --- | --- | --- | --- | ---"]
    for r in results:
        gap = "" if r["ok"] else KNOWN_GAPS.get(matcher, {}).get(r["case_id"], "")
        reason = f"{r['reason']} · 알려진 한계: {gap}" if gap else r["reason"]
        lines.append(f"{r['case_id']} | {r['kind']} | {LABEL.get(r['expected'], r['expected'])} | "
                     f"{LABEL.get(r['decision'], r['decision'])} | {'✅' if r['ok'] else '❌'} | {reason}")
    ok = sum(r["ok"] for r in results)
    wrong = sum(r["decision"] == "wrong_object" for r in results)
    lines += ["", f"맞음 {ok}/{len(results)} · 다른 물건 집음 {wrong}건 (가짜 시나리오, 특징 값은 가상)"]
    if wrong:
        lines.append("⚠️ 다른 물건을 집은 사례가 있습니다 — 실물 시연 전에 반드시 해결")
    return "\n".join(lines)


def compare_text(by: dict[str, list[dict]]) -> str:
    """매칭 방식별 결과를 사례마다 나란히(진짜 결과 파일이 생기면 같은 방식으로 비교)."""
    names = list(by)
    lines = ["사례 | 상황 | 기대 | " + " | ".join(names), "--- | --- | --- | " + " | ".join("---" for _ in names)]
    for i, r in enumerate(by[names[0]]):
        cells = [f"{'✅' if by[n][i]['ok'] else '❌'} {LABEL.get(by[n][i]['decision'], by[n][i]['decision'])}" for n in names]
        lines.append(f"{r['case_id']} | {r['kind']} | {LABEL.get(r['expected'], r['expected'])} | " + " | ".join(cells))
    lines.append("")
    for n in names:
        ok = sum(x["ok"] for x in by[n]); wrong = sum(x["decision"] == "wrong_object" for x in by[n])
        lines.append(f"{n}: 맞음 {ok}/{len(by[n])} · 다른 물건 집음 {wrong}건")
    return "\n".join(lines)


def discord_text(results: list[dict]) -> str:
    """2조봇 답·채팅용 짧은 요약(표 대신 줄 단위, 2000자 이하). 물건 번호·사례 번호만 쓴다."""
    lines = ["🧪 **가짜 보관함 시나리오** (카드지갑 기준 · 특징은 가상 · 카메라·로봇 없이)"]
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        lines.append(f"{mark} {r['case_id']} {r['kind']} → {LABEL.get(r['decision'], r['decision'])}")
        if r["decision"] != "returned":
            lines.append(f"　└ {r['reason']}")
    ok = sum(r["ok"] for r in results)
    wrong = sum(r["decision"] == "wrong_object" for r in results)
    lines.append(f"맞음 **{ok}/{len(results)}** · 다른 물건 집음 **{wrong}건**"
                 + (" ⚠️ 실물 시연 전에 반드시 해결" if wrong else ""))
    text = "\n".join(lines)
    return text if len(text) <= DISCORD_LIMIT else text[:DISCORD_LIMIT - 1] + "…"


def send_details(results: list[dict], reporter: Reporter | None = None) -> list[bool]:
    """AgentOps 관제 채널 3곳: 진행(사례별 단계) · 알림(자동 반환 안 한 이유) · 점수(요약)."""
    rep = reporter or Reporter(dry_run=False)
    prog = "\n".join(f"{r['case_id']} {r['kind']} → {LABEL.get(r['decision'], r['decision'])}: "
                     f"{' → '.join(r['steps']) or '(단계 없음)'}" for r in results)
    alerts = "\n".join(f"{r['case_id']} {r['item_id']} · {r['reason']}" for r in results
                       if r["decision"] != "returned") or "알림 없음"
    ok = sum(r["ok"] for r in results)
    wrong = sum(r["decision"] == "wrong_object" for r in results)
    return [rep.send("progress", f"가짜 시나리오: 반환 흐름 {len(results)}건", prog),
            rep.send("alert", "가짜 시나리오: 자동 반환 안 한 사례", alerts),
            rep.send("score", "가짜 시나리오: 결과", f"맞음 {ok}/{len(results)} · 다른 물건 집음 {wrong}건 (카드지갑 기준, 특징 가상)")]


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="가짜 보관함 시나리오로 관제탑 끝까지 돌리기")
    ap.add_argument("--write", metavar="폴더", help="결과 파일만 만들고 끝(TOWER_VISION_FILE 에 그 폴더를 넣어 쓰기)")
    ap.add_argument("--discord", action="store_true", help="표 대신 디스코드용 짧은 요약 출력")
    ap.add_argument("--send", action="store_true", help="AgentOps 관제 채널 3곳에도 전송")
    ap.add_argument("--matcher", choices=["simple", "policy"], default="policy",
                    help="매칭 부품: policy(기본, 김건태 matching/policy.py) / simple(예전 단순 비교)")
    ap.add_argument("--compare", action="store_true", help="두 매칭 방식을 사례별로 나란히 비교")
    a = ap.parse_args(argv)
    if a.write:
        path = write_report(a.write)
        print(f"만듦: {path}")
        print("API 에서 쓰려면 .env 에 TOWER_VISION_FILE=" + str(path.parent) + " , TOWER_VISION_MAX_AGE=0")
        return 0
    if a.compare:
        print(compare_text({"policy(기본)": run_all(matcher="policy"), "simple(예전)": run_all(matcher="simple")}))
        return 0
    results = run_all(matcher=a.matcher)
    text = discord_text(results) if a.discord else table(results, a.matcher)
    text = f"[매칭: {'김건태 정책(기본)' if a.matcher == 'policy' else '예전 단순 비교'}]\n" + text
    if find_pii(text):
        raise SystemExit("요약에 개인정보 모양이 있어 출력하지 않습니다")
    print(text)
    if a.send:
        print("\n관제 채널 전송:", send_details(results))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
