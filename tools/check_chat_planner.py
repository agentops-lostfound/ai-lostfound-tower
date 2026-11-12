"""고정 500문항에 구조화·이전·악성 planner 대역을 적용한다. 실제 LLM/DB/클라우드 없음."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('기존 검증 기록은 덮어쓰지 않습니다')
    from agents.chat_agents import AgentBrain
    from agents.chat_planner import instruction_for
    from agents.chat_api import build_chatbot_from_env
    from evaluation.chat_eval import QUESTIONS, Runner
    from tools.validate_chat_datasets import isolated_env
    original_plan = AgentBrain.plan_contract
    rows = []
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'agents/chat_planner.py', 'agents/chat_agents.py', 'agents/chatbot.py', 'agents/prompts.py',
        'evaluation/chat_eval.py', 'tools/check_chat_planner.py')}
    items = json.loads(QUESTIONS.read_text(encoding='utf-8'))
    for mode in ('structured_guidance', 'structured_both', 'bounded_legacy', 'hostile'):
        audits = Counter()
        def request(payload):
            if 'steps' not in payload.get('format', {}).get('properties', {}):
                raise OSError('only planner simulated')
            if mode == 'hostile':
                value = {'version': 2, 'steps': [{'worker': 'intake', 'task': 'save', 'input_ref': 'question'}]}
            elif mode == 'bounded_legacy':
                value = {'steps': ['item_search', 'guidance']}
            else:
                workers = ['guidance'] if mode == 'structured_guidance' else ['item_search', 'guidance']
                value = {'version': 2, 'steps': [instruction_for(w, len(workers) > 1).public_contract() for w in workers]}
            return {'message': {'content': json.dumps(value)}}
        def factory(*a, **kw):
            bot = build_chatbot_from_env(*a, **kw)
            bot.brain = AgentBrain('simulated-planner', request=request)
            return bot
        def plan_contract(brain, *a, **kw):
            decision = original_plan(brain, *a, **kw)
            audits[decision.audit['validation'] + ':' + decision.audit['reason']] += 1
            return decision
        with mock.patch.dict(os.environ, isolated_env(), clear=True), \
             mock.patch('agents.chat_api.build_chatbot_from_env', factory), \
             mock.patch.object(AgentBrain, 'plan_contract', plan_contract):
            runner = Runner()
            results = [runner.run_item(item) for item in items]
        row = {'mode': mode, 'passed': sum(r['score'] for r in results), 'total': len(results),
               'planner_checks': dict(audits), 'failures': [r for r in results if not r['score']]}
        rows.append(row)
        print(mode, row['passed'], '/', row['total'], dict(audits), flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({'kind': 'simulated_planner_not_real_llm', 'runs': rows,
            'meta': {'state': 'complete' if mode == 'hostile' else 'running', 'source_sha256': sources},
            'questions_sha256': hashlib.sha256(QUESTIONS.read_bytes()).hexdigest()},
            ensure_ascii=False, indent=2), encoding='utf-8')
    return int(any(row['failures'] for row in rows))


if __name__ == '__main__':
    raise SystemExit(main())
