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
- 등록기계 화면: GET /intake?machine=KIOSK-A(화면), GET /places, POST /items(사진 data URL 포함 가능), POST /items/{item_id}/features (안내 web/intake/README.md)
    TOWER_PHOTO_DIR  등록기계 사진 저장 폴더(기본 저장소/data → data/photos/기계/…, Git 에 안 올림)
- 직원 화면: POST /returns/{case_id}/handover — 바구니의 물건을 분실인에게 건넨 뒤 인계 완료로(11/4)
            POST /returns/{case_id}/hold — 건네지 않기로 함(이유 4개 중 하나) → 반환 보류
            POST /robot/stop (반환 진행 중에도) · POST /robot/home (주변 확인 뒤, 진행 중이면 409)
- 화면 3개: GET /kiosk?machine=KIOSK-A(습득자) · GET /lost(분실자 시안) · GET /staff(직원)
- 실시간 화면: GET /live (보관함·로봇팔·진행) · GET /live/state · 가상 시연 POST /sim/found · /sim/lost · /sim/reset
- AI 챗봇 위젯: POST /chat/questions · GET /chat/suggestions · /chat/health · /chat-widget/widget.js · /chat-widget/demo (agents/chat_api.py)
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

try:      # `from __future__ import annotations` 때문에 FastAPI 가 함수 안 import 를 못 찾는다 → Request·Response 는 모듈 맨 위에서
    from fastapi import Request, Response  # noqa: E402
except ImportError:           # fastapi 없이 import 만 할 때
    Request = Response = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 화면 = web/<이름>/index.html (11/5 정리, 화면 지도: web/README.md). 관제탑과 같은 주소에서 열려 API 를 바로 부른다
WEB_DIR = os.path.join(ROOT, "web")
PAGES = {"intake": "intake", "kiosk": "kiosk", "lost": "lost", "staff": "staff-desk", "live": "live", "admin": "admin",
         "storage": "storage-desk"}   # 주소 → 폴더
LIVE_PAGE = os.path.join(WEB_DIR, "live", "index.html")     # 실시간 화면(보관함·로봇팔·진행)


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
    storage = None
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
        from agents.storage import PostgresStorageStore      # 11/6 보관함 정답지(007 마이그레이션)
        storage = PostgresStorageStore(dsn)
    if not user_factory:
        backend_factory = _with_vision_file(backend_factory)
    from agents.gpu_lease import lease_from_env
    board = LiveBoard()      # 실시간 화면(/live)용 사건 기록 — 진짜 부품 모드에서도 같은 화면에 진행이 보인다
    svc = TowerService(backend_factory or demo_backend_factory(),
                       LiveReporter(Reporter(dry_run=not _flag("TOWER_SEND")), board),
                       recorder=recorder, reviewer=reviewer, claims=claims, intake=intake,
                       gpu_lease=lease_from_env(), storage=storage)
    svc.board = board
    from agents.tower_brain import build_from_env     # 11/8 관제탑 메인 AI(.env TOWER_BRAIN=1 일 때만)
    svc.brain = build_from_env(slot_lookup=svc.slot_area)
    return svc


