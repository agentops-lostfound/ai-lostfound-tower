"""관제탑 API (FastAPI) — LF-14 (docs/design/architecture.md 3장).

한줄 설명: 등록기계·분실인 웹·직원 화면이 HTTP로 관제탑을 부르는 입구. 규칙은 agents/service.py 에 있고 여기선 감싸기만 한다.

실행 (저장소 폴더, .venv 켠 상태)
    pip install -r agents/requirements.txt
    python -m uvicorn agents.api:app --host 127.0.0.1 --port 8100
    → 브라우저 http://127.0.0.1:8100/docs (요청을 직접 눌러 볼 수 있는 화면)

환경값(.env, 없으면 기본)
    TOWER_SEND=1      관제 채널(디스코드)로 실제 전송. 기본 0 = 화면에만
    TOWER_REVIEWER=1  LLM 검토(Ollama) 켜기. 기본 0
    TOWER_DB=1        물건 기록·상태·반환 기록을 PostgreSQL(DATABASE_URL)로. 기본 0 = 가짜 부품·메모리
- 기본은 시연용 가짜 부품(접수 번호 A-W01 ~ A-W07). 진짜 부품은 build_app(backend_factory=...) 로 바꾼다
- 같은 네트워크의 다른 PC(등록기계·웹)에서 부르려면 --host 0.0.0.0 (교육원 안에서만, 외부 공개 TBD)
"""
from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.service import Conflict, RequestError, TowerService, Unavailable, demo_backend_factory  # noqa: E402


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "0").strip().lower() in ("1", "true", "yes", "on")


def build_service(backend_factory=None) -> TowerService:
    from discord_ops.reporter import Reporter
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    reviewer = None
    if _flag("TOWER_REVIEWER"):
        from agents.llm_reviewer import OllamaReviewer
        reviewer = OllamaReviewer()
    recorder = None
    if _flag("TOWER_DB") and backend_factory is None:
        # DB 모드: 물건 기록·상태는 진짜 DB, 나머지 부품(비전·매칭·로봇)은 가짜 → 반환 기록도 DB 에 저장
        from agents.backends import CompositeBackend
        from agents.db_part import PostgresDbPart
        from agents.records import PostgresRecorder
        dsn = os.environ.get("DATABASE_URL", "")
        demo = demo_backend_factory()
        db_part = PostgresDbPart(dsn)
        backend_factory = lambda: CompositeBackend(db=db_part, fallback=demo().fallback)  # noqa: E731
        recorder = PostgresRecorder(dsn)
    return TowerService(backend_factory or demo_backend_factory(), Reporter(dry_run=not _flag("TOWER_SEND")),
                        recorder=recorder, reviewer=reviewer)


def build_app(service: TowerService | None = None):
    try:
        from fastapi import Body, FastAPI, HTTPException
    except ImportError as e:
        raise SystemExit("fastapi 가 없습니다. .venv 에서 `pip install -r agents/requirements.txt` 후 다시 실행하세요") from e
    from agents.tools import TOOLS

    svc = service or build_service()
    app = FastAPI(title="AI 분실물 관제탑 API", version="0.1")

    @app.get("/health")
    def health() -> dict:
        """살아 있는지, 부품이 진짜인지 가짜인지, 실행 중인지"""
        return svc.health()

    @app.get("/tools")
    def tools() -> list[dict]:
        """관제탑 도구 목록(담당·실패 규칙)"""
        return [{"name": t.name, "owner": t.owner, "summary": t.summary, "on_fail": t.on_fail} for t in TOOLS]

    @app.post("/returns")
    def start_return(payload: dict = Body(...)) -> dict:
        """반환 흐름 실행. 본문: case_id, item_id + 관문 결과 6개(true/false). 결과: 결정·이유·단계"""
        try:
            return svc.start_return(payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/returns")
    def recent(limit: int = 20) -> list[dict]:
        """최근 반환 기록(단계 제외)"""
        try:
            return svc.recent(limit)
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/returns/{case_id}")
    def get_case(case_id: str) -> dict:
        """반환 기록 하나(단계 포함)"""
        try:
            row = svc.get_case(case_id)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        if row is None:
            raise HTTPException(status_code=404, detail="기록 없음")
        return row

    return app


_APP = None


def __getattr__(name: str):
    # `uvicorn agents.api:app` 로 불릴 때만 앱을 만든다(import 만 할 때는 fastapi 가 없어도 됨)
    global _APP
    if name == "app":
        if _APP is None:
            _APP = build_app()
        return _APP
    raise AttributeError(name)
