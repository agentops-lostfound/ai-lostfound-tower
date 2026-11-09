"""Local stdin/stdout worker owning the follower; stdout is JSON only."""
import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from robot.joint_motion import vector
from robot.vendor_coordinates import VendorCoordinates
from robot.vendor_motion import move_stage


def main(robot_factory=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--calibration',required=True,type=Path)
    parser.add_argument('--port',default='/dev/ttyACM0')
    parser.add_argument('--trace',type=Path,required=True)
    args=parser.parse_args()
    logging.basicConfig(stream=sys.stderr,level=logging.ERROR)
    # Import heavy dependencies before advertising readiness or starting stage timing.
    from so101_control import control as vendor_control
    calibration=json.loads(args.calibration.read_text(encoding='utf-8-sig'))
    coordinates=VendorCoordinates(calibration)
    # Refuse a second serial owner, including a Studio runtime.
    for process in (Path('/proc').iterdir() if robot_factory is None else []):
        if not process.name.isdigit() or int(process.name)==os.getpid():continue
        try:
            for fd in (process/'fd').iterdir():
                try:
                    if os.readlink(fd)==args.port:raise RuntimeError('Serial port busy; close existing controller first')
                except (FileNotFoundError,PermissionError):pass
        except (FileNotFoundError,PermissionError):pass
    if args.calibration.stem!='follower':raise ValueError('Expected isolated follower.json calibration copy')
    if robot_factory is None:
        from lerobot.robots.so_follower import SO101Follower,SO101FollowerConfig
        robot=SO101Follower(SO101FollowerConfig(port=args.port,id='follower',
            calibration_dir=args.calibration.parent,use_degrees=True,
            disable_torque_on_disconnect=False,max_relative_target=10.0))
    else:robot=robot_factory(args,calibration)
    io=threading.RLock();output=threading.Lock();state_lock=threading.Lock()
    quit_event=threading.Event();cancel_event=threading.Event()
    state={'busy':False,'stopped':True,'error':None,'last_ping':time.monotonic()}

    def emit(event,**data):
        with output:print(json.dumps({'event':event,**data}),flush=True)

    def status():
        with io:degrees=robot.get_observation()
        with state_lock:snapshot=dict(state)
        emit('status',values=coordinates.normalized(degrees),degrees=degrees,
             busy=snapshot['busy'],stopped=snapshot['stopped'],error=snapshot['error'])
        return degrees

    def hold():
        with io:robot.send_action(robot.get_observation())

    class LockedRobot:
        def get_observation(self):
            with io:return robot.get_observation()
        def send_action(self,action):
            with io:return robot.send_action(action)

    def interrupted():
        return cancel_event.is_set() or quit_event.is_set() or time.monotonic()-state['last_ping']>1.5

    def execute(command,target,duration,include_gripper):
        error=None;completed=False;started=time.monotonic()
        def trace(action,applied):
            with io:measured=robot.get_observation()
            args.trace.parent.mkdir(parents=True,exist_ok=True)
            with args.trace.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'id':command,'monotonic':time.monotonic(),
                    'command':action,'applied':applied,'measured':measured})+'\n')
        try:
            move_stage(LockedRobot(),target,duration=duration,cancelled=interrupted,observe=trace,
                       vendor=vendor_control,include_gripper=include_gripper)
            completed=True
        except Exception as exc:error=f'{type(exc).__name__}: {exc}'
        finally:
            with state_lock:
                state.update(busy=False,stopped=bool(error),error=error)
            try:
                actual=status()
                errors={k:abs(actual[k]-target[k]) for k in target if k!='gripper.pos'}
                gripper_error=abs(actual['gripper.pos']-target['gripper.pos']) if include_gripper else None
                emit('result',id=command,completed=completed,error=error,
                     elapsed=time.monotonic()-started,errors_degrees=errors,gripper_error_normalized=gripper_error)
            except Exception as exc:
                cancel_event.set()
                with state_lock:state.update(stopped=True,error=str(exc))
                emit('error',message=str(exc))

    def poll():
        while not quit_event.wait(0.1):
            try:
                if time.monotonic()-state['last_ping']>1.5:
                    cancel_event.set()
                    with state_lock:
                        state.update(stopped=True,error='GUI heartbeat lost; repair required')
                status()
            except Exception as exc:
                cancel_event.set();emit('error',message=str(exc));return

    movement=None
    try:
        # Reuse already configured hardware; do not toggle torque or rewrite calibration.
        robot.bus.connect()
        if not robot.is_calibrated:raise RuntimeError('Existing calibration mismatch')
        torque=robot.bus.sync_read('Torque_Enable',normalize=False)
        if not all(v==1 for v in torque.values()):raise RuntimeError('Torque disabled; prepare the arm before connecting')
        emit('ready',pid=os.getpid(),driver='so101-control',max_relative_target=10,max_seconds=5)
        status()
        threading.Thread(target=poll,daemon=True).start()
        for line in sys.stdin:
            try:
                command=json.loads(line);kind=command.get('command')
                if kind=='ping':state['last_ping']=time.monotonic();continue
                if kind in ('stop','shutdown'):
                    cancel_event.set()
                    with state_lock:state['stopped']=True
                    if not state['busy']:hold()
                    emit('ack',id=command.get('id'),command=kind)
                    if kind=='shutdown':break
                elif kind=='repair':
                    with state_lock:
                        if state['busy']:raise RuntimeError('Movement still stopping')
                        cancel_event.clear();state.update(stopped=False,error=None,last_ping=time.monotonic())
                    emit('ack',id=command.get('id'),command=kind)
                elif kind=='move':
                    if command.get('approved') is not True:raise ValueError('One-stage approval required')
                    vector(command['target']);vector(command['expected'])
                    duration=float(command['duration'])
                    if not 0<duration<=5:raise ValueError('Duration must be <=5 seconds')
                    with state_lock:
                        if state['busy'] or state['stopped'] or state['error']:raise RuntimeError('Repair and idle required')
                        with io:actual=coordinates.normalized(robot.get_observation())
                        if max(abs(actual[k]-command['expected'][k]) for k in actual)>1:
                            raise RuntimeError('Measured pose changed; review again')
                        target=coordinates.degrees(command['target'])
                        state['busy']=True;cancel_event.clear()
                    include_gripper=command.get('include_gripper') is True
                    movement=threading.Thread(target=execute,args=(command['id'],target,duration,include_gripper),daemon=True)
                    movement.start()
                else:raise ValueError('Unknown command')
            except Exception as exc:emit('error',message=str(exc))
    finally:
        quit_event.set();cancel_event.set()
        if movement:movement.join(timeout=6)
        if robot.is_connected:
            hold();robot.disconnect()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'event':'error','message':f'{type(exc).__name__}: {exc}'}),flush=True)
        raise
