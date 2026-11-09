"""AI 챗봇 위젯용 API — 관제탑(8100)에 붙는 챗봇 입구 (LF-5, 11/5)

한줄 설명: 화면 어디에든 `<script src="/chat-widget/widget.js">` 한 줄로 붙는 채팅 창이 부르는 주소들을 관제탑에 더한다.
챗봇 두뇌는 정연우 LF-5 의 `agents/chatbot.py`(LangGraph: 이용 안내 RAG + 물건 검색 에이전트)를 그대로 쓴다.

주소
    POST /chat/questions      {"question": "...", "history": ["이전 질문", ...최대 4개], "mode": "staff"(직원 화면만)} → 답변·근거·후보 카드
                              11/8 "stream": true(또는 Accept: application/x-ndjson)면 NDJSON 단계 줄 {"stage","pct"} … 마지막 {"done": true, ...같은 응답}
    GET  /chat/suggestions    추천 질문 목록
    GET  /chat/health         챗봇 준비 상태(문서 RAG 모델·검색 모드)
    GET  /chat/metrics        챗봇 운영 지표(LLMOps): 건수·응답 시간 p50/p95·결과 비율 — 질문 원문은 저장 안 함(agents/chat_metrics.py)
    GET  /chat-widget/widget.js   채팅 위젯 스크립트(web/chat-widget/widget.js)
    GET  /chat-widget/demo        위젯 시험 페이지(web/chat-widget/index.html)

환경값(.env, 없으면 기본)
    LF_CHAT_RAG_MODEL     문서 답변을 다듬을 로컬 Ollama 모델 이름. 없으면 문서 문단을 그대로 안내
    LF_CHAT_DATABASE_URL  실제 팀 DB 조회(본인인증 세션 검증기가 연결돼야 열림 — 지금은 연결 전)
    TOWER_CHAT_DEMO_DB    가상 물건 DB(SQLite) 파일. 기본 저장소/.cache/chat-demo.sqlite3, "0" 이면 물건 검색 끔

- 챗봇 부품(langgraph 등)은 첫 질문 때 만든다. 설치가 안 돼 있어도 관제탑은 켜지고, 챗봇 주소만 503 으로 알린다
- 질문 원문은 저장하지 않는다(추천 질문 선택 횟수만 셈). 인증 토큰은 Authorization: Bearer 로만 받는다

직원 관제 질문(11/6, A안)
- 관리자 화면 위젯(data-mode="staff")은 본문에 "mode": "staff" 를 붙인다. 관제탑이 관리자 로그인(쿠키·X-Admin-Key)을 확인한 뒤에만
  챗봇에 staff=True 를 넘기고, 로그인이 안 됐으면 401. 분실인 화면(/lost)·키오스크는 mode 를 보내지 않으므로 관제 길이 열리지 않는다
- 관제 질문은 LangManus 구조 관제 분석 에이전트(agents/ops_analyst.py)가 답한다. 관제 기록은 HTTP 를 다시 부르지 않고
  관제탑 안에서 바로 읽는다(ops_source). 보고 문장 모델은 OPS_ANALYST_MODEL, 없으면 LF_CHAT_RAG_MODEL
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

try:      # `from __future__ import annotations` 때문에 FastAPI 가 함수 안 import 를 못 찾는다 → Request 는 모듈 맨 위에서(agents/api.py 와 같음)
    from fastapi import Request
except ImportError:      # fastapi 가 없어도 관제탑 시험(가짜 fastapi)은 돈다
    Request = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIDGET_DIR = os.path.join(ROOT, "web", "chat-widget")
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
STREAM_WAIT_S = 90      # 스트림에서 다음 단계 알림을 기다리는 최대 시간(위젯은 30초·직원 60초에서 먼저 멈춤)


def wants_stream(body, request) -> bool:
    """11/8 진행률: 본문 "stream": true 또는 Accept: application/x-ndjson 일 때만 단계별 스트림. 그 밖은 기존처럼 한 번에"""
    if isinstance(body, dict) and body.get("stream") is True:
        return True
    try:
        accept = (request.headers.get("accept") or "") if request is not None else ""
    except AttributeError:
        accept = ""
    return "application/x-ndjson" in accept


def build_chatbot_from_env(database=None, desk=None):
    """환경값으로 챗봇을 만든다. 실제 DB 설정이 있으면 가상 DB 로 바꿔 대신하지 않는다(정연우 원칙 유지).
    database 를 주면 그 검색 부품을 쓴다(11/7 가상 시연: 관제탑 가상 물건 목록 SimTowerItemSearch).
    desk(11/9): 대화 접수 창구(가상 시연 SimDirector). 없으면 챗봇이 빈칸을 정리한 뒤 키오스크·웹으로 안내"""
    from agents.chat_rag import GroundedRag
    from agents.chat_search import DemoItemDatabase, PostgresItemSearch, SearchAgent
    from agents.chatbot import Chatbot
    from agents.guidance import Guidance
    guide = Guidance()
    if database is not None:
        pass
    elif os.environ.get("LF_CHAT_DATABASE_URL"):
        database = PostgresItemSearch(os.environ["LF_CHAT_DATABASE_URL"])
    else:
        demo = (os.environ.get("TOWER_CHAT_DEMO_DB") or "").strip()
        if demo != "0":
            database = DemoItemDatabase(demo or os.path.join(ROOT, ".cache", "chat-demo.sqlite3"))
    model = os.environ.get("LF_CHAT_RAG_MODEL") or None
    rag = GroundedRag(guide, model=model)
    brain = None
    if model and (os.environ.get("LF_CHAT_AGENT_ROUTING") or "1").strip() != "0":
        # 11/7 DeerFlow 구조: coordinator·planner 도 모델이 판단(LF_CHAT_AGENT_MODEL 로 다른 모델 지정 가능, 0 이면 규칙)
        from agents.chat_agents import AgentBrain
        brain = AgentBrain(os.environ.get("LF_CHAT_AGENT_MODEL") or model)
    from agents.chat_intake import IntakeAgent
    return Chatbot(guide, rag=rag, search=SearchAgent(database), brain=brain, intake=IntakeAgent(desk=desk, brain=brain))


class LazyChatbot:
    """첫 요청 때 한 번만 챗봇을 만든다. 실패 이유는 기억해 두고 503 으로 알린다(다음 요청 때 다시 시도)."""

    def __init__(self, factory=build_chatbot_from_env):
        self._factory = factory
        self._bot = None
        self._lock = threading.Lock()
        self.error: str | None = None

    def get(self):
        if self._bot is None:
            with self._lock:
                if self._bot is None:
                    try:
                        self._bot = self._factory()
                        self.error = None
                    except Exception:     # Never retain/return model or DB error text.
                        self.error = "챗봇을 준비하지 못했습니다. 관제탑 PC의 설치·설정을 확인하세요"
                        raise RuntimeError(self.error) from None
        return self._bot


class _OpsReader:
    """관제 분석 에이전트의 조사자(researcher)가 읽는 자료: 관제탑 기록(ops_source) + 챗봇 운영 지표. 읽기만 한다."""

    def __init__(self, source, metrics):
        self._source, self._metrics = source, metrics

    def collect(self) -> dict:
        data = dict(self._source())
        try:
            data["chat"] = self._metrics.snapshot()
        except Exception:
            data["chat"] = None
        return data


def build_ops_agent(source, metrics):
    from agents.ops_analyst import OpsAnalyst
    model = os.environ.get("OPS_ANALYST_MODEL") or os.environ.get("LF_CHAT_RAG_MODEL") or None
    return OpsAnalyst(reader=_OpsReader(source, metrics), model=model)


def add_chat_routes(app, chatbot=None, staff_allowed=None, ops_source=None, ops_factory=build_ops_agent) -> None:
    """관제탑 앱(agents/api.py build_app)에 챗봇·위젯 주소를 더한다. chatbot 은 시험용으로 바꿔 끼울 수 있다.
    staff_allowed(request) → 관리자 로그인 여부, ops_source() → {"returns": [...], "live": {...}}. 둘 다 있어야 직원 관제 길이 열린다."""
    from fastapi import Body, Header, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse

    from agents.chat_metrics import ChatMetrics

    holder = chatbot if isinstance(chatbot, LazyChatbot) else LazyChatbot(lambda: chatbot) if chatbot else LazyChatbot()
    metrics = ChatMetrics()
    try:
        app.state.chat_metrics = metrics      # 시험에서 꺼내 볼 수 있게(가짜 앱에는 state 가 없음)
    except AttributeError:
        pass

    staff_ready = staff_allowed is not None and ops_source is not None
    ops_lock = threading.Lock()

    def bot():
        try:
            b = holder.get()
        except RuntimeError:
            raise HTTPException(status_code=503, detail="챗봇 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요") from None
        if staff_ready and getattr(b, "ops", "absent") is None:     # 직원 관제 에이전트는 처음 한 번만 붙인다
            with ops_lock:
                if b.ops is None:
                    try:
                        b.ops = ops_factory(ops_source, metrics)
                    except Exception:      # 붙이지 못해도 분실인 안내·검색은 그대로
                        pass
        return b

    def stream_answer(call, body, b, t0):
        """11/8 진행률: 단계마다 한 줄짜리 JSON(NDJSON)을 흘려보내고, 마지막 줄은 {"done": true, ...기존 응답}.
        챗봇은 따로 실행 줄(thread)에서 돌고, agents/chat_progress 알림을 줄 큐로 받아 내보낸다. 오류도 마지막 줄로 알린다."""
        import contextvars
        import queue

        from fastapi.responses import StreamingResponse

        from agents.chat_progress import STAGES, listening

        events: queue.Queue = queue.Queue()

        def worker():
            with listening(lambda stage: events.put(("stage", stage))):
                try:
                    events.put(("done", call()))
                except ValueError as e:
                    events.put(("error", 422, str(e), "rejected"))
                except RuntimeError:
                    events.put(("error", 503, "챗봇 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요", "error"))
                except Exception:      # 내부 오류 문구는 화면에 내보내지 않는다
                    events.put(("error", 500, "챗봇 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요", "error"))

        ctx = contextvars.copy_context()      # 접속 토큰 등 요청별 값(contextvar)을 그대로 넘긴다
        threading.Thread(target=ctx.run, args=(worker,), daemon=True, name="chat-stream").start()

        def line(obj) -> bytes:
            return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

        def lines():
            best = STAGES["received"]
            yield line({"stage": "received", "pct": best})
            while True:
                try:
                    item = events.get(timeout=STREAM_WAIT_S)
                except queue.Empty:
                    metrics.record("question", (time.perf_counter() - t0) * 1000, "error")
                    yield line({"done": True, "error": True, "status_code": 504, "detail": "응답 시간이 길어 요청을 멈췄어요. 잠시 후 다시 시도해 주세요."})
                    return
                if item[0] == "stage":
                    pct = STAGES.get(item[1])
                    if pct is not None and pct > best:      # 퍼센트는 줄어들지 않는다(다시 쓰기 등으로 앞 단계 알림이 늦게 와도)
                        best = pct
                        yield line({"stage": item[1], "pct": pct})
                elif item[0] == "done":
                    result = item[1]
                    metrics.record("question", (time.perf_counter() - t0) * 1000, "ok", result)
                    b.guidance.record_suggestion(body.get("suggestion_id"), body.get("question"))
                    yield line({"done": True, **result})
                    return
                else:
                    _, code, detail, outcome = item
                    metrics.record("question", (time.perf_counter() - t0) * 1000, outcome)
                    yield line({"done": True, "error": True, "status_code": code, "detail": detail})
                    return

        return StreamingResponse(lines(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/chat/questions")
    def chat_question(body: dict = Body(...), authorization: str | None = Header(default=None), request: Request = None) -> dict:
        """AI 챗봇 질문. 본문 {question, history?(이전 질문 또는 {q,a} 최대 4개), suggestion_id?, search_context?, mode?("staff": 관리자 화면),
        session_id?(같은 화면 대화 묶음 번호, 영문·숫자·-_ 8~64자)}"""
        t0 = time.perf_counter()
        mode = body.get("mode") if isinstance(body, dict) else None
        staff = False
        if mode == "staff":
            if not staff_ready:
                raise HTTPException(status_code=404, detail="직원 관제 질문은 관제탑에서만 쓸 수 있습니다")
            if not staff_allowed(request):
                metrics.record("question", (time.perf_counter() - t0) * 1000, "rejected")
                raise HTTPException(status_code=401, detail="관리자 로그인이 필요합니다")
            staff = True
        elif mode not in (None, "", "web", "kiosk"):
            raise HTTPException(status_code=422, detail="mode 는 web·kiosk·staff 중 하나")
        try:
            b = bot()
        except HTTPException:
            metrics.record("question", (time.perf_counter() - t0) * 1000, "error")
            raise
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
        # 11/7 Langfuse: 같은 화면 대화를 묶는 번호(화면이 만든 무작위 값). 형식이 다르면 버림(개인정보·긴 값이 기록에 섞이지 않게)
        sid = body.get("session_id") if isinstance(body.get("session_id"), str) and SESSION_RE.match(body.get("session_id")) else None
        extra = {}
        try:
            import inspect
            params = inspect.signature(b.ask).parameters
            if "session_id" in params:
                extra = {"session_id": sid, "channel": "staff" if staff else (mode or "web")}
            if body.get("intake_action") is not None:      # 11/9 위젯 본인 확인 양식(가린 값만) — 모양이 다르면 422
                from agents.chat_intake import check_action
                try:
                    action = check_action(body.get("intake_action"))
                except ValueError as e:
                    metrics.record("question", (time.perf_counter() - t0) * 1000, "rejected")
                    raise HTTPException(status_code=422, detail=str(e)) from None
                if "intake_action" in params and not staff:
                    extra["intake_action"] = action
        except (TypeError, ValueError):
            extra = {}
        def call():
            if staff:
                return b.ask(body.get("question"), token, body.get("search_context"), body.get("history"), staff=True, **extra)
            return b.ask(body.get("question"), token, body.get("search_context"), body.get("history"), **extra)

        if wants_stream(body, request):
            return stream_answer(call, body, b, t0)
        try:
            result = call()
        except ValueError as e:
            metrics.record("question", (time.perf_counter() - t0) * 1000, "rejected")
            raise HTTPException(status_code=422, detail=str(e)) from None
        except RuntimeError:
            metrics.record("question", (time.perf_counter() - t0) * 1000, "error")
            raise HTTPException(status_code=503, detail="챗봇 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요") from None
        metrics.record("question", (time.perf_counter() - t0) * 1000, "ok", result)
        b.guidance.record_suggestion(body.get("suggestion_id"), body.get("question"))
        return result

    @app.get("/chat/metrics")
    def chat_metrics() -> dict:
        """챗봇 운영 지표(LLMOps) — 질문 원문 없이 건수·응답 시간·결과 비율만"""
        snap = metrics.snapshot()
        try:
            b = holder._bot
            snap["config"] = {"rag_model": getattr(getattr(b, "rag", None), "model", None) if b else None,
                              "search_mode": b.search.mode if b else None}
        except Exception:
            snap["config"] = {}
        return snap

    @app.get("/chat/suggestions")
    def chat_suggestions() -> dict:
        """추천 질문(많이 고른 순)"""
        return bot().guidance.suggestions()

    @app.get("/chat/health")
    def chat_health() -> dict:
        """챗봇 준비 상태. ready=false 면 error 에 이유(관제탑 PC 설치 확인)"""
        try:
            b = holder.get()
        except RuntimeError:
            return {"ready": False, "error": holder.error}
        from agents.observability import status as langfuse_status
        from agents.prompts import status as prompt_status          # 11/9 프롬프트 N개 중 Langfuse 에서 읽힌 M개(키 값 없음)
        return {"ready": True, "rag_model_configured": bool(getattr(b.rag, "model", None)), "langfuse": langfuse_status(),
                "prompts": prompt_status(),
                "search_mode": b.search.mode, "staff_ops": staff_ready,
                "orchestration": "langgraph_guidance_item_search_and_staff_ops" if staff_ready else "langgraph_guidance_and_item_search"}

    @app.get("/chat-widget/widget.js", include_in_schema=False)
    def chat_widget_js():
        """채팅 위젯 스크립트 — 화면에 <script src="/chat-widget/widget.js"></script> 한 줄"""
        return FileResponse(os.path.join(WIDGET_DIR, "widget.js"), media_type="application/javascript")

    @app.get("/chat-widget/demo", include_in_schema=False)
    def chat_widget_demo():
        """위젯 시험 페이지(재민 님 웹 완성 전 확인용)"""
        with open(os.path.join(WIDGET_DIR, "index.html"), encoding="utf-8") as f:
            return HTMLResponse(f.read())


__all__ = ["add_chat_routes", "build_chatbot_from_env", "build_ops_agent", "LazyChatbot"]
