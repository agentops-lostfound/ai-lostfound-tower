"""독립 사용자 여정 회귀: 실제 HTTP·초안·합성 창구 호출을 함께 판정한다."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.conversation_quality_cases import cases, IDENTITY


def fingerprint(bot, sid):
    s = bot.intake.active(sid)
    return copy.deepcopy({k: s.get(k) for k in ('kind', 'slots', 'stage', 'asked', 'version')} if s else None)


def structure_problems(step, answer):
    problems = ['필수 안내 누락: '+w for w in step.get('all', []) if w not in answer]
    first = re.split(r'[.!?\n]', answer, maxsplit=1)[0]
    if step.get('first_any') and not any(w in first for w in step['first_any']):
        problems.append('첫 문장이 질문의 결론이 아님')
    return problems


class RecordingDesk:
    """쓰기 횟수·인수를 기록하는 합성 창구. 운영 DB/로봇과 연결하지 않는다."""
    def __init__(self, quiz=False):
        self.calls = []; self.quiz = quiz

    def found(self, text):
        self.calls.append(('found', text))
        return {'item_id': 'S-20261112-9001', 'place_text': '합성 장소', 'story_id': 'synthetic'}

    def lost(self, text, opts):
        self.calls.append(('lost', text))
        if self.quiz:
            return {'pending_id': 'synthetic-quiz', 'question': '물건의 스티커가 어떤 모양인가요?', 'candidates': [{}, {}]}
        return {'wait_id': 'L-20261112-9001', 'waiting': True}

    def answer(self, pending_id, text):
        self.calls.append(('answer', text))
        return {'claim_id': 'C-20261112-9001', 'quiz_passed': True, 'item_id': 'S-20261112-9001'}

    def cancel_claim(self, claim_id, **kwargs):
        self.calls.append(('cancel', claim_id))
        return {'item_id': 'S-20261112-9001'}


def run_case(case, tmp):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agents.chat_api import add_chat_routes, build_chatbot_from_env
    from agents.chat_search import DemoItemDatabase
    desk = RecordingDesk(quiz=case.get('quiz', False))
    bot = build_chatbot_from_env(DemoItemDatabase(Path(tmp)/'items.sqlite'),
                                 desk=desk)
    app = FastAPI()
    add_chat_routes(app, chatbot=bot)
    sid = 'journey-'+case['id']; history = []; proof = old = used = None; rows = []
    with TestClient(app, base_url='http://127.0.0.1') as client:
        for setup, steps in [(True, case['setup']), (False, case['turns'])]:
            for step in steps:
                step = {'say': step} if isinstance(step, str) else step
                body = {'question': step['say'], 'session_id': sid, 'history': history[-4:]}
                if step.get('identity'):
                    body['intake_action'] = dict(IDENTITY)
                p = step.get('proof')
                if p:
                    selected = {'current': proof, 'old': old, 'same': used}[p]
                    if selected:
                        body['intake_action'] = dict(selected)
                        used = dict(selected)
                before = fingerprint(bot, sid)
                response = client.post('/chat/questions', json=body)
                obj = response.json(); after = fingerprint(bot, sid)
                why = []
                if response.status_code != 200:
                    why.append(f'HTTP {response.status_code}')
                if setup and not after:
                    raise RuntimeError(f"여정 준비 실패: {case['id']} {step['say']} {obj.get('status')}")
                a = obj.get('answer') or ''
                if not a.strip():
                    why.append('빈 답변')
                if len(desk.calls) != step.get('writes', 0):
                    why.append(f'업무쓰기 {len(desk.calls)} != {step.get("writes", 0)}')
                if step.get('preserve') and before != after:
                    why.append('안내 질문이 초안을 변경함')
                if step.get('status') and obj.get('status') != step['status']:
                    why.append('상태 불일치: '+str(obj.get('status')))
                if step.get('not_done') and obj.get('status') == 'intake_done':
                    why.append('동의 없이 완료')
                if step.get('asked') and (obj.get('intake') or {}).get('asked') != step['asked']:
                    why.append('다음 질문 불일치')
                if step.get('kind') and (after or {}).get('kind') != step['kind']:
                    why.append('분실/습득 역할 전환 실패')
                slots = (after or {}).get('slots', {})
                for key, val in step.get('slots', {}).items():
                    if slots.get(key) != val:
                        why.append(f'{key}: {slots.get(key)!r} != {val!r}')
                for key in step.get('absent', []):
                    if key in slots:
                        why.append('이전 업무 값 유지: '+key)
                if step.get('any') and not any(w in a for w in step['any']):
                    why.append('질문에 필요한 안내 누락: '+str(step['any']))
                why.extend(structure_problems(step, a))
                rows.append({'setup': setup, 'say': step['say'], 'http': response.status_code,
                             'status': obj.get('status'), 'answer': a, 'why': why,
                             'state': after, 'writes': len(desk.calls)})
                if obj.get('confirmation'):
                    proof = dict(obj['confirmation'])
                    if old is None:
                        old = dict(proof)
                else:
                    proof = None
                history.append({'q': step['say'], 'a': a[:300]})
    return {'id': case['id'], 'group': case['group'], 'ok': not any(r['why'] for r in rows), 'turns': rows}


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--model', default='')
    parser.add_argument('--source-root', default='')
    parser.add_argument('--holdout', action='store_true')
    parser.add_argument('--quiz', action='store_true')
    parser.add_argument('--only', default='')
    parser.add_argument('--stop-file', default='conversation-quality-stop.flag')
    args = parser.parse_args()
    if args.source_root:
        ROOT = Path(args.source_root).resolve()
        sys.path.insert(0, str(ROOT))
    case_loader = cases
    if args.holdout:
        from evaluation.conversation_quality_holdout import cases as case_loader
    if args.quiz:
        from evaluation.conversation_quality_quiz import cases as case_loader
    selected = set(args.only.split(',')) if args.only else None
    all_cases = case_loader()
    planned = [c for c in all_cases if selected is None or c['id'] in selected]
    if not planned:
        raise SystemExit('선택된 여정 없음')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TOWER_', 'LF_', 'LANGFUSE_', 'DISCORD_'))
           and k != 'DATABASE_URL'}
    env.update(LF_LANGFUSE='0', LF_CHAT_RAG_MODEL=args.model, LF_CHAT_AGENT_MODEL=args.model,
               LF_AGENT_SUPERVISOR_USE_LLM='1' if args.model else '0', TOWER_SEND='0', TOWER_GPU_LEASE='0')
    output = Path(args.out)
    if output.exists():
        parser.error('기존 실행 기록은 덮어쓰지 않습니다. 새 출력 이름을 지정해 주세요.')
    output.parent.mkdir(parents=True, exist_ok=True)
    calls = []; start = time.perf_counter()
    from agents import local_model, chat_agents
    request = local_model.ask_local_model
    def counted(*a, **kw):
        row = {'ok': False}
        t = time.perf_counter()
        try:
            value = request(*a, **kw); row['ok'] = True; return value
        finally:
            row['seconds'] = round(time.perf_counter()-t, 3); calls.append(row)
    report = {'meta': {'model': args.model or 'rules', 'synthetic_only': True, 'state': 'running',
                      'evaluator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      'holdout': args.holdout,
                      'quiz': args.quiz,
                      'expected': len(planned), 'cases_sha256': hashlib.sha256(json.dumps(all_cases, sort_keys=True,
                          ensure_ascii=False).encode()).hexdigest(),
                      'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted((ROOT/'agents').glob('*.py'))}}, 'results': []}
    def save():
        report['summary'] = {'passed': sum(r['ok'] for r in report['results']), 'total': len(report['results']),
            'turns': sum(len(r['turns']) for r in report['results']), 'model_calls': len(calls),
            'model_errors': sum(not r['ok'] for r in calls), 'seconds': round(time.perf_counter()-start, 2)}
        report['groups'] = {g: {'passed': sum(r['ok'] for r in report['results'] if r['group']==g), 'total': n}
                            for g, n in Counter(r['group'] for r in report['results']).items()}
        report['model_calls'] = calls
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        temporary.replace(output)
    with patch.dict(os.environ, env, clear=True), patch.object(local_model, 'ask_local_model', counted), \
         patch.object(chat_agents, 'ask_local_model', counted), tempfile.TemporaryDirectory() as tmp:
        for case in planned:
            if Path(args.stop_file).exists():
                report['meta']['state'] = 'stopped'; break
            result = run_case(case, tmp)
            report['results'].append(result)
            if not result['ok'] or len(report['results']) % 20 == 0:
                print(case['id'], 'PASS' if result['ok'] else 'FAIL', flush=True)
            save()
        if report['meta']['state'] == 'running':
            report['meta']['state'] = 'complete'
        report['meta']['source_unchanged'] = report['meta']['source_sha256'] == {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'agents').glob('*.py'))}
        save()
    print(json.dumps(report['summary']), flush=True)
    return 130 if report['meta']['state']=='stopped' else int(
        report['summary']['passed'] != len(planned) or not report['meta']['source_unchanged'])


if __name__ == '__main__':
    raise SystemExit(main())
