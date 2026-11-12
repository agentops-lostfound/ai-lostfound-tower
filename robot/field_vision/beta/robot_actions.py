"""프로토타입의 공유 정지/홈/다축 이동. 물리 비상정지를 대체하지 않는다."""
from .robot_link import SERIAL
import copy
import json
import math
from pathlib import Path
import threading
import time
import uuid
import numpy as np
from .approach_path import context, SIGN
from .config import DATA
from .manual_control import manual
from .kinematics import NAMES

ALL=NAMES+['gripper']
HOME=DATA/'robot_home.json'


class MotionAborted(ValueError):
    """A completed/stationary motion failed validation; no hardware latch needed."""


SMALL_MOVE_DEG,SMALL_MOVE_MIN_S=10,1.0

def motion_duration(before,target,minimum=None,target_height_mm=None):
    angle=max(abs(target[n]-before[n])*360/4096 for n in ALL)
    arm_angle=max(abs(target[n]-before[n])*360/4096 for n in NAMES)
    low=target_height_mm is not None and target_height_mm<=100 and arm_angle>15
    # v0.2.68: every move took >=3s, so a 0.7mm gap correction cost as much as a 12mm one
    # (flow-3addf047: 10 corrective moves + 3 descent stages = 41s of the 52s before closing).
    # Moves of <=10 encoder degrees now take angle x 0.3s (min 1s): the peak joint speed
    # (3.3 deg/s) never exceeds what an existing 10 deg / 3s move already used.
    # An explicit minimum (HOME, closing) keeps the old floor.
    if minimum is None and angle<=SMALL_MOVE_DEG:return round(max(SMALL_MOVE_MIN_S,angle*3/SMALL_MOVE_DEG),2)
    return max(5 if angle>45 or low else 3,minimum or 3)