def build_app(service: TowerService | None = None, chatbot=None, admin_auth=None):
    try:
        from fastapi import Body, Depends, FastAPI, HTTPException
    except ImportError as e:
        raise SystemExit("fastapi 가 없습니다. .venv 에서 `pip install -r agents/requirements.txt` 후 다시 실행하세요") from e
    from agents.admin_auth import COOKIE, AdminAuth
    from agents.tools import TOOLS

    svc = service or build_service()
    auth = admin_auth or AdminAuth.from_env()
    app = FastAPI(title="AI 분실물 관제탑 API", version="0.1")

    def require_admin(request: Request) -> None:
        """관리자 API 문지기: LF_ADMIN_PASSWORD 가 없으면 열림, 있으면 로그인 쿠키 또는 X-Admin-Key 필요"""
        if not auth.allowed(request.cookies.get(COOKIE, ""), request.headers.get("x-admin-key", "")):
            raise HTTPException(status_code=401, detail="관리자 로그인이 필요합니다")

    admin = [Depends(require_admin)]
    # 주소 체계(11/5): /api/kiosk/* · /api/lost/*(로그인 없음) · /api/admin/*(로그인) · /api/robot/stop(항상 열림).
    # 예전 주소(/places, /items, /returns …)도 같은 함수로 계속 동작한다(챗봇·분실물봇 호환). 관리자 쪽 예전 주소도 같은 문지기를 쓴다

    @app.get("/health")
    def health() -> dict:
        """살아 있는지, 부품이 진짜인지 가짜인지, 실행 중인지 (+ admin_auth: 관리자 로그인 켜짐 여부)"""
        return {**svc.health(), "admin_auth": auth.enabled}

    @app.post("/api/admin/login")
    def admin_login(request: Request, response: Response, payload: dict = Body(...)) -> dict:
        """관리자 로그인. 본문 {"password": "..."} → 쿠키 발급. 연속 5번 틀리면 1분 잠금"""
        if not auth.enabled:
            return {"ok": True, "auth": False}
        who = request.client.host if request.client else ""
        if auth.locked(who):
            raise HTTPException(status_code=429, detail="잠시 뒤에 다시 시도하세요")
        token = auth.login(str(payload.get("password", "")), who)
        if token is None:
            raise HTTPException(status_code=401, detail="비밀번호가 맞지 않습니다")
        response.set_cookie(COOKIE, token, max_age=auth.ttl, httponly=True, samesite="strict")
        return {"ok": True, "auth": True}

    @app.post("/api/admin/logout")
    def admin_logout(response: Response) -> dict:
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/admin/me")
    def admin_me(request: Request) -> dict:
        """화면이 로그인 상태를 확인: auth=로그인 기능 켜짐, logged_in=지금 접근 가능"""
        ok = auth.allowed(request.cookies.get(COOKIE, ""), request.headers.get("x-admin-key", ""))
        return {"auth": auth.enabled, "logged_in": ok}

    @app.get("/tools")
    def tools() -> list[dict]:
        """관제탑 도구 목록(담당·실패 규칙)"""
        return [{"name": t.name, "owner": t.owner, "summary": t.summary, "on_fail": t.on_fail} for t in TOOLS]

    @app.get("/places")
    @app.get("/api/kiosk/places")
    def places(machine_id: str, limit: int = 10) -> list[dict]:
        """등록기계 화면 2번: 이 기계 역의 추천 습득 장소(많이 고른 순). 목록에 없으면 화면에서 직접 입력"""
        try:
            return svc.list_places(machine_id, limit)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/items")
    @app.post("/api/kiosk/items")
    def create_item(payload: dict = Body(...)) -> dict:
        """등록기계 화면: 습득물 접수 → 접수 번호. 본문: machine_id, place_text(필수), place_id(추천 고른 경우),
        finder {name, phone}(둘 다 선택 — 비우면 저장 안 함), photo(선택, data:image/jpeg;base64,… 5MB 이하) 또는 photo_path.
        연락처는 응답에 나오지 않음"""
        try:
            rec = svc.create_item(payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        d = getattr(svc, "sim", None)       # 11/7 가상 시연: 진짜 키오스크 사진 접수 → Qwen 특징 대기 → 회수·보관 장면
        if d is not None and isinstance(payload, dict) and payload.get("photo"):
            d.kiosk_found(rec)
        return rec

    @app.post("/items/{item_id}/features", dependencies=admin)
    @app.post("/api/kiosk/items/{item_id}/features", dependencies=admin)
    def set_item_features(item_id: str, payload: dict = Body(...)) -> dict:
        # 11/8 무작위 시험: 로그인 없이 본센터 보관 물건의 특징(확인 질문 정답 포함)을 덮어쓸 수 있었다 →
        # 관리자 잠금이 켜져 있으면 관리자 키(Qwen 작업자 LF_ADMIN_API_KEY) 필요, 이미 특징이 있으면 409
        """뒤에서 도는 Qwen 작업(김건태 LF-3): {"qwen": general_items_v1 특징, "confidence": 0~1} → 물건 특징 저장"""
        try:
            out = svc.set_item_features(item_id, payload)
            d = getattr(svc, "sim", None)   # 11/7 가상 시연: Qwen 원본을 기억(가상 탑뷰가 같은 물건을 다시 찍을 때) + 기다리던 이야기 진행
            if d is not None:
                d.on_features(item_id, payload.get("qwen"))
            return out
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/api/admin/intake/pending-photos", dependencies=admin)
    def pending_photos(limit: int = 10) -> list[dict]:
        """11/7 사진 분석 대기 물건 — 관제탑 PC 의 Qwen 작업자(tools/intake_qwen_worker.py)가 가져가 특징을 채운다"""
        try:
            return svc.pending_photos(limit)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/claims")
    @app.post("/api/kiosk/claims")
    @app.post("/api/lost/claims")
    def create_claim(request: Request, payload: dict = Body(...)) -> dict:
        """웹(1단계): 찾기 요청 저장. 본문: consent, name_masked, id_no_masked(가린 값), id_verified, description,
        item_id(고른 후보), quiz[{field, passed}], visit_date (+ lost_line·lost_station·lost_date). 결과: claim_id·웹 관문
        11/8 무작위 시험: 로그인 없는 요청이 id_verified·quiz passed=true 를 스스로 보내 키오스크 반환까지 갔다 →
        관리자 잠금이 켜져 있으면, 직원 로그인·관리자 키가 있는 요청(직원 화면·웹 서버)만 그 값을 믿고 나머지는 '미확인'으로 저장"""
        trusted = auth.allowed(request.cookies.get(COOKIE, ""), request.headers.get("x-admin-key", ""))
        try:
            return svc.create_claim(payload, trusted=trusted)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/claims/{claim_id}", dependencies=admin)
    @app.get("/api/admin/claims/{claim_id}", dependencies=admin)
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

    @app.post("/returns", dependencies=admin)
    @app.post("/api/admin/returns", dependencies=admin)
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

    @app.post("/api/kiosk/returns")
    def kiosk_return(payload: dict = Body(...)) -> dict:
        """본센터 키오스크 회수(로그인 없음, 11/6). 본문 {machine_id: "CENTER", claim_id, id_no_masked}. 관문 값은 서버가 정한다.
        신분 번호를 3번 틀리면 잠금(409 kind=locked). 정지 버튼(/api/robot/stop)은 반환 중에도 항상 열려 있다"""
        try:
            d = getattr(svc, "sim", None)       # 11/7 가상 시연: 웹 신고 이야기에 키오스크 회수 단계를 이어 붙임
            return d.kiosk_return(payload) if d is not None else svc.kiosk_return(payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/returns/{case_id}/handover", dependencies=admin)
    @app.post("/api/admin/returns/{case_id}/handover", dependencies=admin)
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

    @app.post("/returns/{case_id}/hold", dependencies=admin)
    @app.post("/api/admin/returns/{case_id}/hold", dependencies=admin)
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

    # ---------- 11/6 인계 교차 검증(docs/design/handover_cross_check.md) ----------
    def _case(call):
        try:
            return call()
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/api/admin/storage/arrivals", dependencies=admin)
    def storage_arrivals(limit: int = 50) -> list:
        """본센터 도착 처리: 칸이 정해지지 않은 물건과 추천 칸(11/6)"""
        return _case(lambda: svc.storage_arrivals(max(1, min(int(limit), 200))))

    @app.post("/api/admin/storage/arrivals/{item_id}/place", dependencies=admin)
    def storage_place(item_id: str, payload: dict = Body(...)) -> dict:
        """직원이 칸에 넣었음 → 본센터 보관 + 칸 기록. 본문 {"slot_id": "R4-1", "override_category": false}"""
        return _case(lambda: svc.place_item(item_id, payload))

    @app.get("/api/admin/storage/status", dependencies=admin)
    def storage_status() -> dict:
        """11/9 보관함 꽉 참 현황: 묶음별 사용(휴대폰 x/2 · 그 밖 y/6)·칸 대기·직원 보관 선반·선반으로 옮기기 제안"""
        return _case(svc.storage_status)

    @app.post("/api/admin/storage/shelf", dependencies=admin)
    def storage_shelf(payload: dict = Body(...)) -> dict:
        """직원 보관 선반으로 옮김(보관 칸 물건 또는 칸 대기 물건). 본문 {"item_id": "..."} — 로봇은 선반 물건을 집지 않음"""
        return _case(lambda: svc.move_to_shelf(payload))

    @app.get("/api/admin/handovers", dependencies=admin)
    def handover_queue(limit: int = 20) -> list:
        """제출보관함에서 직원 확인을 기다리는 반환(인계 대기) 목록"""
        return _case(lambda: svc.handover_queue(max(1, min(int(limit), 100))))

    @app.get("/api/admin/returns/{case_id}/secret", dependencies=admin)
    def handover_secret(case_id: str) -> dict:
        """비공개 특징(정답) — 분실인 설명을 먼저 들은 뒤 '답 보기'로만 연다. 인계 대기 중에만"""
        return _case(lambda: svc.handover_secret(case_id))

    @app.post("/api/admin/returns/{case_id}/verify", dependencies=admin)
    def verify_handover(case_id: str, payload: dict = Body(...)) -> dict:
        """교차 검증 결과. 본문 {"item_match": true, "id_match": true, "feature_match": true} — 셋 다 맞으면 인계 완료, 아니면 반환 보류"""
        out = _case(lambda: svc.verify_handover(case_id, payload))
        d = getattr(svc, "sim", None)       # 11/7 가상 시연: 분실인 웹 진행 상황의 '인계 완료' 갱신
        if d is not None:
            try:
                d.on_verify(case_id, out)
            except Exception:
                pass
        return out

    @app.post("/api/admin/returns/{case_id}/restock", dependencies=admin)
    def restock(case_id: str, payload: dict = Body(...)) -> dict:
        """반환 보류 물건을 원래 칸에 넣은 뒤 → 본센터 보관. 본문 {"staff_confirmed": true}"""
        return _case(lambda: svc.restock(case_id, payload))

    @app.get("/api/admin/items/{item_id}/photo", dependencies=admin)
    def item_photo(item_id: str):
        """등록 사진(직원이 실물과 비교). 없으면 404"""
        from agents.intake import valid_item_id
        from fastapi.responses import FileResponse
        if not valid_item_id(item_id):
            raise HTTPException(status_code=422, detail="item_id 형식")
        path = svc.item_photo(item_id)
        if path is None:
            raise HTTPException(status_code=404, detail="등록 사진 없음")
        return FileResponse(str(path), headers={"Cache-Control": "no-store"})

    @app.get("/robot/state", dependencies=admin)
    @app.get("/api/admin/robot/state", dependencies=admin)
    def robot_state() -> dict:
        """로봇 상태(단계·정지·들고 있는 물건·관절 6개). 계약 docs/contracts/robot_api.md (11/5)"""
        return svc.robot_state()

    @app.post("/robot/stop")
    @app.post("/api/robot/stop")
    def robot_stop() -> dict:
        """직원 화면 🛑 정지: 반환 진행 중에도 동작. 다음 로봇 동작을 막고 즉시 정지(원점 복귀 안 함). 안전 원칙상 로그인 없이 항상 열림"""
        return svc.stop_robot()

    @app.post("/robot/home", dependencies=admin)
    @app.post("/api/admin/robot/home", dependencies=admin)
    def robot_home(payload: dict = Body(...)) -> dict:
        """직원 화면 원점 복귀: 주변 확인 뒤에만. 본문 {"staff_confirmed": true}. 반환 진행 중이면 409"""
        try:
            return svc.robot_home(payload)
        except RequestError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Conflict as e:
            raise HTTPException(status_code=409, detail={"kind": e.kind, "message": str(e)})

    # ---------- 11/6 보관함 정답지(agents/storage.py, docs/design/storage_slots.md) ----------
    def _storage(call):
        from agents.storage import StorageConflict, StorageError
        try:
            return call()
        except HTTPException:
            raise
        except StorageError as e:
            raise HTTPException(status_code=404 if e.not_found else 422, detail=str(e))
        except StorageConflict as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:                   # DB 꺼짐 등(주소·비밀번호는 담지 않음)
            raise HTTPException(status_code=503, detail=f"보관함 DB 사용 불가({type(e).__name__})")

    def _body(payload) -> dict:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="JSON 객체여야 합니다")
        return payload

    @app.get("/api/admin/storage", dependencies=admin)
    def storage_layout() -> dict:
        """보관함 4행×2칸 + 인계 구역: 칸마다 저장 자세와 들어 있는 물건(물건 번호·상태·품목만)"""
        return _storage(svc.storage.layout)

    @app.get("/api/admin/storage/export", dependencies=admin)
    def storage_export() -> dict:
        """비전 run_storage_check.py --storage 형식 JSON(sections·inventory) + warnings"""
        return _storage(svc.storage.export)

    @app.post("/api/admin/storage/assign", dependencies=admin)
    def storage_assign(payload: dict = Body(...)) -> dict:
        """물건을 칸에 넣음. 본문 {"item_id": "A-W01", "slot_id": "R4-1", "override_category": false}. 다른 물건이 있으면 409"""
        p = _body(payload)
        return _storage(lambda: svc.storage.assign(p.get("item_id"), p.get("slot_id"),
                                                   override_category=p.get("override_category") is True))

    @app.post("/api/admin/storage/release", dependencies=admin)
    def storage_release(payload: dict = Body(...)) -> dict:
        """칸 비우기. 본문 {"item_id": ...} 또는 {"slot_id": ...} 중 하나"""
        p = _body(payload)
        return _storage(lambda: svc.storage.release(item_id=p.get("item_id"), slot_id=p.get("slot_id")))

    @app.post("/api/admin/storage/slots/{slot_id}/pose", dependencies=admin)
    def storage_set_pose(slot_id: str, payload: dict = Body(...)) -> dict:
        """로봇 티칭으로 정한 저장 자세 이름을 칸에 연결. 본문 {"pose_name": "pose_1"} (null = 지움)"""
        p = _body(payload)
        return _storage(lambda: svc.storage.set_pose(slot_id, p.get("pose_name")))

    @app.post("/api/admin/storage/checks", dependencies=admin)
    def storage_record_check(payload: dict = Body(...)) -> dict:
        """탑뷰 개수 확인 결과 기록. 본문 {"section": "R1", "expected_count": 2, "detected_count": 2, "status": "count_match"}"""
        return _storage(lambda: svc.storage.record_check(_body(payload)))

    @app.get("/api/admin/storage/checks", dependencies=admin)
    def storage_checks(limit: int = 20) -> list:
        """최근 개수 확인 기록(최신 순, 최대 100개)"""
        return _storage(lambda: svc.storage.recent_checks(limit))

    def _page(name: str):
        from fastapi.responses import HTMLResponse
        path = os.path.join(WEB_DIR, PAGES[name], "index.html")
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail=f"화면 파일 없음: web/{PAGES[name]}/index.html")
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(f.read())

    @app.get("/ui/{name}", include_in_schema=False)
    def ui_asset(name: str):
        """11/8 디자인 개편 공통 파일(web/ui/theme.css·theme.js) — 모든 화면이 같은 색·부품·라이트/다크 전환을 쓴다"""
        from fastapi.responses import FileResponse
        types = {"theme.css": "text/css", "theme.js": "application/javascript"}
        if name not in types:
            raise HTTPException(status_code=404, detail="없는 파일")
        return FileResponse(os.path.join(WEB_DIR, "ui", name), media_type=types[name], headers={"Cache-Control": "no-cache"})

    @app.get("/ui/fonts/{name}", include_in_schema=False)
    def ui_font(name: str):
        """11/8 글꼴 직접 제공(교육원에 인터넷이 없어도 모든 화면이 같은 글꼴). 정해진 파일 이름만"""
        from fastapi.responses import FileResponse
        types = {"PretendardVariable.woff2": "font/woff2", "Pretendard-LICENSE.txt": "text/plain; charset=utf-8"}
        if name not in types:
            raise HTTPException(status_code=404, detail="없는 파일")
        return FileResponse(os.path.join(WEB_DIR, "ui", "fonts", name), media_type=types[name],
                            headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/", include_in_schema=False)
    def home_page():
        """11/7 첫 화면: 주소만 입력했을 때 Not Found 대신 화면 목록(발표 순서). 데이터는 보여 주지 않는다"""
        from fastapi.responses import HTMLResponse
        links = [("① 해운대역 키오스크 — 습득 신고", "/kiosk?machine=KIOSK-A"), ("② 분실인 웹 — 잃어버린 물건 찾기·AI 챗봇", "/lost"),
                 ("③ 부산역 본센터 키오스크 — 회수", "/kiosk?machine=CENTER"), ("④ 관리자 관제(로봇·진행 상황)", "/admin"),
                 ("⑤ 본센터 직원 화면 — 교차 검증", "/staff"), ("⑥ 보관함 칸 관리", "/storage"),
                 ("실시간 작업대(큰 화면)", "/live"), ("서면역 키오스크", "/kiosk?machine=KIOSK-C")]
        items = "".join(f'<li><a href="{href}"><span>{label}</span><code>{href}</code></a></li>' for label, href in links)
        return HTMLResponse(
            '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<title>AI 분실물 관제탑</title><link rel="stylesheet" href="/ui/theme.css"><script src="/ui/theme.js"></script>'
            '<style>body{margin:0}main{max-width:640px;margin:0 auto;padding:48px max(16px,env(safe-area-inset-right,0px)) 96px max(16px,env(safe-area-inset-left,0px))}'
            'header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:24px}'
            '.ui-card{padding:8px 20px}.ui-list a{display:flex;flex-direction:column;gap:4px;width:100%;color:var(--ui-text);text-decoration:none;font-size:17px;font-weight:600}'
            '.ui-list a:hover span{color:var(--ui-primary)}.ui-list code{font:500 13px var(--ui-mono);color:var(--ui-text-3)}</style></head><body><main>'
            '<header><div><h1 class="ui-title">AI 분실물 관제탑</h1><p class="ui-sub">보여 줄 화면을 고르세요(발표 순서). 관리자 화면은 로그인이 켜져 있으면 비밀번호가 필요합니다.</p></div>'
            '<div data-theme-slot></div></header>'
            f'<div class="ui-card"><ul class="ui-list">{items}</ul></div></main></body></html>')

    @app.get("/intake", include_in_schema=False)
    def intake_page():
        """등록기계(습득 신고) 화면 — web/intake/ (김재민). 기계 번호는 주소 뒤 ?machine=KIOSK-A"""
        return _page("intake")

    @app.get("/kiosk", include_in_schema=False)
    def kiosk_page():
        """키오스크 화면 — web/kiosk/ (김재민). 습득 신고 + 분실 확인 + 본센터 회수로 넓힐 화면. ?machine=KIOSK-A"""
        return _page("kiosk")

    @app.get("/lost", include_in_schema=False)
    def lost_page():
        """분실인 웹(분실 확인) — web/lost/ (김재민, 서버 연결 전 시안)"""
        return _page("lost")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        """관리자 관제 — web/admin/ (로그인 화면 + 관제 모니터링·직원 화면을 탭으로). 화면 자체는 열려 있고 데이터 API 가 잠긴다"""
        return _page("admin")

    @app.get("/storage-desk", include_in_schema=False)
    @app.get("/storage", include_in_schema=False)      # 11/7 짧은 주소(PAGES 이름과 같게)
    def storage_desk_page():
        """본센터 보관 화면(11/6): 도착한 물건을 칸에 넣고 기록 — web/storage-desk/. 관리자 화면 '보관함' 탭"""
        return _page("storage")

    @app.get("/staff", include_in_schema=False)
    def staff_page():
        """직원 화면 — web/staff-desk/ (11/5 결정: 직원은 일단 제외, 화면은 남겨 둠)"""
        return _page("staff")

    # ---------- 실시간 화면 · 가상 시연 (11/4, docs/design/virtual_demo.md) ----------
    @app.get("/live", include_in_schema=False)
    def live_page():
        """관제 모니터링 — web/live/ (화면 김재민, 데이터 /live/state 변재원): 보관함·로봇팔·이야기별 진행·관제 메시지"""
        return _page("live")

    @app.get("/live/so101_shape.js", include_in_schema=False)
    def live_so101_shape():
        """SO-101 실제 형상 점 자료(tools/so101_shape.py 가 공식 모델에서 만듦) — 화면이 로봇팔을 그릴 때 읽음"""
        from fastapi.responses import Response
        with open(os.path.join(os.path.dirname(LIVE_PAGE), "so101_shape.js"), encoding="utf-8") as f:
            return Response(f.read(), media_type="application/javascript")

    @app.get("/live/state", dependencies=admin)
    @app.get("/api/admin/live/state", dependencies=admin)
    def live_state(after: int = 0, story: str | None = None) -> dict:
        """after 번 이후의 새 사건 + 가상 세계(가상 시연일 때) + 최근 이야기. 화면이 0.4초마다 부른다"""
        board = getattr(svc, "board", None)
        world = getattr(svc, "world", None)
        return {"seq": board.last_seq if board else 0, "events": board.since(after, story) if board else [],
                "stories": board.recent_stories() if board else [], "world": world.snapshot() if world else None,
                "sim": getattr(svc, "sim", None) is not None, "busy": svc.health()["busy"], "storage": _storage_brief()}

    _brief = {"t": 0.0, "v": None}

    def _storage_brief():
        """11/9 /live 칸 사용 현황(휴대폰 x/2 · 그 밖 y/6 · 대기 n · 선반). 0.4초마다 불리므로 1.5초 동안은 지난 값(팀 DB 부담 줄임)"""
        import time as _t
        now = _t.monotonic()
        if _brief["v"] is None or now - _brief["t"] > 1.5:
            try:
                st = svc.storage_status()
                _brief["v"] = {k: st[k] for k in ("groups", "waiting", "shelf", "message", "summary", "suggest")}
            except Exception:
                _brief["v"] = None
            _brief["t"] = now
        return _brief["v"]

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
        """가상 분실 신고: {"text": "검정 카드지갑 잃어버렸어요, 서면역"} → 찾기 번호 또는 확인 질문(pending_id)
        11/7 분실인 웹: + {"visit": "kiosk", "name_masked": "변*원", "id_no_masked": "******-3******"} 이면
        방문을 자동으로 하지 않고 본센터 키오스크 회수 탭(찾기 번호 + 같은 신분 번호)을 기다린다"""
        opts = {}
        if isinstance(payload, dict) and payload.get("visit") == "kiosk":
            opts["visit"] = "kiosk"
            for k in ("name_masked", "id_no_masked"):
                v = payload.get(k)
                if v is not None:
                    if not isinstance(v, str) or "*" not in v or not 1 <= len(v) <= 32:
                        raise HTTPException(status_code=422, detail=f"{k}: 가린 값만(예: 변*원, ******-3******)")
                    opts[k] = v
        return _sim_call(_sim().lost, _text(payload), opts)

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
            raise HTTPException(status_code=404, detail="없는 처리 번호")
        return {**st, "events": board.since(after, story_id), "seq": board.last_seq}

    @app.post("/sim/reset", dependencies=admin)     # 11/8 무작위 시험: 로그인 없이 시연 전체를 지울 수 있었다
    def sim_reset() -> dict:
        """가상 세계 초기화(보관함 시연 물건 5개·로봇 원점). 반환 진행 중이면 409. 관리자 잠금이 켜져 있으면 로그인 필요"""
        d = _sim()
        if svc.health()["busy"]:
            raise HTTPException(status_code=409, detail={"kind": "busy", "message": "반환 진행 중 — 끝난 뒤 초기화"})
        return d.reset()

    @app.get("/returns", dependencies=admin)
    @app.get("/api/admin/returns", dependencies=admin)
    def recent(limit: int = 20) -> list[dict]:
        """최근 반환 기록(단계 제외)"""
        try:
            return svc.recent(limit)
        except Unavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/returns/{case_id}", dependencies=admin)
    @app.get("/api/admin/returns/{case_id}", dependencies=admin)
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

    # ---------- AI 챗봇 위젯 (LF-5, 11/5) — /chat/*, /chat-widget/* (agents/chat_api.py) ----------
    from agents.chat_api import add_chat_routes

    def staff_allowed(request: Request) -> bool:      # 11/6 직원 관제 질문: 관리자 API 와 같은 문지기
        return auth.allowed(request.cookies.get(COOKIE, ""), request.headers.get("x-admin-key", ""))

    def ops_source() -> dict:                          # 관제 분석 에이전트 조사자: /returns·/live/state 와 같은 자료를 안에서 바로
        return {"returns": svc.recent(100), "live": live_state(0, None)}

    if chatbot is None and getattr(svc, "sim", None) is not None and os.environ.get("TOWER_CHAT_SIM_SEARCH", "1") != "0":
        # 11/7 가상 시연: 챗봇 물건 검색이 화면 작업대와 같은 가상 물건 목록을 보게(연습용 별도 목록과 어긋나던 허점)
        from agents.chat_api import LazyChatbot, build_chatbot_from_env
        from agents.chat_search import SimTowerItemSearch
        chatbot = LazyChatbot(lambda: build_chatbot_from_env(SimTowerItemSearch(svc.world.chat_items)))
    add_chat_routes(app, chatbot, staff_allowed=staff_allowed, ops_source=ops_source)
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
