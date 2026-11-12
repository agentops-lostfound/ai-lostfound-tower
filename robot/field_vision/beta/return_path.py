"""Drop-off transfer (v0.2.46): one taught drop pose + a transfer height.

User model (2026-11-12): after the grasp, rise to a fixed transfer height, travel at that
height to above the drop point, descend straight down to the taught drop pose, open,
rise straight back up, return HOME. The drop pose is the user's taught joint pose
(workflow.dropoff_pose), so no board/TCP calibration error enters the drop position.
"""
import math
import numpy as np
from .approach_path import SIGN
from .kinematics import NAMES

LIFT_STEPS_MM=(30.,20.,10.)
LOADED_CLEARANCE_MM=10.  # held object's bottom above the board plane
EMPTY_CLEARANCE_MM=5.    # empty jaw tip above the board plane
DEFAULT_HANG_MM=30.      # assumed hang when no grasp has been measured (dry check)
TRAVEL_SAG_MM=20.        # joint-space travel may dip this much below the lower end
MIN_LIFT_MM=10.          # B2: refuse when even 10mm cannot be lifted


def to_q(ticks,r,q0):
    return q0+(np.array([ticks[n] for n in NAMES])-r)*SIGN*2*np.pi/4096


def to_ticks(q,r,q0):
    return np.rint(r+(np.asarray(q)-q0)*SIGN*4096/(2*np.pi)).astype(int)


def tcp_z(model,ticks,r,q0):
    return float(model.forward(to_q(ticks,r,q0),with_points=False)['position'][2])


def vertical_lift(model,r,q0,base_ticks,bounds,steps=LIFT_STEPS_MM):
    """Straight-up lift from the COMMANDED base pose (never feedback: shoulder sag ratchets).

    Tries each step (mm) in order. The joint-space path must rise monotonically, keep the
    tool axis within 15 deg and drift laterally at most max(3mm, 8% of the step).
    Returns (ticks, info) or raises ValueError. bounds: {name: (min_ticks, max_ticks)}.
    """
    start=to_q(base_ticks,r,q0);origin=model.forward(start,with_points=False)
    tried=[]
    for step in steps:
        target=origin['position']+np.array([0.,0.,step])
        try:
            solved=model.inverse(target,seed=start,fixed_roll=float(start[4]),prefer_seed=True)
        except ValueError as exc:
            tried.append({'mm':float(step),'reason':str(exc)});continue
        ticks=to_ticks(solved['joint_radians'],r,q0);end=to_q({n:ticks[i] for i,n in enumerate(NAMES)},r,q0)
        reason=None;last=origin['position'][2];drift_limit=max(3.,.08*step)
        if any(not bounds[n][0]<=int(ticks[i])<=bounds[n][1] for i,n in enumerate(NAMES)):reason='관절 범위 밖'
        else:
            for t in np.linspace(0,1,31):
                f=model.forward(start+(end-start)*t,with_points=False);xyz=f['position']
                if np.linalg.norm(xyz[:2]-origin['position'][:2])>drift_limit or xyz[2]<last-.1 or f['tool_axis']@origin['tool_axis']<math.cos(math.radians(15)):
                    reason='수직 단조 상승 경로 아님';break
                last=xyz[2]
            if reason is None and last-origin['position'][2]<step-3:reason='상승량 부족 %.1fmm'%(last-origin['position'][2])
        if reason:tried.append({'mm':float(step),'reason':reason});continue
        goal={n:int(ticks[i]) for i,n in enumerate(NAMES)}
        return goal,{'ok':True,'lift_mm':float(last-origin['position'][2]),'requested_mm':float(step),'tried':tried,
                     'start_z_mm':float(origin['position'][2]),'end_z_mm':float(last)}
    raise ValueError('수직 상승 %s mm 모두 불가 (%s)'%('/'.join('%.0f'%s for s in steps),'; '.join('%.0fmm %s'%(t['mm'],t['reason']) for t in tried)))


def lift_to_height(model,r,q0,base_ticks,bounds,target_z,minimum_z):
    """Rise straight up to target_z; if unreachable, the highest 15mm-lower step >= minimum_z."""
    z0=tcp_z(model,base_ticks,r,q0);need=target_z-z0
    if need<=1:
        return dict(base_ticks),{'ok':True,'lift_mm':0.,'skipped':True,'start_z_mm':z0,'end_z_mm':z0}
    floor=max(MIN_LIFT_MM,minimum_z-z0)
    steps=[need];s=need-15
    while s>=floor:steps.append(s);s-=15
    if steps[-1]>floor+.5 and floor<need:steps.append(floor)
    return vertical_lift(model,r,q0,base_ticks,bounds,steps)


def segment_min_z(model,qa,qb,samples=41):
    return float(min(model.forward(qa+(qb-qa)*t,with_points=False)['position'][2] for t in np.linspace(0,1,samples)))


