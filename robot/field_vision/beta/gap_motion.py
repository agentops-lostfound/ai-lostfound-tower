"""Feedback-mm verification after a settled lateral move, with one bounded retry."""
import numpy as np


def lateral_feedback_move(move_same_target,read_xyz,direction,command_mm,log=lambda *_:None,*,max_attempts=2,expected_z=None):
    direction=np.asarray(direction,float)
    origin=np.asarray(read_xyz(),float)
    along=0.
    for attempt in range(max_attempts):
        # The callback sends the SAME absolute target on retry. It never adds
        # the missing feedback amount onto the previously commanded target.
        move_same_target(attempt)
        now=np.asarray(read_xyz(),float);delta=now-origin
        along=float(delta@direction)
        sideways=float(np.linalg.norm(delta[:2]-direction[:2]*along))
        # Side drift (along the object's long edge) scales with long moves near a
        # joint limit (flow-d9aa72cd: wrist_flex at 3286, -11.25mm move drifted 4.15mm).
        # It does not change the measured gap; bound it relative to the move.
        side_limit=min(5.,max(3.,.45*abs(command_mm)))
        # Height: compare with the COMMANDED height when known. The origin is a
        # sagged feedback pose; returning toward the commanded height read as a
        # +7.9mm 'height error' (flow 19:29, shoulder sag 26->45 ticks).
        if expected_z is None:height=float(delta[2]);low,high=-4.,4.
        else:height=float(now[2]-expected_z);low,high=-6.,4.
        data=dict(attempt=attempt+1,command_mm=command_mm,along_mm=along,sideways_mm=sideways,height_mm=height,
                  height_reference='commanded' if expected_z is not None else 'origin',side_limit_mm=side_limit)
        log(data)
        # v0.2.36: only a height DROP toward the object stops. Side drift, wrong
        # direction and short travel are logged; the ARM camera re-measures the gap.
        # v0.2.43: flow-23834736 (phone at reach) sagged -6.7mm vs command at approach
        # height with the stop at -10mm. Approach height is ~45mm above the board and the
        # path itself is checked against plane+15, so stop only below -14mm (commanded).
        if height<low-8:raise ValueError('영상 보정 중 집게 높이 %.1fmm 하강 · 하강 중단'%height)
        if sideways>side_limit or height>high or height<low or along*np.sign(command_mm)<-.5:
            log(dict(warning=True,note='측면 이동 추종 오차 · 영상 간격 재측정으로 판단',sideways_mm=sideways,height_mm=height,along_mm=along))
        if along*command_mm>0 and abs(along)>=abs(command_mm)*.5:return along
    # A short FK-measured move under shoulder sag is not itself unsafe: the ARM
    # camera re-measures the gap next and decides (ensure_fixed_clearance).
    log(dict(short_move=True,command_mm=command_mm,along_mm=along,note='FK 이동량 50% 미만 · 영상 간격 재측정으로 판단'))
    return along
