"""동일 여정을 고정 소스에서 HTTP로 실행. 운영 환경/실물/외부 알림은 사용하지 않는다."""
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.dialogue_context_cases import cases, IDENTITY


class Desk:
    def __init__(self):
        self.calls = []

    def found(self, text):
        self.calls.append('found')
        return {'item_id': 'S-20261112-9001', 'place_text': '초량역 승강장', 'story_id': 'synthetic-found'}

    def lost(self, text, opts):
        self.calls.append('lost')
        return {'claim_id': 'C-20261112-9001', 'quiz_passed': True, 'item_id': 'S-20261112-9001'}


def run_case(case, tmp, model=''):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agents.chat_api import add_chat_routes, build_chatbot_from_env
    from agents.chat_search import DemoItemDatabase
    desk = Desk()
    bot = build_chatbot_from_env(DemoItemDatabase(Path(tmp)/'items.sqlite'), desk=desk)
    app = FastAPI()
    add_chat_routes(app, chatbot=bot)
    sid = 'dialogue-'+case['id']
    history, rows = [], []
    with TestClient(app) as client:
        for raw in case['turns']:
            step = {'say': raw} if isinstance(raw, str) else raw
            before = copy.deepcopy(bot.intake.active(sid))
            body = {'question': step['say'], 'session_id': sid, 'history': history[-4:]}
            if step.get('identity'):
                body['intake_action'] = IDENTITY
            response = client.post('/chat/questions', json=body)
            obj = response.json()
            after = copy.deepcopy(bot.intake.active(sid))
            why, a = [], str(obj.get('answer', ''))
            if response.status_code != 200:
                why.append(f'HTTP {response.status_code}')
            if step.get('preserve'):
                if before is None:
                    raise RuntimeError(f'준비 실패: {case["id"]}')
                if after is None or (before.get('slots'), before.get('version')) != (after.get('slots'), after.get('version')):
                    why.append('초안 오염/유실')
            if 'asked' in step and (obj.get('intake') or {}).get('asked', 'missing') != step['asked']:
                why.append(f'이어질 질문 누락: {step["asked"]}')
            if 'stage' in step and (after or {}).get('stage') != step['stage']:
                why.append('단계 변경')
            if 'topic' in step and step['topic'] not in [s['topic'] for s in obj.get('sources', [])]:
                why.append(f'주제 유실: {step["topic"]}')
            if 'search' in step and bool(obj.get('item_search_performed')) != step['search']:
                why.append('검색 실행 여부')
            for k, v in step.get('filter', {}).items():
                if obj.get('search_filter', {}).get(k) != v:
                    why.append(f'검색 조건 유실: {k}')
            if 'writes' in step and len(desk.calls) != step['writes']:
                why.append('업무 쓰기 횟수')
            if step.get('not_done') and obj.get('status') == 'intake_done':
                why.append('미승인 완료')
            if step.get('any') and not any(word in a for word in step['any']):
                why.append('문장 의도 누락')
            rows.append({'say': step['say'], 'answer': a, 'status': obj.get('status'), 'why': why})
            history.append({'q': step['say'], 'a': a[:300]})
    return {'id': case['id'], 'group': case['group'], 'ok': not any(r['why'] for r in rows), 'turns': rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--source-root', default=str(ROOT))
    ap.add_argument('--model', default='')
    ap.add_argument('--only', default='')
    args = ap.parse_args()
    output = Path(args.out).resolve()
    if output.exists():
        ap.error('기존 결과는 덮어쓰지 않습니다')
    target = Path(args.source_root).resolve()
    sys.path.insert(0, str(target))
    for key in list(os.environ):
        if key.startswith(('LF_', 'TOWER_', 'LANGFUSE_', 'DISCORD_')) or key == 'DATABASE_URL':
            os.environ.pop(key)
    os.environ.update(LF_LANGFUSE='0', LF_CHAT_RAG_MODEL=args.model, LF_CHAT_AGENT_MODEL=args.model,
                      TOWER_SEND='0', TOWER_GPU_LEASE='0')
    chosen = [c for c in cases() if not args.only or c['id'] in args.only.split(',')]
    hashes = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (target/'agents').glob('*.py')}
    from agents import local_model, chat_agents
    native_request = local_model.ask_local_model
    calls = []
    def counted(payload, **kwargs):
        started = time.monotonic()
        item = {'ok': False}
        try:
            body = json.loads(payload['messages'][1]['content'])
            item['context_present'] = 'conversation_context' in body
            value = native_request(payload, **kwargs)
            item['ok'] = True
            return value
        finally:
            item['seconds'] = round(time.monotonic()-started, 3)
            calls.append(item)
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp, patch.object(local_model, 'ask_local_model', counted), patch.object(chat_agents, 'ask_local_model', counted):
        rows = [run_case(c, tmp, args.model) for c in chosen]
    same = hashes == {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (target/'agents').glob('*.py')}
    result = {'model': args.model or 'rules', 'synthetic_only': True, 'source_unchanged': same,
              'source_sha256': hashes, 'cases_sha256': hashlib.sha256(json.dumps(chosen, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
              'total': len(rows), 'passed': sum(r['ok'] for r in rows), 'turns': sum(len(r['turns']) for r in rows),
              'seconds': round(time.monotonic()-start, 3), 'failures_by_group': dict(Counter(r['group'] for r in rows if not r['ok'])),
              'model_calls': calls, 'model_errors': sum(not c['ok'] for c in calls), 'results': rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('total', 'passed', 'turns', 'source_unchanged', 'seconds', 'failures_by_group')}, ensure_ascii=False))
    return 0 if same and result['passed'] == result['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
