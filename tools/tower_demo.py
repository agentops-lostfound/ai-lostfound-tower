"""관제탑 시연 한 번에 돌리기 — LF-17 (디스코드 봇·발표 시연용).

한줄 설명: 시험 사례 10개 + AI 자기 개선 회차를 돌리고, 디스코드에 그대로 붙일 수 있는 짧은 요약(2000자 이하)을 화면에 낸다.

사용법 (저장소 폴더에서)
    python tools/tower_demo.py                 # 요약만 화면에 출력(2조 봇이 이 내용을 채팅에 답함)
    python tools/tower_demo.py --send          # AgentOps 관제 채널 3곳에도 전송(.env 웹후크)
    python tools/tower_demo.py --reviewer      # 메인 AI LLM 검토(Ollama) 켜고 실행

- 진짜 카메라·로봇이 붙기 전까지는 가짜 부품 기준 결과임을 요약에 밝힌다.
- 요약에는 개인정보·비밀값이 들어가지 않는다(사례 번호·점수만).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_ops.reporter import Reporter, find_pii  # noqa: E402
from evaluation import improve_loop as il  # noqa: E402
from evaluation import run_cases  # noqa: E402

DISCORD_LIMIT = 1900
LABEL = {"returned": "반환", "rejected": "거절", "staff_check": "직원 확인", "stopped": "정지", "wrong_object": "다른 물건"}


def run_demo(reviewer=None) -> dict:
    t0 = time.perf_counter()
    spec = json.loads(run_cases.CASES.read_text(encoding="utf-8"))
    flow = Reporter(dry_run=True)
    cases = run_cases.run_all(spec, flow, reviewer)
    truths = il.demo_truths()
    loop = il.run_loop(truths, il.simulated_runner(truths), p95_limit=3.0, reporter=Reporter(dry_run=True))
    return {"cases": cases, "loop": loop, "alerts": [m for m in flow.messages if m["channel"] == "alert"],
            "seconds": round(time.perf_counter() - t0, 1)}


def summary_text(d: dict, reviewer_on: bool) -> str:
    c, loop = d["cases"], d["loop"]
    lines = ["🛰️ **AI 분실물 관제탑 시연** (가짜 부품 기준)", "", "**① 반환 흐름 시험 10건**"]
    for r in c["results"]:
        ok = "✅" if r["decision"] == r["expected"] else "❌"
        lines.append(f"{ok} {r['case_id']} {r['kind'].split('(')[0]} → {LABEL.get(r['decision'], r['decision'])}")
    lines.append(f"메인 AI **{c['supervisor']['score']:.0f}점** · 로봇 {c['robot']['score']:.0f}점 · 안전 위반 **{len(c['violations'])}건**"
                 + (" · LLM 검토 켬" if reviewer_on else ""))
    lines += ["", "**② AI 자기 개선 회차** (연습용 정답지 70장)"]
    for h in loop.history:
        if "chosen" in h:
            mark = "✅ 채택" if h["adopted"] else "✖ 거절"
            lines.append(f"{h['round']}회차 {mark}: {h['chosen']['tool']} → 검증용 {h['val_base']} → {h['val_cand']}")
    lines.append(f"멈춤: {loop.stop_reason}")
    lines += ["", f"⏱️ {d['seconds']}초 · 자세한 기록은 AgentOps #📊관제-진행 · #🚨관제-알림 · #📈평가-점수"]
    text = "\n".join(lines)
    return text if len(text) <= DISCORD_LIMIT else text[:DISCORD_LIMIT - 1] + "…"


def send_details(d: dict) -> list[bool]:
    rep = Reporter(dry_run=False)
    c, loop = d["cases"], d["loop"]
    prog = "\n".join(f"{r['case_id']} {r['kind']} → {LABEL.get(r['decision'], r['decision'])} ({r['reason']})" for r in c["results"])
    alerts = "\n".join(f"{m['title']} · {m['body']}" for m in d["alerts"]) or "알림 없음"
    rounds = "\n".join(f"{h['round']}회차 {'채택' if h['adopted'] else '거절'}: {h['chosen']['tool']}={h['chosen']['value']} "
                       f"({h['chosen']['reason']}) · 검증용 {h['val_base']}→{h['val_cand']}" for h in loop.history if "chosen" in h)
    return [
        rep.send("progress", "시연: 반환 흐름 시험 10건", prog),
        rep.send("alert", f"시연: 관제 알림 {len(d['alerts'])}건", alerts),
        rep.send("score", "시연: 점수판",
                 f"메인 AI {c['supervisor']['score']:.0f}점 · 로봇 {c['robot']['score']:.0f}점 · 안전 위반 {len(c['violations'])}건\n"
                 f"자기 개선 회차\n{rounds}\n멈춤: {loop.stop_reason}"),
    ]


def _utf8_stdout() -> None:
    """Windows에서 출력이 파이프로 넘어가면(봇·스크립트가 실행할 때) cp949라 이모지가 깨지거나 오류가 난다 → UTF-8로 고정"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="관제탑 시연")
    ap.add_argument("--send", action="store_true", help="AgentOps 관제 채널에도 전송")
    ap.add_argument("--reviewer", action="store_true", help="메인 AI LLM 검토(Ollama) 켜기")
    a = ap.parse_args(argv)
    reviewer = None
    if a.reviewer:
        from agents.llm_reviewer import OllamaReviewer
        reviewer = OllamaReviewer()
        reviewer.warmup()
    d = run_demo(reviewer)
    text = summary_text(d, reviewer is not None)
    if find_pii(text):
        raise SystemExit("요약에 개인정보 모양이 있어 출력하지 않습니다")
    print(text)
    if a.send:
        print("\n관제 채널 전송:", send_details(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
