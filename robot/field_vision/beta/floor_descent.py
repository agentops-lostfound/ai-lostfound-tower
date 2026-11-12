"""Wide flat items: lower the open jaw until the fingertips are LOW ENOUGH (v0.2.41).

Audit B18-B20/B23 (Fable + Codex). FK alone cannot tell a servo dead zone, friction
stall and board support apart (flow-dbb9d941: 4mm command -> 0.57mm; flow-8a3571cc:
0.27mm command -> 0mm), so the decision is "is the measured fingertip height within
LOW_MM of the board", and contact is only a recorded candidate.

Callbacks: goal_for(z) -> joint goal (raises ValueError when IK fails, which is
'ik_limit', never contact); move(goal, z, label) -> measured TCP z after the move
(STOP / timeout errors propagate); read_z() -> measured TCP z.
"""
STEP_MM=2.          # fixed ladder below the planned grasp height
BELOW_GRASP_MM=12.  # command never below grasp_z - 12
CMD_FLOOR_MM=8.     # ... nor below plane - 8
FB_FLOOR_MM=6.      # feedback below plane - 6: model/reality mismatch, end at once
TARGET_MM=1.        # stop descending once feedback <= plane + 1 (v0.2.42)
LOW_MM=3.           # reached <= plane + 3 counts as low enough -> no warning (FK plane error ~mm)
LAG_MM=3.;STALL_MM=.5;MIN_DROP_MM=2.
RETRY_LIFT_MM=10.;RETRY_TARGET_MM=1.
RELEASE_LAG_MM=1.;RELEASE_MM=.5


def command_floor(grasp_z,plane):
    return max(grasp_z-BELOW_GRASP_MM,plane-CMD_FLOOR_MM)


def ladder(grasp_z,plane):
    floor=command_floor(grasp_z,plane);zs=[];z=grasp_z-STEP_MM
    while z>floor+1e-6:zs.append(z);z-=STEP_MM
    if floor<grasp_z-1e-6 and (not zs or zs[-1]>floor+1e-6):zs.append(floor)
    return zs


def contact_candidate(steps,start_z,plane):
    if len(steps)<2:return False
    a,b=steps[-2],steps[-1]
    return (b['feedback_z']<=plane+LOW_MM and start_z-b['feedback_z']>=MIN_DROP_MM
            and all(s['drop_mm']<STALL_MM and s['lag_mm']>=LAG_MM for s in (a,b)))


def descend(grasp_z,plane,goal_for,move,read_z,log=lambda *_:None):
    """Returns a record; result['abort'] (a reason string) means: do NOT close, lift
    and stop. Caller must check it (v0.2.42, Codex review of v0.2.41)."""
    start=float(read_z());prev=start;steps=[];status='floor_limit';error=None;last_cmd=None
    for z in ladder(grasp_z,plane):
        try:goal=goal_for(z)
        except ValueError as exc:status='ik_limit';error=str(exc);break
        fb=float(move(goal,z,'바닥까지 추가 하강 · 계획 높이 %.0fmm'%(z-grasp_z)));last_cmd=z
        steps.append({'commanded_z':z,'feedback_z':fb,'lag_mm':fb-z,'drop_mm':prev-fb});prev=fb
        if fb<plane-FB_FLOOR_MM:status='below_floor';break
        # v0.2.42: the target is the board (plane + 1mm), not "until held up": stop
        # as soon as it is reached. The +3mm window only decides the warning.
        if fb<=plane+TARGET_MM:status='target';break
        if contact_candidate(steps,start,plane):status='contact';break
    result={'status':status,'start_z':start,'plane_z':plane,'command_floor_z':command_floor(grasp_z,plane),
            'target_z':plane+TARGET_MM,'low_window_z':plane+LOW_MM,'steps':steps,'ik_error':error,'abort':None}
    stalled_high=status in ('floor_limit','ik_limit') and prev>plane+LOW_MM
    result['stalled_high']=stalled_high
    if stalled_high and status=='floor_limit':
        # One deliberate long move crosses the dead zone: +10mm, then straight to plane+1.
        retry={'from_z':prev}
        up=prev+RETRY_LIFT_MM;down=max(plane+RETRY_TARGET_MM,command_floor(grasp_z,plane))
        # Only goal_for (IK) errors are caught; move errors (STOP/timeout) propagate.
        try:goals=[goal_for(up),goal_for(down)]
        except ValueError as exc:goals=None;retry['ik_error']=str(exc)
        if goals:
            retry['up_feedback_z']=float(move(goals[0],up,'바닥 정체 · 10mm 올렸다가 다시 하강'))
            prev=float(move(goals[1],down,'바닥 정체 · 판 +1mm까지 한 번에 하강'));last_cmd=down
            retry.update(commanded_z=down,feedback_z=prev)
            # Same absolute lower bound after the retry (v0.2.42).
            if prev<plane-FB_FLOOR_MM:status=result['status']='below_floor'
        result['retry']=retry
    # Judge the REACHED height, before the +0.5mm release below. Too low is NOT
    # 'low enough': it is a failure (high -> warn and close; too low -> stop).
    result['reached_z']=prev
    result['too_low']=bool(prev<plane-FB_FLOOR_MM)
    result['low_enough']=bool(plane-FB_FLOOR_MM<=prev<=plane+LOW_MM)
    if result['too_low']:result['abort']='판보다 %.1fmm 아래로 측정됨 · 모델/실제 불일치'%(plane-prev)
    # Never stay pressed: whatever ended the loop, a feedback held >1mm above the
    # command is released to feedback + 0.5mm, and the release is VERIFIED.
    if last_cmd is not None and prev-last_cmd>RELEASE_LAG_MM:
        target=prev+RELEASE_MM
        try:goal=goal_for(target)
        except ValueError as exc:
            goal=None;result['release_error']=str(exc)
            result['abort']=result['abort'] or '눌림 해제 자세 계산 실패'
        if goal is not None:
            after=float(move(goal,target,'눌림 해제 · 실제 높이 +0.5mm'))
            result.update(released_to_z=target,release_feedback_z=after,release_lag_mm=after-target)
            # Still held >1mm above the new command = still pressed.
            if after-target>RELEASE_LAG_MM:result['abort']=result['abort'] or '눌림 해제 미확인 (명령보다 %.1fmm 위)'%(after-target)
            prev=after
    result['final_z']=prev
    return result


OVERLAP_PX=-8.


def verdict(floor,gap=None,gap_checked=True):
    """What the caller does after the floor descent: ('stop'|'warn_close'|'close', reason).
    gap = fixed_gap result after the descent, None when it could not be measured."""
    if floor.get('abort'):return 'stop','바닥 하강 실패: '+floor['abort']
    if gap_checked:
        if gap is None:return 'stop','바닥 하강 후 고정 손가락 간격을 확인하지 못함'
        if gap['gap_px']<OVERLAP_PX:return 'stop','바닥 하강 후 고정 손가락이 물체 경계 안쪽(%.1fpx)'%gap['gap_px']
    if not floor['low_enough']:
        return 'warn_close','바닥까지 충분히 내려가지 못함(판+%.1fmm > +%.0fmm) · 경고 후 닫기'%(floor['reached_z']-floor['plane_z'],LOW_MM)
    return 'close',''
