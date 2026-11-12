"""Validated one-shot following compensation at approach and descent endpoints."""
import math
import numpy as np
from .approach_path import context,SIGN,pose
from .kinematics import NAMES
from .following_compensation import move_with_compensation
from .robot_actions import MotionAborted,validate_goal


def verify_stage_position(actual,target,*,descent=False,plane_z=15):
    delta=np.asarray(actual,float)-np.asarray(target,float)
    # Near contact: never allow the general +/-4mm allowance below the target.
    # Approach is ~45mm above the object and is followed by ARM-image gap
    # measurement, so 6mm is safe there. flow-ac8bda80: elbow compensation
    # shifted load and shoulder_lift sagged 5->12 ticks (XY 4.1/Z -4.3mm),
    # failing a 3/4mm approach check. Descent near contact stays strict.
    xy_limit=3 if descent else 6
    lower=max(float(target[2])-1,plane_z-3) if descent else float(target[2])-6
    upper=4 if descent else 6
    # v0.2.36: only being BELOW the safe floor stops (board/object strike). XY and
    # 'too high' are warnings; the ARM gap re-measurement decides the grasp.
    # The FK board height is not exact (fingertips still above the real board at
    # plane-2mm, 2026-11-11), so the descent floor is relative to the target.
    floor=float(target[2])-8 if descent else plane_z+10
    if actual[2]<floor:raise MotionAborted('집게가 목표보다 8mm 이상 아래 · 정지')
    warning=bool(np.linalg.norm(delta[:2])>xy_limit or actual[2]<lower or delta[2]>upper)
    return {'delta_mm':delta.tolist(),'xy_mm':float(np.linalg.norm(delta[:2])),'minimum_z_mm':lower,'xy_limit_mm':xy_limit,'warning':warning}


def checked_stage_move(actions,reference,nominal,label,target_xyz,plane_z,*,descent=False,log=lambda *_:None,max_tilt_deg=10):
    nominal=dict(nominal);target_xyz=np.asarray(target_xyz,float)
    def move(goal,compensated):
        actions.move(goal,label+(' · 추종 보정1회' if compensated else ''),arrival_mode='settled',
                     arrival_tolerance_ticks=46,target_height_mm=float(target_xyz[2]))
    def validate(goal,feedback):
        validate_goal(goal,feedback)
        model,q,r,q0=context(reference,feedback)
        def angles(t):return q0+(np.array([t[n] for n in NAMES])-r)*SIGN*2*np.pi/4096
        nq=angles(nominal);cq=angles(goal);bias=q-nq
        actual_start=model.forward(q,with_points=False)['position']
        floor=target_xyz[2]-8 if descent else plane_z+20
        if actual_start[2]<floor:raise ValueError('보정 시작 위치가 하강 하한 아래 · 추가 이동 중단')
        # Nominal-biased response predicts physical motion; raw command also
        # gets a floor check, so extra compensation cannot request a floor strike.
        for start,end in [(q,cq+bias),(nq,cq)]:
            for t in np.linspace(0,1,101):
                f=model.forward(start+(end-start)*t,with_points=False);xyz=f['position']
                if xyz[2]<floor or xyz[2]>max(actual_start[2],target_xyz[2])+12 or -f['tool_axis'][2]<math.cos(math.radians(max_tilt_deg)):
                    raise ValueError('추종 보정 경로의 높이/%g도 검사 실패'%max_tilt_deg)
    # Distinguish completed validation failures from move()/communication faults.
    completed=[False]
    def guarded_move(goal,compensated):
        completed[0]=False
        move(goal,compensated)
        completed[0]=True
    try:
        feedback=move_with_compensation(nominal,guarded_move,actions.check,validate,log)
        actual=pose(reference,feedback)['xyz_mm']
        result=verify_stage_position(actual,target_xyz,descent=descent,plane_z=plane_z)
        log(dict(stage=label,nominal=nominal,actual_xyz_mm=actual,**result))
        return feedback
    except ValueError as exc:
        if completed[0]:raise MotionAborted(str(exc)) from exc
        raise
