"""Bounded normalized-joint interpolation; hardware transport is injected explicitly.

Never treats normalized positions as degrees. No torque or serial connection code.
"""
import math
import time

JOINTS=('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper')


def vector(values):
    result=[]
    for name in JOINTS:
        value=values.get(name+'.pos')
        low=0 if name=='gripper' else -100
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=100:
            raise ValueError('Invalid normalized joint: '+name)
        result.append(float(value))
    return result


def plan(start,target,max_step=0.5,rate_hz=10):
    if not 0<max_step<=0.5 or not 1<=rate_hz<=10:
        raise ValueError('max_step <= 0.5 and rate_hz <= 10 required')
    a,b=vector(start),vector(target)
    # Keep gripper unchanged during approach/retraction.
    if abs(a[-1]-b[-1])>0.5:raise ValueError('Separate approval required for gripper change')
    b[-1]=a[-1]
    steps=max(1,math.ceil(max(abs(y-x) for x,y in zip(a,b))/max_step))
    return {'unit':'studio_normalized','start':a,'target':b,'rate_hz':rate_hz,
            'max_step':max_step,'duration_seconds':steps/rate_hz,
            'waypoints':[[x+(y-x)*i/steps for x,y in zip(a,b)] for i in range(1,steps+1)],
            'collision_checked':False,'robot_authorized':False}


def execute(motion,transport,*,approved=False,stop_requested=lambda:False,
            sleep=time.sleep,clock=time.monotonic):
    """Transport must own the runtime action source, not compete with hold/teleop.

    Required methods: has_exclusive_control(), read_normalized(), send_normalized(),
    hold_current(). The latter must also transfer the held target to the owner.
    A disconnected publisher cannot provide a guaranteed stop.
    """
    if not approved:raise PermissionError('Stage-specific approval required')
    if not transport.has_exclusive_control():raise RuntimeError('Runtime control handoff required')
    # Revalidate limits and waypoint construction, not caller-provided authorization.
    keys=[n+'.pos' for n in JOINTS]
    checked=plan(dict(zip(keys,motion['start'])),dict(zip(keys,motion['target'])),
                 motion['max_step'],motion['rate_hz'])
    previous=checked['start']
    sent=0
    try:
        for point in checked['waypoints']:
            if stop_requested():return {'status':'cancelled','sent':sent}
            if not transport.has_exclusive_control():raise RuntimeError('Control ownership lost')
            current=vector(transport.read_normalized())
            if max(abs(a-b) for a,b in zip(current,previous))>2:
                raise RuntimeError('Start mismatch or following error exceeds 2 normalized units')
            begin=clock()
            transport.send_normalized(dict(zip(keys,point)))
            previous=point;sent+=1
            sleep(max(0,1/checked['rate_hz']-(clock()-begin)))
        measured=vector(transport.read_normalized())
        if max(abs(a-b) for a,b in zip(measured,checked['target']))>1:
            raise RuntimeError('Final target not reached within 1 normalized unit')
        return {'status':'reached','sent':sent,'measured':measured}
    finally:
        transport.hold_current()
