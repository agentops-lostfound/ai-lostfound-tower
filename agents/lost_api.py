"""LF-5 description input and document/search agent chat API."""
import base64
import binascii
import io
import os
import tempfile
import threading
import wave
from pathlib import Path
from fastapi import FastAPI, Body, Header, HTTPException
from agents.intake import decode_photo, IntakeError
from agents.lost_input import DescriptionService, build_description_graph


def wav_bytes(value):
    if not isinstance(value, str) or len(value) > 2_600_000:
        raise ValueError("음성 파일이 없거나 너무 큽니다")
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) < 44 or len(raw) > 2_000_000 or int.from_bytes(raw[4:8], 'little') != len(raw) - 8:
            raise ValueError()
        with wave.open(io.BytesIO(raw), "rb") as audio:
            if (audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 16000
                    or audio.getcomptype() != "NONE" or not 0 < audio.getnframes() / 16000 <= 60):
                raise ValueError()
            frames = audio.readframes(audio.getnframes())
            if len(frames) != audio.getnframes() * 2:
                raise ValueError()
        # Forward only canonical PCM audio, never RIFF metadata or appended payloads.
        output = io.BytesIO()
        with wave.open(output, 'wb') as clean:
            clean.setnchannels(1); clean.setsampwidth(2); clean.setframerate(16000)
            clean.writeframes(frames)
        return output.getvalue()
    except (ValueError, binascii.Error, EOFError, wave.Error):
        raise ValueError("60초 이하 16kHz 모노 PCM16 WAV 파일이 필요합니다") from None


def create_app(service=None, guidance=None, chatbot=None, request_policy=None):
    from agents.guidance import Guidance
    from agents.chatbot import Chatbot
    guidance = guidance or Guidance()
    chatbot = chatbot or Chatbot(guidance)
    service = service or DescriptionService()
    graph = build_description_graph(service)
    app = FastAPI(title="분실 설명 입력", version="0.1")
    from agents.support_security import LocalRequestGuard
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    app.add_middleware(LocalRequestGuard, policy=request_policy)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI's default error includes the rejected input, which can contain secrets.
        return JSONResponse({'detail': '입력 형식이 올바르지 않습니다. 입력 항목을 확인해주세요'}, status_code=422)
    # One media inference at a time on a small demo PC; no background unbounded queue.
    media_lock = threading.Lock()

    @app.get("/input")
    def input_page():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).resolve().parents[1] / "web/lost-input/index.html")

    def run(call):
        try:
            return call()
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from None

    @app.get("/health")
    def health():
        return {"status": "ok", "photo_configured": service.photo_extractor is not None,
                "speech_configured": service.transcriber is not None, "guidance_rag": "project_documents_with_policy_gaps",
                "chat_rag_model_configured": bool(chatbot.rag.model), "chat_search_mode": chatbot.search.mode,
                "chat_orchestration": "langgraph_guidance_and_item_search"}

    @app.post("/chat/questions")
    def chat_question(body: dict = Body(...), authorization: str | None = Header(default=None)):
        token = authorization[7:] if authorization and authorization.startswith('Bearer ') else None
        result = run(lambda: chatbot.ask(body.get('question'), token, body.get('search_context'), body.get('history')))
        guidance.record_suggestion(body.get('suggestion_id'), body.get('question'))
        return result

    @app.get('/guidance/documents/site-help')
    def site_help():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).resolve().parents[1] / 'docs/guidance/site-help.md', media_type='text/plain; charset=utf-8')

    @app.post("/guidance/questions")
    def guidance_question(body: dict = Body(...)):
        result = run(lambda: guidance.ask(body.get("question")))
        guidance.record_suggestion(body.get("suggestion_id"), body.get("question"))
        return result

    @app.get("/guidance/suggestions")
    def guidance_suggestions():
        return guidance.suggestions()

    from fastapi.staticfiles import StaticFiles
    app.mount("/input-assets", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web/lost-input/assets"), name="lost-input-assets")

    @app.post("/descriptions/text")
    def text(body: dict = Body(...)):
        return run(lambda: graph.invoke({"payload": body})["proposal"])

    @app.post("/descriptions/photo")
    def photo(body: dict = Body(...)):
        def process():
            raw, _ = decode_photo(body.get("photo"))
            if not media_lock.acquire(blocking=False):
                raise RuntimeError("사진·음성을 처리 중입니다. 잠시 후 다시 시도해주세요")
            try:
                return service.from_photo(raw, body)
            finally:
                media_lock.release()
        return run(process)

    @app.post("/descriptions/audio")
    def audio(body: dict = Body(...)):
        def process():
            raw = wav_bytes(body.get("audio_base64"))
            if not media_lock.acquire(blocking=False):
                raise RuntimeError("사진·음성을 처리 중입니다. 잠시 후 다시 시도해주세요")
            try:
                with tempfile.TemporaryDirectory(prefix="lf-speech-") as folder:
                    path = Path(folder) / "input.wav"
                    path.write_bytes(raw)
                    return service.from_audio(path, body)
            finally:
                media_lock.release()
        return run(process)

    @app.post('/chat/transcriptions')
    def chat_transcription(body: dict = Body(...)):
        def process():
            raw = wav_bytes(body.get('audio_base64'))
            if not media_lock.acquire(blocking=False):
                raise RuntimeError('사진·음성을 처리 중입니다. 잠시 후 다시 시도해주세요')
            try:
                with tempfile.TemporaryDirectory(prefix='lf-chat-speech-') as folder:
                    path = Path(folder) / 'input.wav'
                    path.write_bytes(raw)
                    return {'text': service.transcribe_audio(path, limit=500), 'sent': False}
            finally:
                media_lock.release()
        return run(process)

    @app.post("/descriptions/{proposal_id}/confirm")
    def confirm(proposal_id: str, body: dict = Body(...)):
        return run(lambda: service.confirm(proposal_id, body))

    # Public operational guidance has no access to claims, candidates or robot APIs.
    return app


def from_environment():
    from agents.lost_photo import OllamaPhoto
    photo = OllamaPhoto(os.environ["LF_OLLAMA_MODEL"]) if os.environ.get("LF_OLLAMA_MODEL") else None
    speech = None
    if os.environ.get("LF_STT_ENABLED") == "1":
        def speech():
            from agents.chat_speech_worker import BoundedSpeechWorker
            return BoundedSpeechWorker()
    from agents.guidance import Guidance
    from agents.chatbot import Chatbot
    from agents.chat_rag import GroundedRag
    from agents.chat_search import SearchAgent, DemoItemDatabase, PostgresItemSearch
    guide = Guidance()
    database = None
    # Explicit mode: never fall back from a real DB error to invented demo results.
    if os.environ.get('LF_CHAT_DATABASE_URL'):
        database = PostgresItemSearch(os.environ['LF_CHAT_DATABASE_URL'])
    elif os.environ.get('LF_CHAT_DEMO_DB'):
        database = DemoItemDatabase(os.environ['LF_CHAT_DEMO_DB'])
    chatbot = Chatbot(guide, rag=GroundedRag(guide, model=os.environ.get('LF_CHAT_RAG_MODEL')),
                      search=SearchAgent(database))
    return create_app(DescriptionService(photo_extractor=photo, transcriber=speech), guide, chatbot)


app = from_environment()
