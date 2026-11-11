"""에이전트 대화 시연·전송 시험 (LF-14 · 11/9 변재원)

한줄 설명: 관제탑을 켜지 않고 가상 시연(습득 2건 → 분실 1건 → 반환)을 한 번 돌려, 에이전트 대화를 화면에 찍고
`--send` 를 주면 **디스코드 에이전트 채널(DISCORD_WEBHOOK_AGENT)로만** 보낸다. 다른 관제 채널(진행·경보·점수·팀)로는 보내지 않는다.

사용법 (저장소 폴더, .venv)
    python tools/agent_talk_demo.py            # 화면에만
    python tools/agent_talk_demo.py --send     # + 디스코드 🤖에이전트-대화 채널(대화 3개 = 메시지 3개)
- 웹후크가 없으면 보내지 않고 알려 준다. 웹후크 주소는 화면에 찍지 않는다
- 첫 습득에서 채점 에이전트 도움 → 되돌아보기 → 다시 답, 두 번째 습득에서 배운 점 반영, 반환에서 로봇팔 위치 확인이 보인다
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STORIES = ["초량역 5번 출구 앞에서 검정 카드지갑 주웠어요", "중앙역 2번 출구에서 파란 보조배터리 주웠어요"]
LOST = "검정 카드지갑 잃어버렸어요 초량역에서요"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="에이전트 대화 시연·디스코드 에이전트 채널 전송 시험")
    ap.add_argument("--send", action="store_true", help="디스코드 에이전트 채널(DISCORD_WEBHOOK_AGENT)로만 보냄")
    args = ap.parse_args(argv)
    try:                                            # Windows 터미널에서 → · 이모지가 깨지지 않게
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    if args.send and not (os.environ.get("DISCORD_WEBHOOK_AGENT") or "").strip():
        print("DISCORD_WEBHOOK_AGENT 가 .env 에 없어요 — docs/design/agent_talk.md 5장대로 웹후크를 넣은 뒤 다시 실행하세요")
        return 2
    from agents.sim_director import build_sim_service
    from discord_ops.reporter import Reporter
    env = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_SEND": "0", "TOWER_AGENT_TALK": "1"}
    svc = build_sim_service(env)                    # 진행·경보 등은 보내지 않음(TOWER_SEND=0)
    talk = svc.talk
    if args.send:
        talk.rep = Reporter(dry_run=False)          # 에이전트 대화 묶음만 진짜로 보냄(화면 기록판은 그대로)
    d = svc.sim
    for text in STORIES:
        d.found(text)
        d.wait_idle(60)
    d.lost(LOST)
    d.wait_idle(120)
    story = None
    for e in svc.board.since(0, limit=999):
        if e["channel"] != "agent":
            continue
        if e["story"] != story:
            story = e["story"]
            print(f"\n── {story} ──")
        a = e["agent"]
        score = f" [{a['score']}점]" if a.get("score") is not None else ""
        print(f"{a['from']} → {a['to']} · {a['kind']}: {e['body']}{score}")
    if args.send:
        sent = [m for m in talk.rep.messages if m["channel"] == "agent"]
        print(f"\n디스코드 에이전트 채널로 보낸 대화: {len(sent)}개(습득 2 + 반환 1 이 정상)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
