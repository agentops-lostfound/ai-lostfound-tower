"""Approved DB target -> one taught route -> staff verification, with no fake grasp verdict."""
from __future__ import annotations

from dataclasses import dataclass, field
import os

from agents.contracts import DECISION_RETURNED, DECISION_STAFF, DECISION_STOPPED, HANDOVER_WAIT
from agents.supervisor import Outcome, new_ctx, web_gate, visit_gate, shelf_handover, _set_status, _stop


def enabled(env=None):
    env = os.environ if env is None else env
    mode = str(env.get('TOWER_ROBOT_SEQUENCE') or '').strip()
    if not mode:
        return False
    if mode != 'taught':
        raise ValueError('TOWER_ROBOT_SEQUENCE must be empty or taught')
    if (str(env.get('TOWER_ROBOT_TARGET') or '').strip().lower() != 'db'
            or env.get('TOWER_ROBOT_PART') != 'robot.remote_client:RemoteTowerRobot'):
        raise ValueError('Taught return requires DB targets and the explicit remote robot part')
    return True


def remote_part(env):
    """Construction only; never arm, connect or move on tower startup."""
    from robot.remote_client import RemoteTowerRobot
    part = RemoteTowerRobot(url=env.get('TOWER_REMOTE_ROBOT_URL', ''),
                           token=env.get('TOWER_REMOTE_ROBOT_TOKEN', ''),
                           expected_mode=env.get('TOWER_REMOTE_ROBOT_MODE') or 'live')
    if part.error:
        raise ValueError('Remote robot URL/token/mode configuration required')
    return part


@dataclass
class TaughtOutcome(Outcome):
    robot_sequence: dict = field(default_factory=dict)


def run_taught_return(req, backend, reporter, reviewer=None, consult=None, talk=None, slot_area=None):
    c = new_ctx(req, backend, reporter, reviewer, consult, talk, slot_area)
    c.out = TaughtOutcome(req.case_id, DECISION_STAFF, '')
    for gate in (web_gate, visit_gate, shelf_handover):
        if gate(c):
            return c.out
    from robot.db_pose_sequence import sequence_for_target
    try:
        target = req.robot_target
        if not isinstance(target, dict) or target.get('item_id') != req.item_id:
            raise ValueError('서버가 선택한 물건의 DB 칸이 필요합니다')
        sequence = sequence_for_target(target)
        run = getattr(backend, 'robot_run_sequence', None)
        if not callable(run):
            raise ValueError('로봇 부품에 티칭 시퀀스 실행 기능이 없습니다')
    except (ValueError, TypeError) as exc:
        c.finish(DECISION_STAFF, str(exc), alert=True)
        return c.out
    c.step('DB 칸 위치 사용(탑뷰 없음)', f"{target['slot_id']} · {target['pose_name']}")
    if not _set_status(c, '반환 중'):
        c.finish(DECISION_STAFF, '상태 기록 실패 — 로봇을 움직이지 않음', alert=True)
        return c.out
    # An ambiguous remote result may follow contact with the object. Never
    # restore its old shelf status or automatically repeat this whole route.
    c.grasp_started = True
    arrivals, events = [], []

    def progress(event):
        index = len(events) // 2 + 1
        kind = 'stage_started' if len(events) % 2 == 0 else 'stage_arrived'
        if (not isinstance(event, dict) or index > 11 or event.get('index') != index
                or event.get('total') != 11 or event.get('event') != kind
                or event.get('pose_name') != sequence[index - 1]):
            raise ValueError('시퀀스 진행 순서·도착 응답이 일치하지 않습니다')
        events.append(dict(event))
        if kind == 'stage_arrived':
            arrivals.append(event['pose_name'])
        c.step(f"티칭 {index}/11 · {event['pose_name']} · "
               + ('도착 확인' if kind == 'stage_arrived' else '이동 중'))
        board = getattr(reporter, 'board', None)
        if board:
            if index == 1 and kind == 'stage_started':
                for key in ('topview', 'match'):
                    board.stage(key, 'skip', '승인된 DB 칸 사용')
            key = 'approach' if index <= 2 else 'grasp' if index <= 6 else 'deliver'
            done = kind == 'stage_arrived' and index in (2, 6, 11)
            board.stage(key, 'done' if done else 'active',
                        f"{index}/11 · {event['pose_name']} · " + ('도착' if kind == 'stage_arrived' else '이동 중'))
    try:
        result = run(target, progress=progress)
        c.out.robot_sequence = {
            'slot_id': target['slot_id'], 'pose_name': target['pose_name'],
            'completed': list(arrivals), 'verification_required': True,
            'job_id': result.get('job_id') if isinstance(result, dict) else None,
            'failed_pose': result.get('failed_pose') if isinstance(result, dict) else None,
        }
        if (not isinstance(result, dict) or result.get('ok') is not True
                or result.get('test_only') is not False or result.get('motion_complete') is not True
                or result.get('item_id') != req.item_id or result.get('completed') != sequence
                or arrivals != sequence):
            why = result.get('reason') if isinstance(result, dict) else '결과 형식 오류'
            raise ValueError(why or '11단계 도착을 확인하지 못했습니다')
    except Exception as exc:
        c.out.robot_sequence.update(slot_id=target['slot_id'], completed=list(arrivals), verification_required=True)
        c.finish(DECISION_STOPPED, f'티칭 시퀀스 중단: {str(exc)[:160]}' + _stop(c), alert=True)
        return c.out
    c.step('티칭 시퀀스 완료', '11/11 · 홈 도착 · 실제 집기·배출은 직원 확인 필요')
    if not _set_status(c, HANDOVER_WAIT):
        c.finish(DECISION_STAFF, '시퀀스 완료 · 인계 대기 기록 실패 — 재실행 금지, 직원 확인', alert=True)
    else:
        c.finish(DECISION_RETURNED, '티칭 이동 완료 · 집기·배출 확인 및 직원 교차 검증 대기')
    return c.out


def configure(svc, env=None):
    if not enabled(env):
        return
    be = svc.backend_factory()
    fn = getattr(be, 'robot_run_sequence', None)
    if not callable(fn):
        raise ValueError('Taught return robot_run_sequence is missing')
    svc.flow = run_taught_return
    svc.taught_robot = True
