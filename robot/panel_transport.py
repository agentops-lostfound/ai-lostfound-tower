"""Panel backends. Optional explicit startup connects Studio in hold, never teleop."""
import json
import threading
import time
import urllib.request
from pathlib import Path

from robot.joint_motion import JOINTS,vector


def step_feedback(target,actions,measured):
    # Gripper is held by the server, never part of this arm-only target.
    keys=[name+'.pos' for name in JOINTS[:5]]
    ack=bool(actions) and all(abs(actions.get(k,float('inf'))-target[k])<0.02 for k in keys)
    errors={k:abs(measured[k]-target[k]) for k in keys} if measured else {}
    reached=bool(errors) and max(errors.values())<=0.15
    return ack,reached,errors


class Simulation:
    live=False
    def __init__(self):
        self.values={n+'.pos':0.0 for n in JOINTS};self.last=time.monotonic();self.error=None
    def snapshot(self):self.last=time.monotonic();return dict(self.values)
    def fresh(self):return True
    def ready(self):return True
    def step(self,target,expected):vector(target);self.values=dict(target)
    def stop(self):pass
    def repair(self):pass
    def close(self):pass


class Studio:
    live=True
    def __init__(self,url,project,follower,connect=False,environment='d4f3fe28-b56c-4635-897e-61f765e4fce5',trace_path=None):
        self.trace_path=Path(trace_path) if trace_path else None
        self.command_id=0
        try:import websocket
        except ImportError as exc:raise RuntimeError('Live mode needs websocket-client; see robot/README-panel.md') from exc
        with urllib.request.urlopen(url+'/api/runtime/sessions',timeout=3) as response:
            sessions=json.load(response)
        self.runtime_ws=None;self.runtime_thread=None
        found=[s for s in sessions if s.get('follower_id')==follower]
        if not found and connect:
            with urllib.request.urlopen(url+f'/api/projects/{project}/environments/{environment}',timeout=3) as response:
                config=json.load(response)
            robots=[r for r in config['robots'] if r['robot']['id']==follower]
            if len(robots)!=1:raise RuntimeError('Follower missing from configured environment')
            leader=robots[0].get('tele_operator') or {}
            handshake={'follower_id':follower,'leader_id':leader.get('robot_id'),
                       'camera_ids':[c['id'] for c in config['cameras']],'restart':False}
            self.runtime_ws=websocket.create_connection(url.replace('http','ws',1)+f'/api/projects/{project}/runtime/ws',timeout=30)
            try:
                self.runtime_ws.send(json.dumps(handshake))
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    event=json.loads(self.runtime_ws.recv())
                    if event.get('event')=='error':raise RuntimeError(event.get('message','Runtime startup failed'))
                    if event.get('event')=='state' and event.get('data',{}).get('connected'):
                        if event['data'].get('follower_source')!='hold':raise RuntimeError('New runtime did not enter hold')
                        found=[{'activity':{'follower_source':'hold'}}];break
                if not found:raise RuntimeError('Runtime startup timed out')
            except Exception:
                self.runtime_ws.close();raise
            # Keep this subscriber alive without sending teleop/policy/position commands.
            def drain_runtime():
                try:
                    while self.runtime_ws:self.runtime_ws.recv()
                except Exception:pass
            self.runtime_thread=threading.Thread(target=drain_runtime,daemon=True);self.runtime_thread.start()
        if len(found)!=1 or found[0].get('activity',{}).get('follower_source')!='hold':
            raise RuntimeError('Existing follower session in hold mode required; no session will be started')
        self.lock=threading.RLock();self.values=None;self.last=0;self.error=None
        self.capable=False;self.pending=None;self.pending_at=0;self.actions=None
        self.failure=None
        self.mode='hold';self.closed=False
        try:
            self.ws=websocket.create_connection(url.replace('http','ws',1)+f'/api/projects/{project}/runtime/manual/ws',timeout=2)
            self.ws.send(json.dumps({'follower_id':follower}))
        except Exception:
            if self.runtime_ws:self.runtime_ws.close();self.runtime_ws=None
            raise
        self.thread=threading.Thread(target=self._receive,daemon=True);self.thread.start()

    def _receive(self):
        try:
            while not self.closed:
                row=json.loads(self.ws.recv())
                with self.lock:
                    event=row.get('event')
                    if event=='manual_capabilities':
                        d=row['data'];self.capable=d.get('version')==1 and d.get('attach_only') is True
                    elif event=='state':
                        self.mode=row['data'].get('follower_source','unknown')
                    elif event=='error':
                        self.error=row.get('message','Studio error');self.pending=None
                        if not self.capable:return  # Preserve connection rejection instead of overwriting it on close.
                    elif event=='observation':
                        values=row['data'];vector(values);self.values=values;self.last=time.monotonic()
                        self.actions=row.get('actions')
                        if self.pending is not None:
                            ack,reached,_=step_feedback(self.pending,self.actions,values)
                            self._trace('feedback')
                            # ACK permits the next bounded trajectory step; it is not arrival.
                            if ack:self.pending=None
        except Exception as exc:
            if not self.closed and not self.error:self.error='Connection lost: '+str(exc)
        finally:
            # A dead receive thread must not leave a ghost manual-panel slot.
            if not self.closed:
                try:self.ws.close()
                except Exception:pass

    def snapshot(self):
        with self.lock:return dict(self.values) if self.values else None
    def fresh(self):return time.monotonic()-self.last<0.75
    def ready(self):
        with self.lock:return self._ready_locked()

    def _trace(self,event):
        path=getattr(self,'trace_path',None)
        if path is None:return
        now=time.monotonic()
        target=dict(self.pending or {})
        ack,reached,errors=step_feedback(target,self.actions,self.values) if target else (False,False,{})
        row={'event':event,'command_id':self.command_id,'monotonic':now,
             'timestamp_unix':time.time(),'pending_elapsed':now-self.pending_at if target else None,
             'target':target,'actions':dict(self.actions or {}),'measured':dict(self.values or {}),
             'arm_errors_normalized':errors,'acknowledged':ack,'position_confirmed':reached}
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')

    def _ready_locked(self):
        if self.pending is not None and time.monotonic()-self.pending_at>1.5:
            ack,reached,errors=step_feedback(self.pending,self.actions,self.values)
            self.failure={'acknowledged':ack,'position_confirmed':reached,'target':dict(self.pending),
                          'measured':dict(self.values or {}),'actions':dict(self.actions or {}),
                          'arm_errors_normalized':errors,'recorded_at_unix':time.time()}
            if not ack:self.error='Step timeout: runtime action not acknowledged'
            else:
                joint=max(errors,key=errors.get) if errors else 'unknown'
                self.error=f'Following timeout: {joint} error={errors.get(joint,0):.3f} normalized'
            if not getattr(self,'_timeout_logged',False):
                self._trace('timeout');self._timeout_logged=True
        return self.capable and self.fresh() and self.mode=='hold' and self.pending is None and not self.error
    def _send(self,event,data):self.ws.send(json.dumps({'event':event,'data':data}))
    def step(self,target,expected):
        with self.lock:
            if not self.ready():raise RuntimeError(self.error or 'Studio not ready')
            self.pending=dict(target);self.pending_at=time.monotonic()
            self.command_id=getattr(self,'command_id',0)+1;self._timeout_logged=False
            self._trace('command')
            self._send('set_manual_joint_target',{'target':target,'expected':expected,'stage_approved':True})
    def stop(self):
        self._send('manual_joint_control',{'action':'stop'})
        with self.lock:self.pending=None
    def repair(self):
        if not self.capable or not self.fresh() or self.mode!='hold':raise RuntimeError('Fresh hold observations required')
        self._send('manual_joint_control',{'action':'repair'})
        with self.lock:self.error=None;self.pending=None
    def close(self):
        try:
            if getattr(self.ws,'connected',False):self.stop()
        except Exception:
            pass  # A closed socket cannot deliver stop; server also latches on detach.
        finally:
            self.closed=True;self.ws.close()
            if self.runtime_ws:
                self.runtime_ws.close();self.runtime_ws=None
