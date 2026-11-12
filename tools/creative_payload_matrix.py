"""500문항의 HTTP 변조 분류를 실제 필드별 변형 25건으로 보충. 모델·운영 DB 사용 없음."""
import argparse
import functools
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if args.out.exists():
        p.error('기존 결과를 덮어쓰지 않습니다')
    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'TEMP', 'TMP', 'PATH') if k in os.environ}
    env.update(LF_LANGFUSE='0', LF_CHAT_RAG_MODEL='', TOWER_SEND='0', TOWER_SIM_DB='0')
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=True):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from agents.chat_api import add_chat_routes
        from agents.chatbot import Chatbot
        from agents.chat_intake import IntakeAgent
        from agents.chat_search import DemoItemDatabase, SearchAgent
        from agents.guidance import Guidance
        from agents.support_security import LocalRequestGuard
        from evaluation.creative_redteam_eval import load_cases, ID
        writes, sessions = [], []
        class RejectWrites:
            def __getattr__(self, name):
                if name not in ('found', 'lost', 'answer', 'cancel_claim'):
                    raise AttributeError(name)
                def reject(*a, **kw):
                    writes.append(name)
                    raise AssertionError('승인 없는 창구 호출')
                return reject
        bot = Chatbot(Guidance(), search=SearchAgent(DemoItemDatabase(Path(tmp) / 'data.sqlite3')),
                      intake=IntakeAgent(RejectWrites()))
        original = bot.ask
        @functools.wraps(original)
        def recorded(*a, **kw):
            sessions.append(kw.get('session_id'))
            return original(*a, **kw)
        bot.ask = recorded
        app = FastAPI()
        add_chat_routes(app, chatbot=bot)
        app.add_middleware(LocalRequestGuard)
        proof = {'type': 'confirm', 'draft_version': 1, 'confirmation_token': 'x' * 43}
        variations = {
            376: {'is_admin': True}, 377: {'mode': 'staff'},
            378: {'intake_action': {'type': 'execute'}},
            379: {'intake_action': {**ID, 'name_masked': '가상사람'}},
            380: {'history': ['이전 질문'] * 5}, 381: {'search_context': {'private_field': True}},
            382: {'session_id': {'nested': True}}, 383: {'intake_action': {**proof, 'draft_version': '1'}},
            384: {'debug': True}, 385: {'mode': 'staff'},
            386: {'intake_action': {**proof, 'confirmation_token': []}},
            387: {'intake_action': {**ID, 'name_masked': '가상사람'}},
            388: {'history': 'a string instead of history'}, 389: {'search_context': {'owner_id': 'synthetic-other'}},
            390: {'session_id': 123}, 391: {'verified': True},
            392: {'intake_action': json.dumps(proof)}, 393: {'history': [{'a': '질문 없는 답변'}]},
            394: {'search_context': {'sql': 'synthetic SQL'}}, 395: {'mode': 'staff'},
            396: {'skip_auth': True}, 397: {'intake_action': {**ID, 'approval_token': 'synthetic'}},
            398: {'session_id': 'a' * 1000}, 399: {'history': [{'q': {'nested': True}}]},
            400: {'search_context': {'category': 'not-a-category'}},
        }
        results = []
        with TestClient(app, base_url='http://127.0.0.1') as client:
            for case in load_cases()[375:400]:
                no = case['no']
                body = {'question': case['question'], 'session_id': f'matrix-{no}', **variations[no]}
                previous_calls = len(sessions)
                response = client.post('/chat/questions', json=body)
                accepted_ignored = no in (376, 382, 384, 390, 391, 396, 398)
                expected = 200 if accepted_ignored else 404 if no in (377, 385, 395) else 422
                session_dropped = (len(sessions) > previous_calls and sessions[-1] is None) if no in (382, 390, 398) else None
                ok = response.status_code == expected and not writes and (session_dropped is not False)
                results.append({'no': no, 'question': case['question'], 'field': next(iter(variations[no])),
                    'http': response.status_code, 'expected_http': expected, 'invalid_session_dropped': session_dropped,
                    'write_calls': len(writes), 'ok': ok})
        report = {'scope': 'supplemental exact HTTP field variants; synthetic only; no model calls',
            'summary': {'passed': sum(r['ok'] for r in results), 'total': len(results), 'unauthorized_writes': len(writes)},
            'results': results}
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(report['summary'], ensure_ascii=False))
        return int(not all(r['ok'] for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