def _travel(model,r,q0,a,b,bounds,required,depth=0):
    """Joint-space travel a->b; split at an IK midpoint at the higher end's height when it dips."""
    qa,qb=to_q(a,r,q0),to_q(b,r,q0)
    z=segment_min_z(model,qa,qb)
    if z>=required-.5:return [],[z]
    if depth>=2:raise ValueError('이송 경로가 높이 %.0fmm 아래로 내려감 (최저 %.0fmm)'%(required,z))
    fa,fb=model.forward(qa,with_points=False),model.forward(qb,with_points=False)
    mid_xyz=(fa['position']+fb['position'])/2;mid_xyz[2]=max(fa['position'][2],fb['position'][2])
    qm=(qa+qb)/2
    solved=model.inverse(mid_xyz,seed=qm,fixed_roll=float(qm[4]),prefer_seed=True)
    t=to_ticks(solved['joint_radians'],r,q0);mid={n:int(t[i]) for i,n in enumerate(NAMES)}
    if any(not bounds[n][0]<=mid[n]<=bounds[n][1] for n in NAMES) or np.linalg.norm(model.forward(to_q(mid,r,q0),with_points=False)['position']-mid_xyz)>5:
        raise ValueError('이송 중간 자세를 계산할 수 없습니다 (최저 %.0fmm < 필요 %.0fmm)'%(z,required))
    left,lz=_travel(model,r,q0,a,mid,bounds,required,depth+1)
    right,rz=_travel(model,r,q0,mid,b,bounds,required,depth+1)
    return left+[mid]+right,lz+rz


def plan_dropoff(model,r,q0,start_ticks,drop_ticks,home_ticks,plane,hang_mm,transfer_height_mm,bounds):
    """Return the full move list (arm ticks only) or raise ValueError before any motion."""
    hang=float(hang_mm)
    drop_z=tcp_z(model,drop_ticks,r,q0)
    transfer_z=max(plane+float(transfer_height_mm),drop_z+20)
    loaded_min=plane+hang+LOADED_CLEARANCE_MM
    lifted,lift_info=lift_to_height(model,r,q0,start_ticks,bounds,transfer_z,loaded_min)
    if lift_info['end_z_mm']<loaded_min-.5:
        raise ValueError('이송 높이 부족 · 들어올린 높이 %.0fmm < 물품 여유 높이 %.0fmm'%(lift_info['end_z_mm'],loaded_min))
    above,above_info=lift_to_height(model,r,q0,drop_ticks,bounds,transfer_z,max(loaded_min,drop_z+MIN_LIFT_MM))
    za,zb=lift_info['end_z_mm'],above_info['end_z_mm']
    required=max(loaded_min,min(za,zb)-TRAVEL_SAG_MM)
    travel,travel_z=_travel(model,r,q0,lifted,above,bounds,required)
    empty_required=min(plane+EMPTY_CLEARANCE_MM,zb,tcp_z(model,home_ticks,r,q0))
    home_z=segment_min_z(model,to_q(above,r,q0),to_q(home_ticks,r,q0))
    if home_z<empty_required-.5:
        raise ValueError('놓은 뒤 HOME 복귀 경로가 판 높이 아래로 지남 (최저 %.0fmm)'%home_z)
    return {'ok':True,'plane_z_mm':float(plane),'hang_mm':hang,'transfer_z_mm':float(transfer_z),'drop_z_mm':drop_z,
            'lift':lift_info,'above_drop':above_info,'travel_points':len(travel),'travel_min_z_mm':float(min(travel_z)),
            'travel_required_z_mm':float(required),'home_min_z_mm':home_z,
            'moves':{'lifted':lifted,'travel':travel,'above':above,'drop':dict(drop_ticks),'home':dict(home_ticks)}}


def dry_check(state,drop_ticks,home_ticks,transfer_height_mm):
    """Settings-screen 'path check only': plan from the current pose, assumed hang, no motion."""
    import json
    from .config import DATA
    from .approach_path import context
    from .orientation_alignment import apply_alignment
    from .robot_frame import transform,load as frame_load
    if not drop_ticks:raise ValueError('놓기 위치가 저장되지 않았습니다.')
    reference=apply_alignment(json.loads((DATA/'working_calibration.json').read_text(encoding='utf-8')))
    model,_,r,q0=context(reference,state)
    board=frame_load()['board_config']
    plane=transform([board['width_mm']/2,board['height_mm']/2],20)['surface_mm'][2]
    start={j['name']:j['raw_ticks'] for j in state['joints']}
    bounds={j['name']:(j['min_ticks'],j['max_ticks']) for j in state['joints']}
    result=plan_dropoff(model,r,q0,start,drop_ticks,home_ticks,plane,DEFAULT_HANG_MM,transfer_height_mm,bounds)
    result.pop('moves');result['assumed_hang']=True;result['start']='current_pose'
    return result
