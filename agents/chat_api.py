"""AI 챗봇 위젯용 API — 관제탑(8100)에 붙는 챗봇 입구 (LF-5, 11/5)

한줄 설명: 화면 어디에든 `<script src="/chat-widget/widget.js">` 한 줄로 붙는 채팅 창이 부르는 주소들을 관제탑에 더한다.
챗봇 두뇌는 정연우 LF-5 의 `agents/chatbot.py`(LangGraph: 이용 안내 RAG + 물건 검색 에이전트)를 그대로 쓴다.

주소
    POST /chat/questions      {"question": "...", "history": ["이전 질문", ...최대 4개]} → 답변·근거·후보 카드
    GET  /chat/suggestions    추천 질문 목록
    GET  /chat/health         챗봇 준비 상태(문서 RAG 모델·검색 모드)
    GET  /chat-widget/widget.js   채팅 위젯 스크립트(web/chat-widget/widget.js)
    GET  /chat-widget/demo        위젯 시험 페이지(web/chat-widget/index.html)

환경값(.env, 없으면 기본)
    LF_CHAT_RAG_MODEL     문서 답변을 다듬을 로컬 Ollama 모델 이름. 없으면 문서 문단을 그대로 안내
    LF_CHAT_DATABASE_URL  실제 팀 DB 조회(본인인증 세션 검증기가 연결돼야 열림 — 지금은 연결 전)
    TOWER_CHAT_DEMO_DB    가상 물건 DB(SQLite) 파일. 기본 저장소/.cache/chat-demo.sqlite3, "0" 이면 물건 검색 끔

- 챗봇 부품(langgraph 등)은 첫 질문 때 만든다. 설치가 안 돼 있어도 관제탑은 켜지고, 챗봇 주소만 503 으로 알린다
- 질문 원문은 저장하지 않는다(추천 질문 선택 횟수만 셈). 인증 토큰은 Authorization: Bearer 로만 받는다
"""
from __future__ import annotations

import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIDGET_DIR = os.path.join(ROOT, "web", "chat-widget")


def build_chatbot_from_env():
    """환경값으로 챗봇을 만든다. 실제 DB 설정이 있으면 가상 DB 로 바꿔 대신하지 않는다(정연우 원칙 유지)."""
    from agents.chat_rag import GroundedRag
    from agents.chat_search import DemoItemDatabase, PostgresItemSearch, SearchAgent
    from agents.chatbot import Chatbot
    from agents.guidance import Guidance
    guide = Guidance()
    database = None
    if os.environ.get("LF_CHAT_DATABASE_URL"):
        database = PostgresItemSearch(os.environ["LF_CHAT_DATABASE_URL"])
    else:
        demo = (os.environ.get("TOWER_CHAT_DEMO_DB") or "").strip()
        if demo != "0":
            database = DemoItemDatabase(demo or os.path.join(ROOT, ".cache", "chat-demo.sqlite3"))
    rag = GroundedRag(guide, model=os.environ.get("LF_CHAT_RAG_MODEL") or None)
    return Chatbot(guide, rag=rag, search=SearchAgent(database))


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
                    except Exception as e:     # langgraph 미설치·문서 파일 없음 등
                        self.error = f"{type(e).__name__}: {e}"
                        raise RuntimeError("챗봇을 준비하지 못했습니다. 관제탑 PC 의 설치 상태를 확인하세요") from e
        return self._bot


def add_chat_routes(app, chatbot=None) -> None:
    """관제탑 앱(agents/api.py build_app)에 챗봇·위젯 주소를 더한다. chatbot 은 시험용으로 바꿔 끼울 수 있다."""
    from fastapi import Body, Header, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse

    holder = chatbot if isinstance(chatbot, LazyChatbot) else LazyChatbot(lambda: chatbot) if chatbot else LazyChatbot()

    def bot():
        try:
            return holder.get()
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from None

    @app.post("/chat/questions")
    def chat_question(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
        """AI 챗봇 질문. 본문 {question, history?(이전 질문 최대 4개), suggestion_id?, search_context?}"""
        b = bot()
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
        try:
            result = b.ask(body.get("question"), token, body.get("search_context"), body.get("history"))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from None
        b.guidance.record_suggestion(body.get("suggestion_id"), body.get("question"))
        return result

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
        return {"ready": True, "rag_model_configured": bool(getattr(b.rag, "model", None)),
                "search_mode": b.search.mode, "orchestration": "langgraph_guidance_and_item_search"}

    @app.get("/chat-widget/widget.js", include_in_schema=False)
    def chat_widget_js():
        """채팅 위젯 스크립트 — 화면에 <script src="/chat-widget/widget.js"></script> 한 줄"""
        return FileResponse(os.path.join(WIDGET_DIR, "widget.js"), media_type="application/javascript")

    @app.get("/chat-widget/demo", include_in_schema=False)
    def chat_widget_demo():
        """위젯 시험 페이지(재민 님 웹 완성 전 확인용)"""
        with open(os.path.join(WIDGET_DIR, "index.html"), encoding="utf-8") as f:
            return HTMLResponse(f.read())


__all__ = ["add_chat_routes", "build_chatbot_from_env", "LazyChatbot"]
