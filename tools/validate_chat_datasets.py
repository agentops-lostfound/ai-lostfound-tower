"""누적 가상 평가 데이터 무결성/전체 규칙 회귀. .env·기존 엑셀·원본 평가 기록을 변경하지 않는다."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
KST = dt.timezone(dt.timedelta(hours=9))


def isolated_env():
    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'TEMP', 'TMP', 'PATH') if k in os.environ}
    env.update(PYTHONUTF8='1', LF_LANGFUSE='0', TOWER_SIM='1', TOWER_SIM_DB='0',
               TOWER_SIM_SEED='full', TOWER_SIM_SPEED='0', TOWER_GPU_LEASE='0', TOWER_SEND='0',
               TOWER_AGENT_TALK='0', LF_AGENT_SUPERVISOR_USE_LLM='0')
    return env


def score_value(record):
    if 'score' in record and type(record['score']) in (int, bool) and record['score'] in (0, 1):
        return int(record['score'])
    if type(record.get('ok')) is bool:
        return int(record['ok'])
    return None


def audit_file(path, root):
    row = {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'errors': []}
    raw = path.read_bytes()
    row['sha256'] = hashlib.sha256(raw).hexdigest()
    try:
        if path.suffix == '.csv':
            with path.open(encoding='utf-8-sig', newline='') as stream:
                records = list(csv.reader(stream, strict=True))
            row.update(kind='csv', records=max(0, len(records) - 1))
            if not records:
                row['errors'].append('empty_csv')
            elif len(records[0]) != len(set(records[0])):
                row['errors'].append('duplicate_csv_header')
            return row
        obj = json.loads(raw.decode('utf-8-sig'))
        if isinstance(obj, dict) and isinstance(obj.get('meta'), dict):
            state = obj['meta'].get('state')
            if state in ('running', 'stopped', 'error'):
                row['completion_state'] = state
                row['warnings'] = ['partial_run']
        records = obj if isinstance(obj, list) else obj.get('results') if isinstance(obj, dict) else None
        row.update(kind=type(obj).__name__, records=len(records) if isinstance(records, list) else None)
        if isinstance(records, list):
            numbers = [r.get('no') for r in records if isinstance(r, dict) and 'no' in r]
            if any(type(n) is not int for n in numbers):
                row['errors'].append('invalid_case_number')
            elif len(numbers) != len(set(numbers)):
                row['errors'].append('duplicate_case_number')
            scores = [score_value(r) for r in records if isinstance(r, dict)]
            if scores and len(scores) == len(records) and all(s is not None for s in scores):
                row['passed'] = sum(scores)
                summary = obj.get('summary', {}) if isinstance(obj, dict) else {}
                if not isinstance(summary, dict):
                    row['errors'].append('invalid_summary_shape')
                    summary = {}
                if 'total' in summary and summary['total'] != len(records):
                    row['errors'].append('summary_total_mismatch')
                if 'passed' in summary and summary['passed'] != sum(scores):
                    row['errors'].append('summary_passed_mismatch')
        if path.name == 'chat_eval_500.json':
            valid_numbers = (isinstance(records, list) and len(numbers) == 500
                             and all(type(n) is int for n in numbers))
            if not isinstance(records, list) or len(records) != 500 or not valid_numbers or set(numbers) != set(range(1, 501)):
                row['errors'].append('invalid_500_case_coverage')
            elif sum(r.get('lf') is True for r in records) != 50:
                row['errors'].append('invalid_fixed_50_coverage')
            if isinstance(records, list) and any(not isinstance(r, dict) or not isinstance(r.get('turns'), list)
                                                or not r['turns'] for r in records):
                row['errors'].append('invalid_case_turns')
    except (ValueError, UnicodeError, csv.Error, TypeError):
        row['errors'].append('invalid_' + path.suffix.lstrip('.'))
    return row


def audit_all(root):
    paths = []
    for folder in ('evaluation', 'docs/reports'):
        base = root / folder
        if base.exists():
            paths.extend(p for p in base.rglob('*') if p.is_file() and p.suffix in ('.json', '.csv'))
    return [audit_file(path, root) for path in sorted(paths)]


def save_report(path, report):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)


def check_guidance(item, result):
    reasons = []
    if result.get('status') != item.get('expected_status'):
        reasons.append('expected_status_mismatch')
    found = {s.get('topic') for s in result.get('sources', []) if isinstance(s, dict)}
    if not set(item.get('expected_topics', [])) <= found:
        reasons.append('expected_topics_missing')
    return reasons


def guidance_result(guide, question):
    """안내의 명시적 입력 거절도 평가 결과다. 개인정보 원문/예외 문구는 기록하지 않는다."""
    try:
        return guide.ask(question)
    except ValueError:
        return {'status': 'rejected', 'sources': [], 'answer': ''}
    except Exception as error:
        return {'status': 'error', 'sources': [], 'answer': '', 'error_type': type(error).__name__}


def run_rules(root, report, out, stop_file=None):
    from evaluation.chat_eval import Runner
    names = ('chat_eval_500.json', 'chat_integration_1111_cases.json',
             'chat_policy_1111_cases.json', 'chat_guidance_quality_cases.json')
    runner = Runner()
    for name in names:
        path = root / 'evaluation' / name
        if not path.exists():
            continue
        items = json.loads(path.read_text(encoding='utf-8'))
        suite = {'path': path.relative_to(root).as_posix(), 'expected': len(items), 'results': []}
        report['suites'].append(suite)
        for item in items:
            if stop_file is not None and stop_file.exists():
                report['meta']['state'] = 'stopped'
                save_report(out, report)
                return False
            result = runner.run_item(item)
            suite['results'].append(result)
            if not result['score']:
                print(name, item['no'], 'FAIL', result['why'][:2], flush=True)
            if len(suite['results']) % 25 == 0:
                save_report(out, report)
                print(name, len(suite['results']), '/', len(items), flush=True)
        suite['passed'] = sum(r['score'] for r in suite['results'])
        print(name, suite['passed'], '/', len(items), flush=True)
        save_report(out, report)
    from agents.guidance import Guidance
    from agents.chat_api import build_chatbot_from_env
    from tools.chat_live_check import check as check_live
    guide, bot = Guidance(), None
    for name in ('guidance_questions.json', 'chat_live_questions.json'):
        path = root / 'evaluation' / name
        if not path.exists():
            continue
        items = json.loads(path.read_text(encoding='utf-8'))
        suite = {'path': path.relative_to(root).as_posix(), 'expected': len(items), 'results': []}
        report['suites'].append(suite)
        for number, item in enumerate(items, 1):
            if stop_file is not None and stop_file.exists():
                report['meta']['state'] = 'stopped'
                save_report(out, report)
                return False
            if name == 'guidance_questions.json':
                result = guidance_result(guide, item['question'])
                reasons = check_guidance(item, result)
            else:
                bot = bot or build_chatbot_from_env()
                result = bot.ask(item['q'], history=item.get('history') or [], session_id=f'cumulative-{number:03d}')
                reasons = check_live(item, result)
            suite['results'].append({'no': number, 'score': int(not reasons), 'why': reasons,
                                     'status': result.get('status'), 'answer': result.get('answer', '')[:400]})
            if reasons:
                print(name, number, 'FAIL', reasons[:2], flush=True)
        suite['passed'] = sum(r['score'] for r in suite['results'])
        print(name, suite['passed'], '/', len(items), flush=True)
        save_report(out, report)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=('audit', 'rules'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--stop-file')
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        parser.error('기존 검증 기록은 덮어쓰지 않습니다. 새 출력 이름을 지정해주세요')
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {'meta': {'mode': args.mode, 'data': 'synthetic_evaluation_assets', 'state': 'running',
        'started': dt.datetime.now(KST).isoformat(), 'langfuse': False}, 'audit': [], 'suites': []}
    source_names = ('agents/guidance.py', 'agents/chat_rag.py', 'agents/chatbot.py',
                    'agents/chat_api.py', 'agents/chat_intake.py', 'agents/chat_identity_evidence.py',
                    'evaluation/chat_eval.py', 'tools/chat_live_check.py', 'tools/validate_chat_datasets.py')
    report['meta']['source_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                      for name in source_names if (ROOT / name).is_file()}
    for name in ('agents/chat_planner.py', 'agents/chat_agents.py', 'agents/ops_analyst.py'):
        report['meta']['source_sha256'][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    try:
        report['meta']['commit'] = subprocess.check_output(['git', '-c', f'safe.directory={ROOT.as_posix()}',
            'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['meta']['tracked_changes'] = bool(subprocess.check_output(['git', '-c',
            f'safe.directory={ROOT.as_posix()}', 'status', '--porcelain', '--untracked-files=no'],
            cwd=ROOT, text=True).strip())
    except Exception:
        report['meta']['commit'] = 'unknown'
    started = time.perf_counter()
    report['audit'] = audit_all(ROOT)
    complete = True
    with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, isolated_env(), clear=True):
        os.environ['TOWER_CHAT_DEMO_DB'] = str(Path(temporary) / 'demo.sqlite3')
        if args.mode == 'rules':
            complete = run_rules(ROOT, report, out, Path(args.stop_file) if args.stop_file else None)
    results = [r for suite in report['suites'] for r in suite['results']]
    report['summary'] = {'audited_files': len(report['audit']),
        'invalid_files': sum(bool(r['errors']) for r in report['audit']),
        'partial_files': sum(bool(r.get('warnings')) for r in report['audit']),
        'cases': len(results), 'passed': sum(r['score'] for r in results),
        'seconds': round(time.perf_counter() - started, 3)}
    report['meta']['state'] = 'complete' if complete else 'stopped'
    save_report(out, report)
    print(json.dumps(report['summary'], ensure_ascii=False), flush=True)
    if not complete:
        return 130
    return int(report['summary']['invalid_files'] > 0 or report['summary']['passed'] != len(results))


if __name__ == '__main__':
    raise SystemExit(main())
