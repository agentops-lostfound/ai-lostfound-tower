"""Planner의 읽기 작업·입력 참조 계약. SQL·인증·저장 인자는 받지 않는다."""
from dataclasses import asdict, dataclass


WORK_TASKS = {'guidance': 'answer_guidance', 'item_search': 'search_candidates'}
WORK_INPUTS = {'guidance': ('question', 'guidance_part'), 'item_search': ('question', 'search_part')}


@dataclass(frozen=True)
class WorkInstruction:
    worker: str
    task: str
    input_ref: str

    def public_contract(self):
        return asdict(self)


@dataclass(frozen=True)
class PlanningDecision:
    instructions: tuple[WorkInstruction, ...]
    audit: dict

    @property
    def workers(self):
        return tuple(step.worker for step in self.instructions)


def instruction_for(worker, combined=False):
    if worker not in WORK_TASKS:
        raise ValueError('unknown_worker')
    return WorkInstruction(worker, WORK_TASKS[worker], WORK_INPUTS[worker][int(bool(combined))])


def allowed_instructions():
    return [WorkInstruction(worker, task, ref).public_contract()
            for worker, task in WORK_TASKS.items() for ref in WORK_INPUTS[worker]]


def allowed_plans():
    """배열 요소를 따로 조합하지 않고 유효한 완성 계획 하나를 고르게 한다."""
    return [{'version': 2, 'steps': [instruction_for(worker, len(workers) > 1).public_contract()
                                     for worker in workers]}
            for workers in (('guidance',), ('item_search',), ('item_search', 'guidance'))]


def output_schema():
    return {'type': 'object', 'additionalProperties': False, 'required': ['version', 'steps'],
            'enum': allowed_plans(),
            'properties': {'version': {'type': 'integer', 'enum': [2]},
                'steps': {'type': 'array', 'minItems': 1, 'maxItems': 2, 'items': {
                    'type': 'object', 'additionalProperties': False,
                    'required': ['worker', 'task', 'input_ref'], 'enum': allowed_instructions(),
                    'properties': {'worker': {'type': 'string', 'enum': list(WORK_TASKS)},
                        'task': {'type': 'string', 'enum': list(WORK_TASKS.values())},
                        'input_ref': {'type': 'string', 'enum': ['question', 'guidance_part', 'search_part']}}}}}}


def parse_proposal(value):
    """이전 production의 일꾼 목록은 좁은 v1 변환만 허용한다. 임의 지시 글은 거절한다."""
    if type(value) is not dict:
        raise ValueError('invalid_plan_shape')
    legacy = set(value) == {'steps'}
    if not legacy and (set(value) != {'version', 'steps'} or type(value['version']) is not int or value['version'] != 2):
        raise ValueError('invalid_plan_version_or_fields')
    steps = value.get('steps')
    if type(steps) is not list or not 1 <= len(steps) <= 2:
        raise ValueError('invalid_plan_size')
    instructions = []
    for step in steps:
        if legacy:
            if type(step) is not str or step not in WORK_TASKS:
                raise ValueError('invalid_legacy_worker')
            instruction = instruction_for(step)
        else:
            if type(step) is not dict or set(step) != {'worker', 'task', 'input_ref'}:
                raise ValueError('invalid_instruction_fields')
            if not all(type(value) is str for value in step.values()) or step not in allowed_instructions():
                raise ValueError('invalid_instruction_combination')
            instruction = WorkInstruction(**step)
        if instruction.worker in [existing.worker for existing in instructions]:
            raise ValueError('duplicate_worker')
        instructions.append(instruction)
    return (1 if legacy else 2), tuple(instructions)


def safe_proposal(value):
    """trace에도 원문 모델 출력/알 수 없는 필드를 남기지 않는다."""
    try:
        version, instructions = parse_proposal(value)
        return {'version': version, 'steps': [step.public_contract() for step in instructions]}
    except ValueError as error:
        return {'valid': False, 'reason': str(error)}
