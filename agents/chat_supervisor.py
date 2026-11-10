"""LF-5 감독 행동 계약과 실행 검사. 모델 출력은 명령이 아닌 제안이다.

후보는 서버가 업무 상태로 만든다. 모델은 후보의 action/step/agent만
반환하며 저장 인자·SQL·사용자 질문·새 작업 문장을 만들 수 없다.
"""
from __future__ import annotations

ACTIONS = ('run_step', 'ask_user', 'add_step', 'replan', 'finish')
FIELDS = {'action', 'step', 'agent'}
AGENTS = ('', 'researcher', 'item_search', 'intake', 'ops_analyst', 'reporter')


def proposal(action, step=0, agent=''):
    return {'action': action, 'step': step, 'agent': agent}


def candidates(steps, *, stop=False, reported=False, executions=0, limit=6,
               intake_allowed=False, ops_allowed=False):
    """안전 조건을 먼저 적용. 미완료 필수 단계를 모델이 건너뛸 수 없다."""
    if reported:
        return [proposal('finish')]
    if stop:
        return [proposal('ask_user')]
    if executions >= limit:
        return [proposal('finish')]
    pending = [x for x in steps if x['status'] == 'todo']
    if not pending:
        return [proposal('finish')]
    x = pending[0]
    agent = x['agent']
    if agent == 'intake' and not intake_allowed:
        return [proposal('ask_user')]
    if agent == 'ops_analyst' and not ops_allowed:
        return [proposal('finish')]
    # 독립적인 읽기 작업끼리는 모델이 순서를 판단할 수 있다. 필수 작업은 삭제 불가.
    choices = pending if all(p['agent'] in ('researcher', 'item_search') for p in pending) else [x]
    out = []
    for x in choices:
        action = 'run_step'
        if x.get('by') == 'supervisor':
            action = 'replan' if x.get('note') == 'replan_item_search' else 'add_step'
        out.append(proposal(action, x['no'], x['agent']))
    return out


def validate(raw, allowed):
    """JSON schema에만 의존하지 않고 실행 직전 형식·후보 일치를 검사한다."""
    if not isinstance(raw, dict) or set(raw) != FIELDS:
        return False, 'invalid_shape'
    if raw.get('action') not in ACTIONS:
        return False, 'unknown_action'
    if type(raw.get('step')) is not int or raw['step'] < 0 or not isinstance(raw.get('agent'), str):
        return False, 'invalid_field_type'
    if raw not in allowed:
        return False, 'state_or_permission_denied'
    return True, 'accepted'


def output_schema(allowed):
    """후보 객체 전체를 enum으로 고정해 다른 후보의 필드를 섞을 수도 없게 한다.

    필드별 enum만 쓰면 (검색,1)/(안내,2)에서 (검색,2)가 나올 수 있다.
    root enum은 올바른 조합만 허용한다. 최종 validate는 별도로 유지한다.
    """
    if not isinstance(allowed, list) or not allowed:
        raise ValueError('supervisor candidates must not be empty')
    for x in allowed:
        if not validate(x, [x])[0] or x['agent'] not in AGENTS:
            raise ValueError('invalid supervisor candidate')
    values = [dict(x) for x in allowed]
    return {'type': 'object', 'additionalProperties': False,
            'required': ['action', 'step', 'agent'],
            'properties': {'action': {'type': 'string', 'enum': list(dict.fromkeys(x['action'] for x in values))},
                           'step': {'type': 'integer', 'enum': list(dict.fromkeys(x['step'] for x in values))},
                           'agent': {'type': 'string', 'enum': list(dict.fromkeys(x['agent'] for x in values))}},
            'enum': values}


def safe_proposal(raw):
    """추적에는 계약 필드의 알려진 값만. 임의 문자열은 보관하지 않는다."""
    safe = None
    if isinstance(raw, dict):
        safe = {k: raw.get(k) for k in FIELDS
                if (k == 'action' and raw.get(k) in ACTIONS)
                or (k == 'step' and type(raw.get(k)) is int and 0 <= raw[k] <= 100)
                or (k == 'agent' and raw.get(k) in ('', 'researcher', 'item_search', 'intake', 'ops_analyst', 'reporter'))}
    return safe


def decide(brain, allowed, context):
    """실패하면 서버 후보 사용. 모델 원문·민감값은 반환/추적하지 않는다."""
    raw, failure = None, 'model_unavailable'
    call = getattr(brain, 'supervise', None)
    if callable(call):
        try:
            raw = call(allowed, context)
        except Exception:
            failure = 'model_error'
    accepted, reason = validate(raw, allowed)
    chosen = dict(raw if accepted else allowed[0])
    audit = {'proposal': safe_proposal(raw), 'validation': 'accepted' if accepted else 'rejected',
             'reason': reason if raw is not None else failure,
             'executed': chosen, 'source': 'model' if accepted else 'code_fallback'}
    return chosen, audit
