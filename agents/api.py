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
    TOWER_VISION_FILE 탑뷰 결과(result_with_qwen.json) 파일 또는 폴더 → 탑뷰 부품만 진짜 결과로(docs/design/swap_guide.md)
    TOWER_VISION_MAX_AGE  결과를 몇 초까지 믿을지(기본 600, 0 = 검사 안 함)
    TOWER_MATCHER         매칭 부품. 비움/policy = 김건태 matching/policy.py(11/3 기본), simple = 예전 단순 비교
    TOWER_SIM=1       전체 가상 시연(등록기계·Qwen·탑뷰·로봇팔 가상, docs/design/virtual_demo.md). TOWER_SIM_SPEED(시간 배수, 기본 1)
    TOWER_GPU_LEASE       GPU 사용권(agents/gpu_lease.py). 기본 켬, 0 = 끔. TOWER_GPU_WAIT(초, 기본 60) · TOWER_GPU_FREE_MB(남은 메모리 확인, 기본 없음)
- 등록기계 화면: GET /intake?machine=KIOSK-A(화면), GET /places, POST /items(사진 data URL 포함 가능), POST /items/{item_id}/features (안내 intake_machine/README.md)
    TOWER_PHOTO_DIR  등록기계 사진 저장 폴더(기본 저장소/data → data/photos/기계/…, Git 에 안 올림)
- 직원 화면: POST /returns/{case_id}/handover — 바구니의 물건을 분실인에게 건넨 뒤 인계 완료로(11/4)
            POST /returns/{case_id}/hold — 건네지 않기로 함(이유 4개 중 하나) → 반환 보류
            POST /robot/stop (반환 진행 중에도) · POST /robot/home (주변 확인 뒤, 진행 중이면 409)
