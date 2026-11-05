"""Local LF-5 demo. No model downloads, team DB migrations or public listener."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description='분실물 설명·안내 챗봇 로컬 시연')
    parser.add_argument('--demo', action='store_true', help='가상 물건 6종이 들어 있는 SQLite DB 사용')
    parser.add_argument('--rag-model', help='이미 설치된 로컬 Ollama 모델 이름')
    parser.add_argument('--speech', action='store_true', help='이미 준비된 오프라인 small 음성 모델 사용')
    parser.add_argument('--port', type=int, default=8111)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('포트는 1~65535 사이로 지정하세요')
    if args.demo:
        if os.environ.get('LF_CHAT_DATABASE_URL'):
            parser.error('실제 DB 설정이 있으면 가상 DB 시연을 함께 켤 수 없습니다')
        os.environ['LF_CHAT_DEMO_DB'] = str(ROOT / '.cache/chat-demo.sqlite3')
    if args.rag_model:
        os.environ['LF_CHAT_RAG_MODEL'] = args.rag_model
    if args.speech:
        os.environ['LF_STT_ENABLED'] = '1'
    import uvicorn
    uvicorn.run('agents.lost_api:app', host='127.0.0.1', port=args.port, proxy_headers=False, access_log=False)


if __name__ == '__main__':
    main()
