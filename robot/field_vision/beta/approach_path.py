"""Model-based approach using the frozen empirical calibration; no taught waypoint."""
import math
import numpy as np
from .kinematics import Model,NAMES

# wrist_roll(5th) direction: +1. The original calibration poses never moved
# wrist_roll (all 2035 ticks), so -1 was an unverified assumption. 18 trials with
# ARM-camera alignment measurements fit +1 with max residual ~16 deg, while -1
# drifts with shoulder_pan (0 -> +44 -> -90 deg, right -> centre -> left).
SIGN=np.array([1,1,1,1,1])


def path_cost(start,path):
    previous=start;total=0.
    for q in path:total+=float(np.max(np.abs(q-previous)));previous=q
    last_start=start if len(path)==1 else path[-2]
    return total+3*float(np.max(np.abs(path[-1]-last_start)))

def context(reference,state):
    model=Model(opening_axis_local=reference.get('opening_axis_local'));by={j['name']:j for j in state['joints']}
    r=np.array(reference['reference_raw_ticks']);q0=np.array(reference['reference_model_radians'])
    bounds=np.array([[by[n]['min_ticks'],by[n]['max_ticks']] for n in NAMES])
    mapped=q0[:,None]+(bounds-r[:,None])*SIGN[:,None]*2*np.pi/4096
    model.limits[:,0]=np.maximum(model.limits[:,0],mapped.min(1))
    model.limits[:,1]=np.minimum(model.limits[:,1],mapped.max(1))
    q=q0+(np.array([by[n]['raw_ticks'] for n in NAMES])-r)*SIGN*2*np.pi/4096
    return model,q,r,q0

def pose(reference,state):
    m,q,_,_=context(reference,state);f=m.forward(q,with_points=False)
    return {'xyz_mm':f['position'].tolist(),'tool_axis':f['tool_axis'].tolist(),
        'opening_axis':f['opening_axis'].tolist(),'down_error_deg':float(np.degrees(np.arccos(np.clip(-f['tool_axis'][2],-1,1))))}

