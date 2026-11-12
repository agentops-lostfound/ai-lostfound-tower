"""One feed-forward correction around an immutable nominal joint target."""
from .kinematics import NAMES


def over_limit(name,error):
    """error = nominal - actual. shoulder_lift sags under load (actual > nominal)
    by up to ~45 ticks at full reach (flow-c583e50c: 5.9mm lateral move, wrist_flex at
    its limit -> +45). Allow that sag direction to 60 ticks; FK checks still decide."""
    if name=='shoulder_lift' and -60<=error<0:return False
    return abs(error)>40


def compensated_goal(nominal,feedback):
    actual={j['name']:j['raw_ticks'] for j in feedback['joints']}
    errors={n:int(nominal[n]-actual[n]) for n in NAMES}
    if any(over_limit(n,e) for n,e in errors.items()):raise ValueError('정지 후 관절 오차가 보정 상한40틱 초과 · 하강 중단')
    correction={n:e if abs(e)>8 else 0 for n,e in errors.items()}
    if abs(errors['wrist_roll'])>8:raise ValueError('고정 손목 회전 추종 오차8틱 초과 · 방향 재확인 필요')
    correction['wrist_roll']=0
    goal=dict(nominal)
    for n,e in correction.items():goal[n]+=e
    # Wrist axis is verified before lateral adjustment and must stay held.
    return goal,correction


def move_with_compensation(nominal,move,read_state,validate,log=lambda *_:None):
    move(nominal,False)
    state=read_state()
    # v0.2.36: a compensation that is out of bounds or fails its path check is
    # SKIPPED (logged), not a stop. Position is then judged by the caller / ARM image.
    try:
        goal,correction=compensated_goal(nominal,state)
        if any(correction.values()):validate(goal,state)
    except ValueError as exc:
        log({'compensation_skipped':str(exc)})
        return state
    initial_error={j['name']:abs(nominal[j['name']]-j['raw_ticks']) for j in state['joints'] if j['name'] in NAMES}
    if any(correction.values()):
        log({'nominal':dict(nominal),'compensated':goal,'correction_ticks':correction})
        move(goal,True)
        state=read_state()
    actual={j['name']:j['raw_ticks'] for j in state['joints']}
    if any(abs(nominal[n]-actual[n])>=initial_error[n]-2 for n,c in correction.items() if c):
        # A small correction (e.g. elbow 16 ticks) can sit inside the loaded
        # servo's dead zone and not move at all (flow-6c36c759: 16 -> 15 ticks while
        # the TCP was within the approach limit, XY 5.5mm / Z -3.7mm). Do not stop on
        # joint numbers alone; the caller's FK position check decides
        # (approach 6mm, descent 3mm/+4-1mm, lateral height/side checks).
        log({'compensation_effective':False,'nominal':dict(nominal),'actual':actual,
             'note':'보정 명령에도 관절이 움직이지 않음 · 위치 판정은 FK 검사로'})
    # A compensation command must improve following of the ORIGINAL target.
    if any(over_limit(n,nominal[n]-actual[n]) for n in NAMES):log({'warning':'1회 추종 보정 후 원래 목표 오차40틱 초과','actual':actual})
    return state
