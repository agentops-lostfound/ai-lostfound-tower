"""전용 분실물 봇 — 디스코드 분실물 채널 메시지로 관제탑 가상 시연을 움직인다 (LF-29, 11/4, docs/design/virtual_demo.md).

한줄 설명: 분실물 채널에 "서면역 5번 출구 앞에서 검정 카드지갑 주웠어요" / "검정 카드지갑 잃어버렸어요" 를 쓰면
           관제탑(TOWER_SIM=1)에 HTTP 로 전하고, 진행판 메시지 하나를 단계마다 고쳐 보여 준다.

실행 (교육원 PC, 저장소 폴더, .venv 켠 상태 — 관제탑을 먼저 TOWER_SIM=1 로 켜 둔다)
    pip install -r tools/requirements-bot.txt
    python tools/lostfound_bot.py            # 디스코드에 연결(토큰은 .env LOSTFOUND_BOT_TOKEN)
    python tools/lostfound_bot.py --try "서면역 5번 출구 앞에서 검정 카드지갑 주웠어요"   # 디스코드 없이 같은 처리(터미널)

.env (값은 직접 넣는다. 화면·채팅·Git 에 쓰지 않는다)
    LOSTFOUND_BOT_TOKEN=     디스코드 개발자 포털에서 만든 봇 토큰
    LOSTFOUND_CHANNEL_ID=    봇이 읽을 채널 번호(여러 개면 쉼표). 다른 채널 메시지는 무시
    TOWER_URL=               관제탑 주소(기본 http://127.0.0.1:8100)
    LIVE_URL=                진행판 끝에 붙일 실시간 화면 주소(선택, 예: http://교육원PC주소:8100/live)

- 봇 규칙: 메시지 원문을 저장·전달하지 않고 관제탑에는 글만 보낸다. 관제탑이 장소 글·물건 특징만 남긴다
- 봇은 교육원 PC 에서 켜 둔 동안만 동작한다(2조봇과 같은 규칙). 디스코드 연결부 외의 판단은 BotCore(시험 가능)에 있다
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FOUND_RE = re.compile(r"주웠|주운|주워|발견|습득|떨어져\s*있|놓고\s*간|놓여\s*있")
LOST_RE = re.compile(r"잃어버|잃었|분실|찾고\s*있|찾아요|찾습니다|두고\s*내|놓고\s*내")
HELP = ("**분실물 봇 사용법**\n"
        "- 습득: `서면역 5번 출구 앞에서 검정 카드지갑 주웠어요` (역: 서면·해운대·중앙)\n"
        "- 분실: `검정 카드지갑 잃어버렸어요, 서면역에서요`\n"
        "- 확인 질문이 오면 답만 쓰기(모르면 `모름`)\n"
        "- 명령: `정지` · `원점` · `상태` · `초기화` · `도움말`\n"
        "- 시연 꼬리표: `#집기실패` `#보정실패` `#신분증불일치` `#수동인계`")
MARK = {"done": "✅", "active": "⏳", "fail": "❌", "todo": "⬜", "skip": "➖"}
PENDING_TTL_S = 300


class TowerError(RuntimeError):
    pass


class TowerClient:
    """관제탑 HTTP 입구(표준 라이브러리)."""

    def __init__(self, base: str | None = None, timeout: float = 10.0):
        self.base = (base or os.environ.get("TOWER_URL") or "http://127.0.0.1:8100").rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                d = json.loads(e.read().decode("utf-8")).get("detail")
            except Exception:
                d = None
            msg = d.get("message") if isinstance(d, dict) else d
            raise TowerError(str(msg or f"관제탑 오류 {e.code}")) from e
        except (urllib.error.URLError, OSError) as e:
            raise TowerError("관제탑에 연결할 수 없어요 — 관제탑(TOWER_SIM=1)이 켜져 있는지 확인") from e

    def get(self, path: str) -> dict:
        return self._call("GET", path)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self._call("POST", path, body or {})


def classify(text: str) -> str:
    """메시지 → help | stop | home | status | reset | found | lost | unknown"""
    t = (text or "").strip()
    cmd = t.lstrip("!/").strip()
    if cmd in ("도움말", "help", "사용법"):
        return "help"
    if cmd in ("정지", "멈춰", "stop"):
        return "stop"
    if cmd in ("원점", "원점 복귀", "home"):
        return "home"
    if cmd in ("상태", "status"):
        return "status"
    if cmd in ("초기화", "reset"):
        return "reset"
    f, l = bool(FOUND_RE.search(t)), bool(LOST_RE.search(t))
    if f and not l:
        return "found"
    if l and not f:
        return "lost"
    if f and l:
        return "found" if re.search(r"주웠|주운|습득", t) else "lost"
    return "unknown"


def progress_text(story: dict, live_url: str = "") -> str:
    """이야기 → 진행판 글(사람·AI 모두 읽기 쉽게 한 줄에 한 단계)."""
    kind = "습득 신고" if story.get("kind") == "found" else "분실 신고"
    names = {"item_id": "물건", "claim_id": "찾기", "case_id": "사례"}
    ids = " · ".join(f"{names.get(k, k)} {v}" for k, v in (story.get("ids") or {}).items())
    lines = [f"**[{story.get('story_id')} {kind}]** {ids}".rstrip()]
    for s in story.get("stages", []):
        detail = f" — {s['detail']}" if s.get("detail") and s.get("state") != "todo" else ""
        lines.append(f"{MARK.get(s.get('state'), '⬜')} {s.get('label')}{detail}")
    res = story.get("result")
    if res:
        lines.append(f"**결과: {'✅' if res.get('ok') else '⚠️'} {res.get('text')}**")
    if live_url:
        lines.append(f"실시간 화면: {live_url}")
    return "\n".join(lines)[:1900]


class BotCore:
    """디스코드와 무관한 판단: 메시지 → (답글, 따라갈 이야기 번호 또는 None)."""

    def __init__(self, client: TowerClient):
        self.client = client
        self.pending: dict[str, tuple[str, float]] = {}     # 작성자 → (확인 질문 번호, 시각)

    def handle(self, author: str, text: str) -> tuple[str, str | None]:
        text = (text or "").strip()[:300]
        if not text:
            return "", None
        try:
            kind = classify(text)
            pend = self.pending.get(author)
            if pend and time.time() - pend[1] > PENDING_TTL_S:
                self.pending.pop(author, None)
                pend = None
            if pend and kind == "unknown":          # 확인 질문 답(명령·새 신고가 아니면)
                self.pending.pop(author, None)
                d = self.client.post(f"/sim/lost/{pend[0]}/answer", {"text": text})
                return self._claimed(d), d.get("story_id")
            if kind == "help":
                return HELP, None
            if kind == "stop":
                d = self.client.post("/robot/stop")
                return ("🛑 정지 명령 보냄" + (" (반환 진행 중)" if d.get("running") else "") +
                        ("" if d.get("ok") else f" — 실패: {d.get('reason')}") + "\n주변 확인 뒤 `원점` 으로 복귀"), None
            if kind == "home":
                d = self.client.post("/robot/home", {"staff_confirmed": True})
                return ("🏠 원점 복귀 완료" if d.get("ok") else f"원점 복귀 실패: {d.get('reason')}"), None
            if kind == "reset":
                d = self.client.post("/sim/reset")
                n = sum(1 for i in (d.get("items") or []) if i.get("loc") == "bin")
                return f"🔄 가상 세계 초기화(보관함 시연 물건 {n}개 · 로봇 원점)", None
            if kind == "status":
                return self._status(), None
            if kind == "found":
                d = self.client.post("/sim/found", {"text": text})
                return (f"📥 **습득물 접수** `{d['item_id']}`\n장소: {d['place_text']} ({d['machine_id']})\n"
                        f"특징(가상 Qwen): {d['features']}\n→ 회수·보관함 배치를 진행판에서 보여 드려요"), d["story_id"]
            if kind == "lost":
                d = self.client.post("/sim/lost", {"text": text})
                if d.get("pending_id"):
                    self.pending[author] = (d["pending_id"], time.time())
                    cards = "\n".join(f"- `{c['item_id']}` {c['card']} ({c['station']})" for c in d["candidates"])
                    return f"🔎 닮은 습득물 후보\n{cards}\n**확인 질문:** {d['question']} (모르면 `모름`)", None
                return self._claimed(d), d.get("story_id")
            return "무슨 말인지 모르겠어요. `도움말` 을 써 보세요", None
        except TowerError as e:
            return f"⚠️ {e}", None
        except (KeyError, TypeError, ValueError) as e:
            return f"⚠️ 관제탑 응답을 읽지 못했어요({type(e).__name__})", None

    @staticmethod
    def _claimed(d: dict) -> str:
        return (f"📝 **찾기 요청** `{d['claim_id']}` → 후보 `{d['item_id']}` · 확인 질문 "
                f"{'통과' if d.get('quiz_passed') else '미통과(관제탑이 반환을 막는 장면)'}\n→ 방문·반환 과정을 진행판에서 보여 드려요")

    def _status(self) -> str:
        d = self.client.get("/live/state?after=999999999")
        w = d.get("world") or {}
        arm = w.get("arm") or {}
        items = w.get("items") or []
        count = lambda loc: sum(1 for i in items if i.get("loc") == loc)  # noqa: E731
        return (f"📡 관제탑 {'반환 진행 중' if d.get('busy') else '대기'} · 로봇 {'정지' if arm.get('stopped') else arm.get('phase', '-')}\n"
                f"보관함 {count('bin')}개 · 등록기계 {count('kiosk')}개 · 이동 중 {count('transit')}개 · 바구니 {count('basket')}개")

    def follow(self, story_id: str, update, live_url: str = "", timeout_s: float = 240.0, every_s: float = 1.5,
               sleep=time.sleep) -> dict | None:
        """이야기가 끝날 때까지 진행판 글을 update(글) 로 고친다(바뀔 때만). 마지막 이야기를 돌려준다."""
        last, story, end = "", None, time.time() + timeout_s
        while time.time() < end:
            try:
                story = self.client.get(f"/sim/stories/{story_id}")
            except TowerError:
                sleep(every_s)
                continue
            text = progress_text(story, live_url)
            if text != last:
                update(text)
                last = text
            if story.get("result"):
                return story
            sleep(every_s)
        return story


def run_discord() -> None:
    from tools.envfile import load_env
    load_env()
    token = os.environ.get("LOSTFOUND_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(".env 에 LOSTFOUND_BOT_TOKEN 이 없습니다(docs/design/virtual_demo.md 4장 — 봇 만들기)")
    channels = {c.strip() for c in os.environ.get("LOSTFOUND_CHANNEL_ID", "").split(",") if c.strip()}
    if not channels:
        raise SystemExit(".env 에 LOSTFOUND_CHANNEL_ID(분실물 채널 번호)가 없습니다")
    try:
        import discord
    except ImportError as e:      # 진짜 원인(예: Python 3.13 에서 audioop 없음)을 함께 보여 준다
        raise SystemExit(f"discord.py 를 불러오지 못했습니다({type(e).__name__}: {e}) — "
                         "pip install -r tools/requirements-bot.txt (Python 3.13 은 discord.py 2.5 이상)") from e
    import asyncio

    live_url = os.environ.get("LIVE_URL", "").strip()
    core = BotCore(TowerClient())
    intents = discord.Intents.default()
    intents.message_content = True            # 개발자 포털에서 MESSAGE CONTENT INTENT 를 켜야 함
    bot = discord.Client(intents=intents)

    @bot.event
    async def on_ready():
        print(f"[분실물 봇] 연결됨: {bot.user} · 채널 {len(channels)}개 · 관제탑 {core.client.base}")

    @bot.event
    async def on_message(msg):
        if msg.author.bot or str(msg.channel.id) not in channels:
            return
        try:
            reply, story = await asyncio.to_thread(core.handle, str(msg.author.id), msg.content)
            if not reply:
                return
            await msg.reply(reply, mention_author=False)
            print(f"[분실물 봇] {time.strftime('%H:%M:%S')} 답함({classify(msg.content)})"
                  + (f" · 진행판 {story}" if story else ""), flush=True)   # 메시지 원문은 남기지 않음
            if story:
                board = await msg.channel.send("⏳ 진행판 준비 중…")
                loop = asyncio.get_running_loop()

                def update(text):
                    asyncio.run_coroutine_threadsafe(board.edit(content=text), loop).result(timeout=10)
                await asyncio.to_thread(core.follow, story, update, live_url)
        except Exception as e:      # 한 메시지 실패가 봇 전체를 멈추지 않게, 원인만 탭에 남김
            print(f"[분실물 봇] {time.strftime('%H:%M:%S')} 처리 실패: {type(e).__name__}: {str(e)[:200]}", flush=True)

    import logging
    # 연결 끊김·재연결·권한 오류 같은 경고만 탭에 보인다(11/4: 예전에는 아무것도 안 찍혀 원인을 몰랐음)
    discord.utils.setup_logging(level=logging.WARNING)
    bot.run(token, log_handler=None)


def run_try(text: str) -> None:
    """디스코드 없이 터미널에서 같은 처리(관제탑은 켜져 있어야 함)."""
    core = BotCore(TowerClient())
    reply, story = core.handle("terminal", text)
    print(reply)
    if story:
        core.follow(story, lambda t: print("\n" + t), os.environ.get("LIVE_URL", ""))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="전용 분실물 봇(가상 시연)")
    ap.add_argument("--try", dest="try_text", help="디스코드 없이 메시지 하나 처리")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if a.try_text:
        from tools.envfile import load_env
        load_env()
        run_try(a.try_text)
    else:
        run_discord()


if __name__ == "__main__":
    main()
