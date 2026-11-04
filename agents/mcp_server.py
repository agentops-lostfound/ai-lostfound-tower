"""MCP 서버 — LF-16.

한줄 설명: agents/tools.py 의 도구들을 MCP 표준으로 열어, Claude·LangGraph 같은 AI가 같은 방식으로 부를 수 있게 한다.

실행(패키지 설치가 되는 PC, .venv 안에서)
    pip install mcp
    python agents/mcp_server.py            # 가짜 부품으로 실행(stdio)
- .env 에 TOWER_DB=1 이면 db_get_item 은 팀 DB(DATABASE_URL)를 읽는다. TOWER_VISION_FILE 이 있으면 vision_topview 는 그 결과 파일. 나머지는 가짜 부품
- 진짜 부품이 나오면 build_server(backend=진짜부품) 으로 바꾼다.
- 로봇을 움직이는 도구는 MCP로 열지 않는다. 로봇은 메인 AI 흐름(supervisor)이 안전 관문을 지난 뒤에만 부른다.
"""
from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import public_card  # noqa: E402
from agents.tools import TOOLS, MockBackend  # noqa: E402

# AI가 직접 부를 수 있는 도구(읽기·비교·알림만). 로봇·상태 변경은 제외
EXPOSED = ["vision_topview", "match_item", "db_get_item", "notify", "list_tools"]


def default_backend(env: dict | None = None):
    """TOWER_DB=1 이면 DB 부품 진짜(PostgreSQL), TOWER_VISION_FILE 이 있으면 탑뷰 부품 진짜(결과 파일). 나머지는 가짜."""
    env = os.environ if env is None else env
    from agents.vision_adapter import vision_part_from_env
    vision = vision_part_from_env(env)
    db = None
    if str(env.get("TOWER_DB", "")).strip().lower() in ("1", "true", "yes", "on"):
        from agents.db_part import PostgresDbPart
        db = PostgresDbPart(env.get("DATABASE_URL", ""))
    from agents.matcher_part import matcher_part_from_env
    matcher = matcher_part_from_env(env)
    if vision is None and db is None and matcher is None:
        return MockBackend()
    from agents.backends import CompositeBackend
    return CompositeBackend(vision=vision, matcher=matcher, db=db, fallback=MockBackend())


def build_server(backend=None, reporter=None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # 설치 안 된 PC
        raise SystemExit("mcp 패키지가 없습니다. .venv 에서 `pip install mcp` 후 다시 실행하세요") from e
    from discord_ops.reporter import Reporter

    be = backend or MockBackend()
    rep = reporter or Reporter(dry_run=True)
    app = FastMCP("lostfound-tower")

    @app.tool()
    def list_tools() -> list[dict]:
        """관제탑 도구 목록과 담당·실패 처리 규칙"""
        return [{"name": t.name, "owner": t.owner, "summary": t.summary, "on_fail": t.on_fail} for t in TOOLS]

    @app.tool()
    def vision_topview() -> list[dict]:
        """탑뷰 카메라로 공용 보관함을 찍어 물건마다 box·center·특징 JSON을 돌려준다"""
        return be.vision_topview()

    @app.tool()
    def match_item(query: dict, detections: list[dict]) -> dict:
        """접수 특징(query)과 탑뷰 물건들(detections)을 비교해 가장 유력한 물건을 고른다"""
        return be.match_item(query, detections)

    @app.tool()
    def db_get_item(item_id: str) -> dict | None:
        """접수 번호로 물건 기록을 읽는다(비공개 특징 = 확인 질문 정답은 빼고 돌려준다)"""
        rec = be.db_get_item(item_id)
        if rec is None:
            return None
        return {**rec, "features": public_card(rec.get("features") or {})}

    @app.tool()
    def notify(channel: str, text: str) -> dict:
        """디스코드 관제 채널(progress·alert·score)에 알림. 개인정보가 보이면 보내지 않는다"""
        return {"ok": rep.send(channel, text)}

    return app


if __name__ == "__main__":
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    build_server(backend=default_backend()).run()