def small_move_arrival(start,target):
    delta={n:int(target[n]-start[n]) for n in NAMES if abs(target[n]-start[n])>3}
    tolerance={n:min(24,max(2,abs(delta[n])//2)) if n in delta else 46 for n in ALL}
    return tolerance,delta


def read_home():
    if not HOME.exists():
        # User's earliest taught starting pose; do not substitute the central pose.
        source=DATA/'manual_sessions/20261110-154814-9f8ab7/pose-42ce3c5b54/pose.json'
        if source.exists():
            pose=json.loads(source.read_text(encoding='utf-8'))
            value={'label':'처음 준비자세','source':str(source),'created':pose['captured'],
                'serial':SERIAL,'raw_ticks':{j['name']:j['raw_ticks'] for j in pose['state']['joints']}}
            HOME.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        else:return None
    return json.loads(HOME.read_text(encoding='utf-8'))


def fresh():
    s=manual.snapshot()
    if not s['connected'] or s['age'] is None or s['age']>.8:raise ValueError(s.get('last_error') or '수동 연결과 최신 관절 피드백이 필요합니다.')
    return s


def validate_goal(target,s):
    if set(target)!=set(ALL):raise ValueError('6개 관절 목표가 필요합니다.')
    invalid=[]
    for j in s['joints']:
        v=target[j['name']]
        if type(v)!=int or not j['min_ticks']<=v<=j['max_ticks']:
            invalid.append(f'{j["id"]}번 {v} (허용 {j["min_ticks"]}~{j["max_ticks"]})')
    if invalid:raise ValueError('목표가 현재 보정 범위 밖입니다: '+', '.join(invalid))


class Actions:
    def __init__(self):
        self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None
        self.info={'running':False,'phase':'idle','message':'대기','events':[]}

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.info)

    def log(self,phase,message,**data):
        with self.lock:
            self.info.update(phase=phase,message=message)
            event={'time':time.time(),'phase':phase,'message':message,**data};self.info['events'].append(event)
            self.info['events']=self.info['events'][-100:]
            folder=DATA/'robot_actions';folder.mkdir(exist_ok=True)
            with (folder/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')

    def stop(self):
        self.cancel.set()
        if manual.snapshot()['connected']:
            try:manual.send('stop')
            except Exception as exc:self.log('stop_error','정지 피드백 확인 실패: '+str(exc));raise
        self.log('stopped','STOP · 자동 시퀀스 취소 · 토크 유지')
        return self.snapshot()

    def launch(self,kind,fn):
        with self.lock:
            if self.info['running']:raise ValueError('기존 작업을 STOP하고 종료를 기다리세요.')
            self.cancel.clear();self.info.update(running=True,phase=kind,message='시작',run_id=uuid.uuid4().hex)
            def run():
                try:
                    fn()
                    if not self.cancel.is_set():self.log('complete','완료 · 위치 유지')
                except Exception as exc:
                    self.cancel.set()
                    state=manual.snapshot()
                    ordinary=isinstance(exc,MotionAborted) and state.get('connected') and not state.get('active') and not state.get('latched')
                    try:
                        if state['connected'] and not ordinary:manual.send('stop')
                    except Exception:pass
                    self.log('aborted' if ordinary else 'failed',str(exc))
                finally:
                    with self.lock:self.info['running']=False
            self.thread=threading.Thread(target=run,daemon=True,name='robot-'+kind);self.thread.start()
        return self.snapshot()

    def check(self):
        if self.cancel.is_set():raise ValueError('STOP으로 취소됨 · 자동 재개 없음')
        s=fresh()
        if s['latched']:raise ValueError('정지 잠금 · '+s.get('last_error',s.get('message','시퀀스 취소')))
        return s

    def move(self,target,label,minimum=None,grip_contact=False,watch=None,timed_close=False,timed_close_seconds=1.5,gripper_only=False,arrival_tolerance_ticks=46,arrival_displacement_ticks=None,arrival_mode='target',target_height_mm=None):
        s=self.check();validate_goal(target,s)
        if s['active']:raise ValueError('다른 관절 조작이 진행 중입니다.')
        before={j['name']:j['raw_ticks'] for j in s['joints']}
        if gripper_only:target=dict(before,gripper=target['gripper'])
        for j in s['joints']:
            if abs(target[j['name']]-j['raw_ticks'])>3 and not j['torque_enabled']:
                self.check();manual.send('enable',joint=j['name'])
        s=self.check();before={j['name']:j['raw_ticks'] for j in s['joints']}
        if gripper_only:target=dict(before,gripper=target['gripper'])
        # Large posture changes (>45 encoder degrees on any axis) take 5s.
        duration=motion_duration(before,target,minimum,target_height_mm)
        if duration>20:raise ValueError('이동 구간이 너무 큽니다. 경유 자세가 필요합니다.')
        token=uuid.uuid4().hex;self.log('moving',label,target=target,duration=duration,token=token)
        extra={} if arrival_displacement_ticks is None else {'arrival_displacement_ticks':arrival_displacement_ticks}
        if arrival_mode!='target':extra['arrival_mode']=arrival_mode
        if timed_close:extra['timed_close_seconds']=float(timed_close_seconds)
        self.check();manual.send('move',target=target,expected=before,duration=duration,token=token,grip_contact=grip_contact,timed_close=timed_close,gripper_only=gripper_only,arrival_tolerance_ticks=arrival_tolerance_ticks,**extra)
        deadline=time.monotonic()+duration+6;last_heartbeat=0
        try:
            while time.monotonic()<deadline:
                s=self.check();motion=s.get('motion') or {}
                if motion.get('token')==token:
                    if motion['status'] in ['complete','contact_candidate']:
                        self.log('arrived',label+' · '+motion['status'],motion=motion);return s
                    if motion['status'] in ['stopped','failed']:raise ValueError('구간 정지: '+s.get('last_error',motion['status']))
                if time.monotonic()-last_heartbeat>.15:
                    manual.send('move_heartbeat',token=token);last_heartbeat=time.monotonic()
                if watch and watch(s):
                    self.check();return manual.send('grip_contact_stop',token=token)
                self.cancel.wait(.05)
            raise ValueError('이동 완료 시간 초과')
        except Exception:
            try:manual.send('stop')
            except Exception:pass
            raise

    def home_status(self):
        home=read_home();s=manual.snapshot();error=None
        if home and s['connected']:
            target=dict(home['raw_ticks'])
            try:validate_goal(target,s)
            except ValueError as exc:error=str(exc)
        return {'home':home,'validation_error':error,'running':self.info['running'],
                'gripper_policy':'집게 포함 저장된 준비자세로 복귀'}

    def save_home(self):
        if self.info['running']:raise ValueError('작업 종료 후 홈을 저장하세요.')
        s=fresh()
        if s['active']:raise ValueError('움직임을 멈춘 뒤 저장하세요.')
        raw={j['name']:j['raw_ticks'] for j in s['joints']};validate_goal(raw,s)
        value={'label':'사용자 지정 준비자세','created':time.time(),'serial':SERIAL,'raw_ticks':raw}
        if HOME.exists():
            archive=DATA/'archives';archive.mkdir(exist_ok=True)
            (archive/('robot-home-'+uuid.uuid4().hex+'.json')).write_text(HOME.read_text(encoding='utf-8'),encoding='utf-8')
        HOME.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        return self.home_status()

    def open_gripper(self):
        s=fresh()
        if s['active'] or s['latched']:
            raise ValueError('장비 동작을 종료하고 정지 잠금을 해제하세요.')
        def run():
            state=self.check()
            jaw=next(j for j in state['joints'] if j['name']=='gripper')
            target={j['name']:j['raw_ticks'] for j in state['joints']}
            target['gripper']=round((jaw['min_ticks']+jaw['max_ticks'])/2)
            self.move(target,'집게만 50% 열기',gripper_only=True)
        return self.launch('release',run)

    def home_release_target(self,state):
        # v0.2.45 B2: staged 30 -> 20 -> 10mm straight lift; below 10mm HOME is refused.
        from .return_path import vertical_lift
        reference=json.loads((DATA/'working_calibration.json').read_text(encoding='utf-8'))
        model,start,zero_ticks,zero_angles=context(reference,state)
        if reference['model_sha256']!=model.hash:
            raise ValueError('로봇 모델과 작업 보정이 일치하지 않습니다.')
        base={j['name']:j['raw_ticks'] for j in state['joints']}
        bounds={j['name']:(j['min_ticks'],j['max_ticks']) for j in state['joints']}
        try:goal,info=vertical_lift(model,zero_ticks,zero_angles,base,bounds)
        except ValueError as exc:raise ValueError('HOME 전 상승 불가 · '+str(exc))
        self.last_home_lift=info
        jaw=next(j for j in state['joints'] if j['name']=='gripper')
        result=dict(goal)
        result['gripper']=max(jaw['raw_ticks'],round((jaw['min_ticks']+jaw['max_ticks'])/2))
        validate_goal(result,state)
        return result

    def go_home(self):
        if self.info['running']:raise ValueError('STOP 후 작업 종료를 기다리세요.')
        home=read_home()
        if not home:raise ValueError('준비자세를 먼저 저장하세요.')
        s=fresh();target=dict(home['raw_ticks'])
        validate_goal(target,s)
        if s['active']:raise ValueError('STOP 후 동작 종료를 기다리세요.')
        release=self.home_release_target(s)
        # Hold the release aperture throughout transit. The grasp sequence
        # still uses the saved closed home posture when starting a new trial.
        target['gripper']=release['gripper']
        if s['latched']:manual.send('resume')
        def run():
            # Clearance-only lift. Fully extended, the loaded shoulder_lift can stop
            # just short (flow-3ad8175f: 47 ticks vs 46 -> latched). The worker caps
            # tolerance at 46, so accept an arrival-timeout here when every joint is
            # within 90 ticks and the user did not press STOP; HOME itself (folded,
            # low load) still uses the normal 46-tick arrival check.
            try:self.move(release,'HOME 전 · %.0fmm 상승하며 집게 개방'%getattr(self,'last_home_lift',{}).get('lift_mm',30))
            except ValueError:
                if self.cancel.is_set():raise
                s=fresh();motion=s.get('motion') or {}
                errors=motion.get('arrival_error_ticks') or {}
                if not (s['latched'] and motion.get('status')=='failed' and errors
                        and all(abs(v)<=90 for v in errors.values())):raise
                self.log('home_lift_short','HOME 전 상승 도착 오차 허용 · 준비자세로 계속',arrival_error_ticks=errors)
                manual.send('resume')
            self.home_move(target)
        return self.launch('home',run)

    def home_move(self,target):
        s=self.check();start={j['name']:j['raw_ticks'] for j in s['joints']}
        self.move(target,'HOME · 저장된 준비자세 복귀',minimum=3)


actions=Actions()
