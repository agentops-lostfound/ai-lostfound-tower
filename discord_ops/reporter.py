"""디스코드 관제 알림 — LF-17.

한줄 설명: 메인 AI의 단계별 진행·오류·점수를 알맞은 관제 채널로 보내고, 보내기 전에 개인정보가 섞였는지 검사한다.

채널과 .env 이름
    progress → DISCORD_WEBHOOK_PROGRESS  (#📊관제-진행)
    alert    → DISCORD_WEBHOOK_ALERT     (#🚨관제-알림)
    score    → DISCORD_WEBHOOK_SCORE     (#📈평가-점수)
    team     → DISCORD_WEBHOOK_TEAM      (팀 대화 채널, 예: 부산7기 #2조-분실물관리시스템) — 반환 1건당 결과 한 줄만
               비어 있으면 보내지 않는다(시험 채널로 대신 보내지 않음: 단계별 알림이 팀 대화를 덮지 않게)
    채널별 이름이 비어 있으면 DISCORD_WEBHOOK_URL(시험 채널) 하나로 보내고 제목 앞에 채널 이름을 붙인다.
dry_run=True(기본)이면 보내지 않고 messages 에만 쌓는다(시험·연습용).
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHANNELS = {
    "progress": ("DISCORD_WEBHOOK_PROGRESS", "📊관제-진행"),
    "alert": ("DISCORD_WEBHOOK_ALERT", "🚨관제-알림"),
    "score": ("DISCORD_WEBHOOK_SCORE", "📈평가-점수"),
    "team": ("DISCORD_WEBHOOK_TEAM", "2조 팀 채널"),
}
NO_FALLBACK = {"team"}   # 웹후크가 없으면 조용히 건너뜀
FALLBACK_KEY = "DISCORD_WEBHOOK_URL"

# 개인정보로 보이는 글자 모양(이름은 모양으로 못 찾으므로 메시지는 물건 번호로만 만든다)
PII_PATTERNS = {
    "전화번호": re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}"),
    "주민등록번호": re.compile(r"\d{6}[-\s]?[1-4]\d{6}"),
    "카드번호": re.compile(r"\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}"),
    "이메일": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
}


def find_pii(text: str) -> list[str]:
    return [name for name, pat in PII_PATTERNS.items() if pat.search(text or "")]


@dataclass
class Reporter:
    dry_run: bool = True
    messages: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)   # 개인정보 때문에 막은 메시지(안전 위반 기록)

    def send(self, channel: str, title: str, body: str = "") -> bool:
        if channel not in CHANNELS:
            raise ValueError(f"모르는 채널: {channel} (허용: {list(CHANNELS)})")
        pii = find_pii(f"{title}\n{body}")
        if pii:
            # 원문은 남기지 않고 어떤 종류가 걸렸는지만 기록한다
            self.blocked.append({"channel": channel, "kinds": pii})
            return False
        msg = {"channel": channel, "title": title, "body": body}
        self.messages.append(msg)
        if self.dry_run:
            return True
        return _post(channel, title, body)

    # 자주 쓰는 모양
    def progress(self, case: str, step: str, detail: str = "") -> bool:
        return self.send("progress", f"[{case}] {step}", detail)

    def alert(self, case: str, reason: str, detail: str = "") -> bool:
        return self.send("alert", f"[{case}] ⚠️ {reason}", detail)

    def score(self, title: str, body: str) -> bool:
        return self.send("score", title, body)

    def team(self, title: str, body: str = "") -> bool:
        return self.send("team", title, body)


def _post(channel: str, title: str, body: str) -> bool:
    from tools.envfile import load_env
    from tools.notify import notify
    load_env()
    key, label = CHANNELS[channel]
    if os.environ.get(key, "").strip():
        return notify(title, body, env_key=key)
    if channel in NO_FALLBACK:
        return False
    return notify(f"{label} | {title}", body, env_key=FALLBACK_KEY)


def format_scoreboard(round_no: int, scores: dict, prev: dict | None = None, extra: str = "") -> tuple[str, str]:
    """#📈평가-점수 메시지. scores = {에이전트: 점수}, prev = 지난 회차."""
    lines = []
    for name, val in scores.items():
        grade = "양호" if val >= 80 else ("보완 필요" if val >= 60 else "다시 하기")
        diff = ""
        if prev and name in prev:
            d = round(val - prev[name], 1)
            diff = f" ({'+' if d >= 0 else ''}{d})"
        lines.append(f"• {name}: **{val:.1f}**{diff} · {grade}")
    if extra:
        lines.append(extra)
    return f"{round_no}회차 점수", "\n".join(lines)
