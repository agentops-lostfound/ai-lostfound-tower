"""실제 Mi:dm 검증. .env/팀 DB/Langfuse/기존 엑셀을 읽거나 변경하지 않는다."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite', choices=['live', '500'], required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--stop-file', help='이 파일이 생기면 다음 문항을 시작하지 않고 부분 결과를 보존')
    p.add_argument('--only', default='', help='검증할 문항 번호(쉼표 구분). 원본 전체 점수와 구분해 기록')
    p.add_argument('--questions', default='', help='별도 JSON 문항(선택한 suite 형식). 기존 500문항을 변경하지 않음')
    p.add_argument('--prompt-label', choices=['production', 'staging'], default='production', help='프롬프트 조회 라벨. 클라우드 연결이 없으면 기본값 사용을 명시')
    args = p.parse_args(argv)
    output = Path(args.out)
    if output.exists():
        p.error('기존 검증 기록은 덮어쓰지 않습니다. 새 출력 이름을 지정해주세요')
    output.parent.mkdir(parents=True, exist_ok=True)
    stop_file = Path(args.stop_file) if args.stop_file else None
    if stop_file is not None and stop_file.exists():
        output.write_text(json.dumps({'meta': {'suite': args.suite, 'state': 'stopped',
            'data': 'synthetic_only', 'langfuse': False}, 'results': [],
            'summary': {'passed': 0, 'total': 0}}, ensure_ascii=False), encoding='utf-8')
        return 130
    only = {int(n) for n in args.only.split(',') if n.strip()}
    from agents import local_model
    from agents import chat_supervisor
    from agents import prompts
    from agents import chat_agents
    from agents.chat_agents import AgentBrain
    original_request, original_decide = local_model.ask_local_model, chat_supervisor.decide
    original_plan = AgentBrain.plan_contract
    calls, audits, audit_examples, planner_checks = [], Counter(), [], Counter()

    def plan_contract(brain, *a, **kw):
        decision = original_plan(brain, *a, **kw)
        planner_checks[decision.audit['validation'] + ':' + decision.audit['reason']] += 1
        return decision

    def request(payload, *a, **kw):
        props = (payload.get('format') or {}).get('properties', {}) if isinstance(payload.get('format'), dict) else {}
        role = ('supervisor' if 'action' in props else 'coordinator' if 'intent' in props
                else 'planner' if 'steps' in props else 'intake_or_search' if 'category' in props
                else 'researcher_or_ops')
        t = time.perf_counter()
        row = {'role': role, 'model': payload.get('model')}
        try:
            out = original_request(payload, *a, **kw)
            row['ok'] = True
            row['eval_count'] = out.get('eval_count')
            row['load_seconds'] = round(out.get('load_duration', 0) / 1e9, 3)
            return out
        except Exception as e:
            row.update(ok=False, error=type(e).__name__)
            raise
        finally:
            row['seconds'] = round(time.perf_counter() - t, 3)
            calls.append(row)

    def decide(*a, **kw):
        chosen, audit = original_decide(*a, **kw)
        audits[audit['validation'] + ':' + audit['reason']] += 1
        if audit['validation'] == 'rejected' and len(audit_examples) < 20:
            audit_examples.append({'allowed': a[1], 'audit': audit})
        return chosen, audit

    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'TEMP', 'TMP', 'PATH') if k in os.environ}
    env.update(LF_LANGFUSE='0', LF_CHAT_RAG_MODEL='midm-2.0-mini', LF_CHAT_AGENT_MODEL='midm-2.0-mini',
               LF_PROMPT_LABEL=args.prompt_label,
               LF_AGENT_SUPERVISOR_USE_LLM='1', TOWER_SIM='1', TOWER_SIM_SPEED='0', TOWER_SIM_DB='0',
               TOWER_GPU_LEASE='0', TOWER_SEND='0', TOWER_AGENT_TALK='0')
    report = {'meta': {'suite': args.suite, 'model': 'midm-2.0-mini', 'supervisor_llm': True,
                       'langfuse': False, 'prompt_label': args.prompt_label, 'data': 'synthetic_only',
                       'selection': sorted(only) if only else 'all', 'state': 'running',
                       'started': dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat()}, 'results': []}
    report['meta']['source_sha256'] = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ('agents/chatbot.py', 'agents/chat_agents.py', 'agents/chat_supervisor.py', 'agents/prompts.py',
                     'agents/guidance.py', 'agents/chat_rag.py', 'agents/chat_retrieval.py',
                     'agents/chat_api.py', 'agents/chat_intake.py', 'agents/chat_find_auth.py',
                     'agents/chat_postgres_access.py', 'agents/chat_session_issuer.py',
                     'agents/chat_identity_evidence.py', 'agents/chat_operations.py')}
    for name in ('agents/chat_planner.py', 'agents/ops_analyst.py', 'tools/validate_chat_midm.py', 'evaluation/chat_eval.py'):
        report['meta']['source_sha256'][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    try:
        report['meta']['commit'] = subprocess.check_output(['git', '-c', f'safe.directory={ROOT.as_posix()}',
                                                          'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except Exception:
        report['meta']['commit'] = 'unknown'
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(local_model, 'ask_local_model', request), mock.patch.object(chat_supervisor, 'decide', decide), \
         mock.patch.object(chat_agents, 'ask_local_model', request), \
         mock.patch.object(AgentBrain, 'plan_contract', plan_contract), \
         prompts.usage_scope():
        os.environ['TOWER_CHAT_DEMO_DB'] = str(Path(tmp) / 'demo.sqlite3')
        from tools.chat_live_check import installed_models, model_ready, model_probe
        why = model_ready('midm-2.0-mini', installed_models()) or model_probe('midm-2.0-mini')
        if why:
            print(why)
            return 2
        if args.suite == 'live':
            from tools.chat_live_check import run, QUESTIONS
            from agents.chat_api import build_chatbot_from_env
            path = Path(args.questions) if args.questions else QUESTIONS
            report['meta']['questions_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            items = list(enumerate(json.loads(path.read_text(encoding='utf-8')), 1))
            chosen = [(n, q) for n, q in items if not only or n in only]
            report['meta']['expected_questions'] = len(chosen)
            bot, results = build_chatbot_from_env(), []
            for n, question in chosen:
                if stop_file is not None and stop_file.exists():
                    report['meta']['state'] = 'stopped'
                    break
                results.extend(run(bot, [(n, question)]))
                report['results'] = results
                output.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
            report['results'] = results
            passed = sum(r['ok'] for r in results)
        else:
            from evaluation.chat_eval import Runner, QUESTIONS
            runner = Runner()
            path = Path(args.questions) if args.questions else QUESTIONS
            report['meta']['questions_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            items = json.loads(path.read_text(encoding='utf-8'))
            report['meta']['expected_questions'] = sum(not only or it['no'] in only for it in items)
            for it in items:
                if only and it['no'] not in only:
                    continue
                if stop_file is not None and stop_file.exists():
                    report['meta']['state'] = 'stopped'
                    break
                n = len(calls)
                r = runner.run_item(it)
                r.update(group=it['group'], model_calls=len(calls) - n)
                report['results'].append(r)
                if not r['score'] or it['no'] % 10 == 0:
                    print(it['no'], 'PASS' if r['score'] else 'FAIL', r['seconds'], r['why'], flush=True)
                # 긴 실행 중에도 완료된 문항과 실제 호출 증거를 보존한다.
                report['model_calls'] = calls
                report['supervisor_checks'] = dict(audits)
                report['planner_checks'] = dict(planner_checks)
                report['supervisor_rejection_examples'] = audit_examples
                report['meta']['prompt_usage'] = prompts.loaded_versions()
                report['meta']['prompt_provenance'] = prompts.usage_summary()
                Path(args.out).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
            passed = sum(r['score'] for r in report['results'])
        seconds = [r['seconds'] for r in report['results']]
        report['summary'] = {'passed': passed, 'total': len(seconds), 'seconds': round(time.perf_counter() - started, 2),
                             'median_seconds': statistics.median(seconds) if seconds else None,
                             'p95_seconds': sorted(seconds)[max(0, int(len(seconds) * .95) - 1)] if seconds else None}
        report['model_calls'], report['supervisor_checks'] = calls, dict(audits)
        report['planner_checks'] = dict(planner_checks)
        report['supervisor_rejection_examples'] = audit_examples
        report['meta']['prompt_usage'] = prompts.loaded_versions()
        report['meta']['prompt_provenance'] = prompts.usage_summary()
        if report['meta']['state'] != 'stopped':
            report['meta']['state'] = 'complete'
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False), dict(audits), flush=True)
    return 130 if report['meta']['state'] == 'stopped' else int(passed != len(report['results']))


if __name__ == '__main__':
    raise SystemExit(main())
