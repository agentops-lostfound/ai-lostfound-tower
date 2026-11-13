"""회귀용 연속 대화 실행기. 운영 설정/실물/외부 알림 없이 합성 창구만 사용한다."""
import copy
import tempfile
from pathlib import Path


class Desk:
    def __init__(self):
        self.calls, self.wait_state = [], 'waiting'

    def found(self, text):
        self.calls.append('found')
        return {'item_id': 'S-20261113-8001', 'story_id': 'synthetic-found'}

    def lost(self, text, opts):
        self.calls.append('lost')
        return {'claim_id': 'C-20261113-8001', 'item_id': 'S-20261113-8001', 'quiz_passed': True}

    def wait_status(self, wid):
        return {'state': self.wait_state, **({'claim_id': 'C-20261113-8001', 'item_id': 'S-20261113-8001'} if self.wait_state == 'matched' else {})}


def snapshot(bot, sid):
    active = bot.intake.active(sid)
    if not active:
        return None
    return {k: copy.deepcopy(active.get(k)) for k in ('stage', 'asked', 'kind', 'version', 'slots')}


def run_case(case):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agents.chat_api import add_chat_routes, build_chatbot_from_env
    from agents.chat_search import DemoItemDatabase
    with tempfile.TemporaryDirectory() as tmp:
        desk = Desk()
        bot = build_chatbot_from_env(DemoItemDatabase(Path(tmp)/'items.sqlite'), desk=desk)
        app = FastAPI()
        add_chat_routes(app, chatbot=bot)
        histories, proofs, failures = {}, {}, []
        with TestClient(app) as client:
            for i, step in enumerate(case['turns']):
                who = step.get('who', 'A')
                sid = 'repair-'+case['id']+'-'+who
                before = snapshot(bot, sid)
                history = histories.setdefault(who, [])
                if 'wait_state' in step:
                    desk.wait_state = step['wait_state']
                body = {'question': step['q'], 'session_id': sid, 'history': history[-4:]}
                if step.get('identity'):
                    body['intake_action'] = {'type': 'identity', 'name_masked': '가*인', 'id_no_masked': '******-1******'}
                if step.get('confirm') and who in proofs:
                    body['intake_action'] = proofs[who]
                response = client.post('/chat/questions', json=body)
                r = response.json()
                after, why, answer = snapshot(bot, sid), [], r.get('answer', '')
                if r.get('confirmation'):
                    proofs[who] = copy.deepcopy(r['confirmation'])
                topics = [s['topic'] for s in r.get('sources', [])]
                if response.status_code != 200:
                    why.append('HTTP '+str(response.status_code))
                if step.get('preserve') and (not before or before != after):
                    why.append('draft_changed')
                for key, observed in (('asked', (r.get('intake') or {}).get('asked')), ('kind', (after or {}).get('kind')), ('status', r.get('status'))):
                    if key in step and observed != step[key]:
                        why.append(key)
                for key, expected in step.get('slots', {}).items():
                    if (after or {}).get('slots', {}).get(key) != expected:
                        why.append('slot:'+key)
                for key, expected in step.get('filter', {}).items():
                    if r.get('search_filter', {}).get(key) != expected:
                        why.append('filter:'+key)
                for topic in step.get('topics', [])+([step['topic']] if 'topic' in step else []):
                    if topic not in topics:
                        why.append('topic:'+topic)
                if step.get('no_topic') in topics:
                    why.append('negated_topic')
                if 'search' in step and bool(r.get('item_search_performed')) != step['search']:
                    why.append('search')
                if 'writes' in step and len(desk.calls) != step['writes']:
                    why.append('writes')
                if r.get('method') == 'receipt_next_step_guidance' and set(r.get('choices') or []) & {'분실 접수하기','습득 신고하기'}:
                    why.append('duplicate_intake_offer_after_receipt')
                if step.get('privacy') and not all(s in answer for s in ('실제', '개인정보', '가상')):
                    why.append('privacy')
                if step.get('pickup') and not all(s in answer for s in ('키오스크', '확인', '물건 받았어요')):
                    why.append('pickup')
                if any(s not in answer for s in step.get('contains', [])):
                    why.append('contains')
                if step.get('contains_any') and not any(s in answer for s in step['contains_any']):
                    why.append('contains_any')
                if why:
                    failures.append({'turn': i+1, 'q': step['q'], 'why': why, 'answer': answer})
                history.append({'q': step['q'], 'a': answer[:300]})
        return failures
