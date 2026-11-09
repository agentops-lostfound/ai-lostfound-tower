"""Opt-in actual local-model HTTP checks using synthetic questions and a temporary DB."""
import argparse
import json
import tempfile
import time
from pathlib import Path
from fastapi.testclient import TestClient
from tools.run_chat_widget_demo import create_app


CASES = [
    ('photo', '사진은 어떻게 올려요?', 'answered', True),
    ('voice', '마이크가 없으면 글로 입력해도 되나요?', 'answered', True),
    ('pickup', '물건 수령 절차 알려줘', 'answered', True),
    ('privacy', '분실인 개인정보는 어떻게 저장하나요?', 'answered', True),
    ('first_visit', '처음 왔는데 뭐부터 하면 돼요?', 'answered', True),
    ('found_report', '주운 물건은 어떻게 신고하나요?', 'answered', True),
    ('combined_search_help', '검정 지갑 찾아줘. 수령 절차도 알려줘', 'answered', True),
    ('unknown_hours', '주말 운영시간은?', 'policy_pending', False),
    ('unknown_retention', '지갑 보관기간은 며칠인가요?', 'policy_pending', False),
    ('database_search', '검정 지갑 찾아줘', 'items_found', False),
    ('private_input', '010-1234-5678 내 전화번호야', None, False),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, help='이미 설치된 Ollama 모델 이름; 다운로드하지 않음')
    args = parser.parse_args()
    passed = 0
    with tempfile.TemporaryDirectory(prefix='lf-chat-sllm-') as folder, TestClient(
            create_app(Path(folder)/'demo.sqlite3', model=args.model),
            base_url='http://127.0.0.1:8112') as client:
        for name, question, status, expect_model in CASES:
            started = time.monotonic()
            response = client.post('/chat/questions', json={'question': question})
            result = response.json()
            if status is None:
                ok = response.status_code == 422
            else:
                ok = (response.status_code == 200 and result.get('status') == status
                      and result.get('generation_used', False) == expect_model
                      and bool(result.get('answer')))
                if expect_model:
                    ok = ok and bool(result.get('sources'))
                    if name == 'combined_search_help':
                        ok = (ok and result.get('search_status') == 'items_found'
                              and result.get('generation_status') == 'generated'
                              and result.get('model') == args.model
                              and bool(result.get('candidates')) and not result.get('reservation_created'))
                    else:
                        ok = ok and not result.get('item_search_performed')
                if name == 'database_search':
                    ok = ok and bool(result.get('candidates')) and not result.get('reservation_created')
            passed += bool(ok)
            print(json.dumps({'case': name, 'passed': bool(ok),
                'elapsed_seconds': round(time.monotonic()-started, 2),
                'http_status': response.status_code, 'status': result.get('status'),
                'generation_used': result.get('generation_used', False),
                'generation_status': result.get('generation_status')}, ensure_ascii=False), flush=True)
    print(json.dumps({'model': args.model, 'passed': passed, 'total': len(CASES)}, ensure_ascii=False))
    return 0 if passed == len(CASES) else 1


if __name__ == '__main__':
    raise SystemExit(main())
