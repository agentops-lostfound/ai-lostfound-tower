"""전 과정 테스트 사례 실행기 — LF-15.

한줄 설명: 시험 사례 10개를 메인 AI 흐름에 넣어 결정·안전 규칙·로봇 결과를 채점하고, 점수판을 디스코드 형식으로 만든다.

사용법
    python evaluation/run_cases.py            # 화면에만 출력(가짜 부품)
    python evaluation/run_cases.py --send     # .env 웹후크로 디스코드에도 전송
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import DECISION_RETURNED  # noqa: E402
from agents.supervisor import ReturnRequest, run_return  # noqa: E402
from agents.tools import MockBackend  # noqa: E402
from discord_ops.reporter import Reporter, format_scoreboard  # noqa: E402
from evaluation.scoring import robot_score, safety_violations, supervisor_score  # noqa: E402

CASES = Path(__file__).with_name("test_cases.json")


def build_backend(spec: dict, case: dict) -> MockBackend:
    objs = spec["objects"]
    bin_items = [{"object_id": oid, "features": objs[oid], "center": [100 + 80 * i, 240]} for i, oid in enumerate(spec["bin"])]
    item_id = f"A-{case['case_id']}"
    db = {item_id: {"status": "본센터 보관", "features": objs[case["object"]], "object_id": case["object"]}}
    return MockBackend(bin_items=bin_items, db=db, grasp_plan=case.get("grasp_plan", [True]))


def run_all(spec: dict, reporter: Reporter, reviewer=None) -> dict:
    results = []
    trials = []
    for case in spec["cases"]:
        be = build_backend(spec, case)
        req = ReturnRequest(case_id=case["case_id"], item_id=f"A-{case['case_id']}", **case["input"])
        out = run_return(req, be, reporter, reviewer=reviewer)
        picked = out.matched_object   # 검출 목록이 걸러져도 물건 ID로 확인
        delivered = be.delivered()
        right_object = (picked == case["object"]) if out.decision == DECISION_RETURNED else None
        results.append({
            "case_id": case["case_id"], "kind": case["kind"], "expected": case["expected"], "decision": out.decision,
            "reason": out.reason, "approved": out.approved, "delivered": delivered, "picked": picked,
            "right_object": right_object, "quiz_passed": req.quiz_passed, "visitor_id_match": req.visitor_id_match,
        })
        if be.robot_moved():
            trials.append({"delivered": delivered and right_object is True, "stopped_on_fail": "robot_stop" in be.calls})
    # 다른 물건을 돌려줬다면 결정이 맞아도 틀린 것으로 본다
    for r in results:
        if r["right_object"] is False:
            r["decision"] = "wrong_object"
    viol = safety_violations(results, blocked_messages=len(reporter.blocked))
    return {"results": results, "violations": viol, "supervisor": supervisor_score(results, viol),
            "robot": robot_score(trials)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="시험 사례 10개 실행")
    ap.add_argument("--send", action="store_true", help="디스코드로 전송(.env 웹후크 필요)")
    ap.add_argument("--round", type=int, default=1, help="회차 번호")
    ap.add_argument("--reviewer", action="store_true", help="Ollama LLM 검토를 켜고 실행(잘못된 보류가 몇 건인지 측정)")
    a = ap.parse_args(argv)
    spec = json.loads(CASES.read_text(encoding="utf-8"))
    flow = Reporter(dry_run=True)            # 사례별 진행 알림은 화면용으로만 모은다
    reviewer = None
    if a.reviewer:
        from agents.llm_reviewer import OllamaReviewer
        reviewer = OllamaReviewer()
    rep = run_all(spec, flow, reviewer)
    if a.reviewer:
        holds = [r for r in rep['results'] if '검토 보류' in r['reason']]
        print(f"LLM 검토: 보류 {len(holds)}건 (기대가 '반환'인데 보류면 잘못된 보류 → 많으면 검토를 끄는 것이 낫다)")
    for r in rep["results"]:
        mark = "✅" if r["decision"] == r["expected"] else "❌"
        print(f"{mark} {r['case_id']} {r['kind']}: 기대 {r['expected']} / 결과 {r['decision']} ({r['reason']})")
    print(f"메인 AI {rep['supervisor']['score']}점 · 로봇 {rep['robot']['score']}점 · 안전 위반 {len(rep['violations'])}건")
    for v in rep["violations"]:
        print("  ⚠️", v)
    title, body = format_scoreboard(a.round, {"메인 AI": rep["supervisor"]["score"], "로봇팔": rep["robot"]["score"]},
                                    extra=f"사례 {rep['supervisor']['correct']}/{rep['supervisor']['total']} 통과 · 안전 위반 {len(rep['violations'])}건 · 가짜 부품 기준")
    Reporter(dry_run=not a.send).score(title, body)
    return 0 if rep["supervisor"]["score"] == 100 else 1


if __name__ == "__main__":
    raise SystemExit(main())
