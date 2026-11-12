"""500문항으로 감독 계약 회귀 검사. .env·실제 DB·LLM·Langfuse·엑셀을 사용하지 않는다.

python tools/check_chat_supervisor.py --out docs/reports/supervisor-check.json
모델 대역이 첫 후보/마지막 후보/악성 제안을 낼 때 기존 업무가 유지되는지 검사한다.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    from evaluation.chat_eval import QUESTIONS, Runner, SIM_ENV
    from agents.chat_api import build_chatbot_from_env
    from agents.chat_agents import AgentBrain
    rows = []
    env = {**SIM_ENV, 'LF_LANGFUSE': '0', 'TOWER_SIM_DB': '0', 'TOWER_CHAT_DEMO_DB': '0',
           'LF_AGENT_SUPERVISOR_USE_LLM': '1', 'SYSTEMROOT': os.environ.get('SYSTEMROOT', '')}
    for mode in ('rules', 'first', 'last', 'hostile'):
        def request(payload):
            if 'supervisor' not in payload['messages'][0]['content'][:80]:
                raise OSError('only supervisor simulated')
            user = json.loads(payload['messages'][1]['content'])
            allowed = user['allowed']
            value = ({'action': 'run_step', 'step': 1, 'agent': 'intake', 'save': True}
                     if mode == 'hostile' else allowed[-1 if mode == 'last' else 0])
            return {'message': {'content': json.dumps(value)}}
        def factory(*a, **kw):
            b = build_chatbot_from_env(*a, **kw)
            if mode != 'rules':
                b.brain = AgentBrain('simulated-supervisor', request=request)
            return b
        with mock.patch.dict(os.environ, env, clear=True), mock.patch('agents.chat_api.build_chatbot_from_env', factory):
            runner = Runner()
            results = [runner.run_item(item) for item in json.loads(QUESTIONS.read_text(encoding='utf-8'))]
        row = {'mode': mode, 'passed': sum(r['score'] for r in results), 'total': len(results),
               'failures': [r for r in results if not r['score']]}
        rows.append(row)
        print(mode, row['passed'], '/', row['total'], flush=True)
    Path(args.out).write_text(json.dumps({'kind': 'simulated_supervisor_not_real_llm', 'runs': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    return int(any(r['failures'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