def plan_path(reference,state,target,plane_z,opening_yaw=None,roll_window=None,relaxed=False,fixed_roll=None,opening_direction=None,max_tilt_deg=None):
    # Tool tilt from vertical allowed at the target (default 10 relaxed / 5 strict).
    # Far board cells (~29cm) need ~11 deg at approach height: wrist_flex is at its limit.
    tilt=max_tilt_deg if max_tilt_deg is not None else (10 if relaxed else 5)
    m,start,r,q0=context(reference,state);target=np.array(target,float)
    start_pose=m.forward(start,with_points=False)
    def quantized(q):
        raw=np.rint(r+(q-q0)*SIGN*4096/(2*np.pi))
        return q0+(raw-r)*SIGN*2*np.pi/4096
    def solve(xyz,seed):
        # Try alternate numerical weightings without relaxing any acceptance
        # threshold. A single weighted optimum can miss an otherwise valid pose.
        for weight in [60,45,30]:
            for yaw in ([None] if opening_yaw is None else [opening_yaw,opening_yaw+math.pi]):
                for initial in [seed,q0,q0+np.array([0,0,0,0,-math.pi/2]),q0+np.array([0,0,0,0,math.pi/2])]:
                    sol=m.inverse(xyz,seed=initial,tool_down=True,fixed_roll=fixed_roll,prefer_seed=True,opening_yaw=yaw,orientation_weight=weight,down_weight=15 if relaxed else 60,max_down_deg=tilt)
                    if sol['reachable_in_model']:
                        q=quantized(np.array(sol['joint_radians']))
                        fk=m.forward(q,with_points=False)
                        if opening_direction is not None and fk['opening_axis']@np.asarray(opening_direction)<math.cos(math.radians(12)):continue
                        if np.any(q<m.limits[:,0]) or np.any(q>m.limits[:,1]):continue
                        if np.linalg.norm(fk['position']-xyz)>=3 or -fk['tool_axis'][2]<math.cos(math.radians(tilt)):continue
                        yaw_error=0 if yaw is None else math.degrees(math.acos(np.clip(fk['opening_axis']@np.array([math.cos(yaw),math.sin(yaw),0]),-1,1)))
                        roll_ticks=r[4]+(q[4]-q0[4])*SIGN[4]*4096/(2*np.pi)
                        if roll_window and abs(roll_ticks-roll_window[0])>roll_window[1]:continue
                        if yaw_error<=12:return q
        return None
    goal=solve(target,start)
    if goal is None:raise ValueError('현재 보정·관절 범위에서 대상 접근 자세를 계산할 수 없습니다.')
    def safe(path):
        previous=start
        for end in path:
            for t in np.linspace(0,1,301):
                f=m.forward(previous*(1-t)+end*t,with_points=False);p=f['position'];distance=np.linalg.norm(p[:2]-target[:2])
                # Desk and object approach clearance; full scene collisions unmodeled.
                if p[2]<plane_z+20:return False
                if distance<60 and p[2]<target[2]+20:
                    if p[2]<target[2]-3 or -f['tool_axis'][2]<math.cos(math.radians(max(tilt,10) if relaxed else 20)):return False
            previous=end
        return True
    candidates=[]
    if safe([goal]):candidates.append([goal])
    if not candidates:
        nearby=[]
        # These three pitch joints have parallel axes. Equal/opposite shoulder
        # and elbow changes retain the solved tool orientation and wrist angle.
        # Finish turning above the target, then approach with that orientation;
        # a direct HOME interpolation otherwise finishes turning too low.
        for delta in np.r_[np.arange(.05,1.401,.05),-np.arange(.05,1.401,.05)]:
            mid=quantized(goal+np.array([0,-delta,delta,0,0]))
            if np.any(mid<m.limits[:,0]) or np.any(mid>m.limits[:,1]):continue
            middle=m.forward(mid,with_points=False)['position'];end=m.forward(goal,with_points=False)['position']
            if middle[2]<end[2]+10 or np.linalg.norm(middle[:2]-target[:2])>60:continue
            nearby.append([mid,goal])
        # Two target-XY elevated poses often avoid the large equal/opposite
        # shoulder/elbow swing of the diagonal final segment. Bounded IK work.
        for height in [target[2]+12,target[2]+20]:
            mid=solve([*target[:2],height],start)
            if mid is not None:nearby.append([mid,goal])
        for candidate in sorted(nearby,key=lambda path:path_cost(start,path)):
            if safe(candidate):
                candidates.append(candidate);break
    if not candidates:
        for fraction in [1.,.75,.5,.25]:
            xy=start_pose['position'][:2]*(1-fraction)+target[:2]*fraction
            for height in [target[2]+20,max(100,target[2]+40),max(140,target[2]+60),180]:
                mid=solve([*xy,height],start)
                if mid is None:continue
                # Reuse an already validated endpoint only if the entire route passes.
                if safe([mid,goal]):
                    candidates.append([mid,goal]);break
                end=solve(target,mid)
                if end is not None and safe([mid,end]):
                    candidates.append([mid,end]);break
            if candidates:break
    if not candidates:raise ValueError('계산된 경로의 집게 높이·방향 검사를 통과하지 못했습니다. 이동하지 않습니다.')
    chosen=min(candidates,key=lambda path:path_cost(start,path));grip=next(j['raw_ticks'] for j in state['joints'] if j['name']=='gripper')
    result=[]
    for q in chosen:
        raw=np.rint(r+(q-q0)*SIGN*4096/(2*np.pi)).astype(int)
        goal_dict={n:int(raw[i]) for i,n in enumerate(NAMES)};goal_dict['gripper']=grip
        f=m.forward(q,with_points=False)
        result.append({'target':goal_dict,'xyz_mm':f['position'].tolist(),'tool_axis':f['tool_axis'].tolist(),'opening_axis':f['opening_axis'].tolist(),
            'down_error_deg':float(np.degrees(np.arccos(np.clip(-f['tool_axis'][2],-1,1)))),
            'short_axis_error_deg':None if opening_yaw is None else float(np.degrees(np.arccos(np.clip(abs(f['opening_axis']@np.array([math.cos(opening_yaw),math.sin(opening_yaw),0])),-1,1))))})
    return {'start_pose':pose(reference,state),'waypoints':result,'model_only':True,
        'note':'TCP 높이·방향 및 관절 범위 검사 · 주변 장애물/로봇 몸체 충돌 검증 아님'}
