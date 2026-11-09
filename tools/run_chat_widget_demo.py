"""Local synthetic widget preview; optional explicitly selected installed Ollama model."""
import argparse
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from agents.chat_api import add_chat_routes
from agents.chat_factory import build_chatbot
from agents.chat_search import DemoItemDatabase
from agents.guidance import Guidance
from agents.support_security import LocalRequestGuard


class WidgetDemoStyles:
    """The demo and Shadow DOM widget create inline CSS; scripts stay self-only."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def styled_send(message):
            if scope.get('path') == '/chat-widget/demo' and message['type'] == 'http.response.start' and message['status'] == 200:
                message['headers'] = [(key, value.replace(b"style-src 'self';", b"style-src 'self' 'unsafe-inline';")
                    if key.lower() == b'content-security-policy' else value) for key, value in message['headers']]
            await send(message)
        await self.app(scope, receive, styled_send)


def create_app(database_path=None, model=None, engine='legacy'):
    path = database_path or Path(__file__).resolve().parents[1]/'.cache/widget-demo.sqlite3'
    guide = Guidance()
    chatbot = build_chatbot(guide, DemoItemDatabase(path), engine=engine, model=model, rag_model=model)
    app = FastAPI(title='가상 데이터 챗봇 위젯 미리보기')
    add_chat_routes(app, chatbot)
    app.add_middleware(LocalRequestGuard)
    app.add_middleware(WidgetDemoStyles)

    @app.get('/', include_in_schema=False)
    def index():
        return RedirectResponse('/chat-widget/demo')
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8112)
    parser.add_argument('--model', help='이미 설치된 Ollama 모델 이름. 생략하면 모델 없이 문서 안내')
    parser.add_argument('--engine', choices=['legacy', 'model'], default='legacy')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be in 1..65535')
    print(f'가상 챗봇 위젯: http://127.0.0.1:{args.port}/chat-widget/demo', flush=True)
    uvicorn.run(create_app(model=args.model, engine=args.engine), host='127.0.0.1', port=args.port, proxy_headers=False, access_log=False)


if __name__ == '__main__':
    main()