- 실시간 화면: GET /live (보관함·로봇팔·진행) · GET /live/state · 가상 시연 POST /sim/found · /sim/lost · /sim/reset
- 기본은 시연용 가짜 부품(접수 번호 A-W01 ~ A-W07). 진짜 부품은 build_app(backend_factory=...) 로 바꾼다
- 같은 네트워크의 다른 PC(등록기계·웹)에서 부르려면 --host 0.0.0.0 (교육원 안에서만, 외부 공개 TBD)
"""
from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.service import (Conflict, NotFound, RequestError, TowerService, Unavailable,  # noqa: E402
                            demo_backend_factory)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAFF_PAGE = os.path.join(ROOT, "web", "staff-desk", "index.html")
LIVE_PAGE = os.path.join(ROOT, "web", "live", "index.html")     # 11/4 실시간 화면(보관함·로봇팔·진행)
# 등록기계 화면(11/4): intake_machine/index.html 이 생기면 그것을, 아니면 지금 화면 시안(web/found-item-intake.html)을 연다
INTAKE_PAGES = [os.path.join(ROOT, "intake_machine", "index.html"), os.path.join(ROOT, "web", "found-item-intake.html")]


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "0").strip().lower() in ("1", "true", "yes", "on")


def _with_vision_file(backend_factory):
    """환경값으로 진짜 부품을 바꿔 끼운다(build_service 에 직접 넘긴 부품(시험용)에는 쓰지 않는다).
    - TOWER_VISION_FILE: 탑뷰 부품 → 결과 파일(김건태 LF-3 result_with_qwen.json)
    - TOWER_MATCHER=policy: 매칭 부품 → 김건태 matching/policy.py (agents/matcher_part.py)"""
    from agents.matcher_part import matcher_part_from_env
    from agents.vision_adapter import vision_part_from_env
    part = vision_part_from_env()
    matcher = matcher_part_from_env()
    if part is None and matcher is None:
        return backend_factory
    from agents.backends import CompositeBackend
    base = backend_factory or demo_backend_factory()

    def make():
        be = base()
        route = getattr(be, "_route", {})
        db = route.get("db_get_item")
        return CompositeBackend(vision=part, matcher=matcher, db=db, fallback=getattr(be, "fallback", be))
    return make


def build_service(backend_factory=None) -> TowerService:
    from agents.live import LiveBoard, LiveReporter
    from discord_ops.reporter import Reporter
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    if _flag("TOWER_SIM") and backend_factory is None:
        # 11/4 전체 가상 시연(docs/design/virtual_demo.md): 등록기계·Qwen·탑뷰·로봇팔을 가상 부품으로, 접수·DB 는 메모리
        if _flag("TOWER_DB"):
            print("[관제탑] TOWER_SIM=1 이라 TOWER_DB 는 쓰지 않습니다(가상 시연은 메모리)", file=sys.stderr)
        from agents.sim_director import build_sim_service
        return build_sim_service()
    reviewer = None
    if _flag("TOWER_REVIEWER"):
        from agents.llm_reviewer import OllamaReviewer
        reviewer = OllamaReviewer()
    recorder = None
    claims = None
    intake = None
    user_factory = backend_factory is not None
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
        from agents.claims import PostgresClaimStore
        claims = PostgresClaimStore(dsn)
        from agents.intake import PostgresIntakeStore
        intake = PostgresIntakeStore(dsn)
    if not user_factory:
        backend_factory = _with_vision_file(backend_factory)
    from agents.gpu_lease import lease_from_env
    board = LiveBoard()      # 실시간 화면(/live)용 사건 기록 — 진짜 부품 모드에서도 같은 화면에 진행이 보인다
    svc = TowerService(backend_factory or demo_backend_factory(),
                       LiveReporter(Reporter(dry_run=not _flag("TOWER_SEND")), board),
                       recorder=recorder, reviewer=reviewer, claims=claims, intake=intake,
                       gpu_lease=lease_from_env())
    svc.board = board
    return svc


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

    @app.get("/places")
    def places(machine_id: str, limit: int = 10) -> list[dict]:
        """등록기계 화면 2번: 이 기계 역의 추천 습득 장소(많이 고른 순). 목록에 없으면 화면에서 직접 입력"""
        try:
            return svc.list_places(machine_id, limit)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/items")
    def create_item(payload: dict = Body(...)) -> dict:
        """등록기계 화면: 습득물 접수 → 접수 번호. 본문: machine_id, place_text(필수), place_id(추천 고른 경우),
        finder {name, phone}(둘 다 선택 — 비우면 저장 안 함), photo(선택, data:image/jpeg;base64,… 5MB 이하) 또는 photo_path.
        연락처는 응답에 나오지 않음"""
        try:
            return svc.create_item(payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/items/{item_id}/features")
    def set_item_features(item_id: str, payload: dict = Body(...)) -> dict:
        """뒤에서 도는 Qwen 작업(김건태 LF-3): {"qwen": general_items_v1 특징, "confidence": 0~1} → 물건 특징 저장"""
        try:
            return svc.set_item_features(item_id, payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/claims")
    def create_claim(payload: dict = Body(...)) -> dict:
        """웹(1단계): 찾기 요청 저장. 본문: consent, name_masked, id_no_masked(가린 값), id_verified, description,
        item_id(고른 후보), quiz[{field, passed}], visit_date (+ lost_line·lost_station·lost_date). 결과: claim_id·웹 관문"""
        try:
            return svc.create_claim(payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/claims/{claim_id}")
    def get_claim(claim_id: str) -> dict:
        """직원 화면: 찾기 요청 하나(가린 이름·물건 번호·예약·웹 관문 결과)"""
        try:
            row = svc.get_claim(claim_id)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        if row is None:
            raise HTTPException(status_code=404, detail="없는 찾기 번호")
        return row

    @app.post("/returns")
    def start_return(payload: dict = Body(...)) -> dict:
        """반환 흐름 실행. 본문 둘 중 하나
        - 2단계(권장): claim_id + visitor_id_match·inner_feature_ok·staff_confirmed (웹 결과는 저장된 값 사용)
        - 1단계: case_id, item_id + 관문 결과 6개(시연·시험용)"""
        try:
            return svc.start_return(payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/returns/{case_id}/handover")
    def handover(case_id: str, payload: dict = Body(...)) -> dict:
        """직원 화면: 바구니의 물건을 분실인에게 건넴 → 인계 대기 → 인계 완료. 본문 {"staff_confirmed": true}"""
        try:
            return svc.handover(case_id, payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/returns/{case_id}/hold")
    def hold_handover(case_id: str, payload: dict = Body(...)) -> dict:
        """직원 화면: 인계 대기 중 건네지 않음(본인 아님·물건 다름·분실인 거부·기타) → 반환 보류 + 경보. 본문 {"reason": "본인 아님"}"""
        try:
            return svc.hold_handover(case_id, payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/robot/stop")
    def robot_stop() -> dict:
        """직원 화면 🛑 정지: 반환 진행 중에도 동작. 다음 로봇 동작을 막고 즉시 정지(원점 복귀 안 함)"""
        return svc.stop_robot()

    @app.post("/robot/home")
    def robot_home(payload: dict = Body(...)) -> dict:
        """직원 화면 원점 복귀: 주변 확인 뒤에만. 본문 {"staff_confirmed": true}. 반환 진행 중이면 409"""
        try:
            return svc.robot_home(payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})

    @app.get("/intake", include_in_schema=False)
    def intake_page():
        """등록기계 화면(태블릿). 관제탑과 같은 주소에서 열려 API 를 바로 부른다. 기계 번호는 주소 뒤 ?machine=KIOSK-A"""
        from fastapi.responses import HTMLResponse
        for path in INTAKE_PAGES:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    return HTMLResponse(f.read())
        raise HTTPException(status_code=404, detail="등록기계 화면 파일 없음")

    @app.get("/staff", include_in_schema=False)
    def staff_page():
        """직원 화면(본센터 방문 확인). 같은 주소에서 열려 API 를 바로 부른다"""
        from fastapi.responses import HTMLResponse
        with open(STAFF_PAGE, encoding="utf-8") as f:
            return HTMLResponse(f.read())

    # ---------- 실시간 화면 · 가상 시연 (11/4, docs/design/virtual_demo.md) ----------
    @app.get("/live", include_in_schema=False)
    def live_page():
        """실시간 화면: 보관함 탑뷰 그림·로봇팔 움직임·이야기별 진행·관제 메시지"""
        from fastapi.responses import HTMLResponse
        with open(LIVE_PAGE, encoding="utf-8") as f:
            return HTMLResponse(f.read())

    @app.get("/live/state")
    def live_state(after: int = 0, story: str | None = None) -> dict:
        """after 번 이후의 새 사건 + 가상 세계(가상 시연일 때) + 최근 이야기. 화면이 0.4초마다 부른다"""
        board = getattr(svc, "board", None)
        world = getattr(svc, "world", None)
        return {"seq": board.last_seq if board else 0, "events": board.since(after, story) if board else [],
                "stories": board.recent_stories() if board else [], "world": world.snapshot() if world else None,
                "sim": getattr(svc, "sim", None) is not None, "busy": svc.health()["busy"]}

    def _sim():
        d = getattr(svc, "sim", None)
        if d is None:
            raise HTTPException(status_code=404, detail="가상 시연이 꺼져 있습니다(.env TOWER_SIM=1 후 관제탑 다시 켜기)")
        return d

    def _text(payload) -> str:
        t = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(t, str) or not t.strip() or len(t) > 300:
            raise HTTPException(status_code=422, detail='본문 {"text": "메시지(300자 이하)"}')
        return t

    def _sim_call(fn, *a):
        try:
            return fn(*a)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/sim/found")
    def sim_found(payload: dict = Body(...)) -> dict:
        """가상 습득 신고: {"text": "서면역 5번 출구 앞에서 검정 카드지갑 주웠어요"} → 접수 번호·이야기 번호(나머지는 뒤에서 진행)"""
        return _sim_call(_sim().found, _text(payload))

    @app.post("/sim/lost")
    def sim_lost(payload: dict = Body(...)) -> dict:
        """가상 분실 신고: {"text": "검정 카드지갑 잃어버렸어요, 서면역"} → 찾기 번호 또는 확인 질문(pending_id)"""
        return _sim_call(_sim().lost, _text(payload))

    @app.post("/sim/lost/{pending_id}/answer")
    def sim_answer(pending_id: str, payload: dict = Body(...)) -> dict:
        """확인 질문 답: {"text": "VOVA"} (모르면 "모름")"""
        return _sim_call(_sim().answer, pending_id, _text(payload))

    @app.get("/sim/stories/{story_id}")
    def sim_story(story_id: str, after: int = 0) -> dict:
        """이야기 하나의 단계 상태 + after 이후 사건(분실물 봇이 진행판을 고칠 때 부름)"""
        board = getattr(svc, "board", None)
        st = board.story(story_id) if board else None
        if st is None:
            raise HTTPException(status_code=404, detail="없는 이야기 번호")
        return {**st, "events": board.since(after, story_id), "seq": board.last_seq}

    @app.post("/sim/reset")
    def sim_reset() -> dict:
        """가상 세계 초기화(보관함 시연 물건 4개·로봇 원점). 반환 진행 중이면 409"""
        d = _sim()
        if svc.health()["busy"]:
            raise HTTPException(status_code=409, detail={"kind": "busy", "message": "반환 진행 중 — 끝난 뒤 초기화"})
        return d.reset()

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
