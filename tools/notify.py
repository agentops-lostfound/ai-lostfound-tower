"""디스코드 웹훅 알림 (파이썬판 notify).

한줄 설명: 학습 완료·실패 같은 소식을 디스코드 채널에 자동으로 보내는 도구.

사용법
    python tools/notify.py "제목" "본문"
코드에서
    from tools.notify import notify
    notify("학습 완료", "yolo26s v1103 · mAP50-95 0.81")

- 웹훅 주소는 .env 의 DISCORD_WEBHOOK_URL 에서만 읽는다(코드에 쓰지 않음).
- 실패해도 예외를 던지지 않고 False 를 돌려준다(학습 스크립트가 알림 때문에 멈추지 않게).
- 오류 메시지에 웹훅 주소를 남기지 않는다(주소 자체가 비밀값).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.envfile import load_env  # noqa: E402

TITLE_LIMIT = 256
BODY_LIMIT = 4096
TIMEOUT_SEC = 10


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_payload(title: str, body: str) -> dict:
    embed: dict = {}
    if title.strip():
        embed["title"] = _cut(title, TITLE_LIMIT)
    if body.strip():
        embed["description"] = _cut(body, BODY_LIMIT)
    # @everyone 같은 멘션이 섞여도 알림이 울리지 않게 막는다
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


def notify(title: str, body: str = "", env_key: str = "DISCORD_WEBHOOK_URL") -> bool:
    """env_key: 웹훅 주소가 든 .env 이름(채널마다 다르게 쓸 수 있음)."""
    load_env()
    url = os.environ.get(env_key, "").strip()
    if not url:
        print(f"[notify] {env_key} 이 .env 에 없습니다", file=sys.stderr)
        return False
    if not url.startswith("https://discord.com/api/webhooks/"):
        print(f"[notify] {env_key} 형식이 웹훅 주소가 아닙니다", file=sys.stderr)
        return False
    if not title.strip() and not body.strip():
        print("[notify] 제목과 본문이 모두 비었습니다", file=sys.stderr)
        return False

    data = json.dumps(build_payload(title, body), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "ai-lostfound-tower"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
            return 200 <= res.status < 300
    except urllib.error.HTTPError as e:
        print(f"[notify] 전송 실패: HTTP {e.code}", file=sys.stderr)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        print(f"[notify] 전송 실패: {type(reason).__name__}", file=sys.stderr)
    return False


def main(argv: list[str]) -> int:
    title = argv[1] if len(argv) > 1 else "테스트 알림"
    body = argv[2] if len(argv) > 2 else "tools/notify.py 기본 테스트 문구입니다."
    ok = notify(title, body)
    print("전송 성공" if ok else "전송 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
