"""수동 GUI의 단일 장비 세션과 피드백/기록 관리."""
import copy
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid
import requests
from .config import DATA
from . import robot_link


class ManualControl:
    def __init__(self):
        self.lock=threading.RLock();self.write_lock=threading.Lock();self.process=None
        self.ready=threading.Event();self.pending={};self.owns=False;self.directory=None
        self.state={'connected':False,'joints':[],'active':None,'latched':False,'message':'연결 전','updated':None}

    def snapshot(self):
        with self.lock:
            result=copy.deepcopy(self.state)
            result['age']=time.time()-result['updated'] if result['updated'] else None
            result['session']=self.directory.name if self.directory else None
            result['process_alive']=self.process is not None and self.process.poll() is None
            return result

    def start(self):
        with self.lock:
            if self.process and self.process.poll() is None:return self.snapshot()
            info=robot_link.status()
            if info['sessions']:raise ValueError('Studio 로봇 실행 세션을 먼저 종료하세요.')
            if not robot_link.LOCK.acquire(blocking=False):raise ValueError('다른 장비 조회가 진행 중입니다.')
            self.owns=True
            try:
                r=requests.get(robot_link.BASE+f'/projects/{info["project_id"]}/robots/{info["robot_id"]}',timeout=5);r.raise_for_status()
                robot=r.json();payload=robot['payload']
                if payload['serial_number']!=robot_link.SERIAL:raise ValueError('장비 시리얼 불일치')
                self.directory=DATA/'manual_sessions'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
                self.directory.mkdir(parents=True,exist_ok=False)
                (self.directory/'device.json').write_text(json.dumps(robot,ensure_ascii=False,indent=2),encoding='utf-8')
                self.state={'connected':False,'joints':[],'active':None,'latched':False,'message':'연결 중','updated':None}
                self.ready.clear()
                source=Path(__file__).with_name('manual_worker.py').read_text(encoding='utf-8')
                self.process=subprocess.Popen(['docker','exec','-i',robot_link.CONTAINER,
                    '/app/application/backend/.venv/bin/python','-u','-c',source],stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',bufsize=1)
                self.process.stdin.write(json.dumps({'port':payload['connection_string'],'calibration':payload['calibration']})+'\n');self.process.stdin.flush()
                threading.Thread(target=self._reader,args=(self.process,self.directory),daemon=True).start()
            except Exception:
                robot_link.LOCK.release();self.owns=False;raise
        if not self.ready.wait(12):
            self.close();raise ValueError('장비 연결 응답이 없습니다.')
        result=self.snapshot()
        if not result['connected']:raise ValueError(result['message'])
        return result

    def _reader(self,process,directory):
        try:
            with (directory/'events.jsonl').open('a',encoding='utf-8') as log:
                for line in process.stdout:
                    try:data=json.loads(line)
                    except ValueError:continue
                    data['received']=time.time();log.write(json.dumps(data,ensure_ascii=False)+'\n');log.flush()
                    with self.lock:
                        event=data.get('event')
                        if event in ['ready','state']:
                            self.state.update(connected=True,joints=data['joints'],updated=time.time(),
                                active=data.get('active'),latched=data.get('latched',False),writes=data.get('writes',0),motion=data.get('motion'),grip_force=data.get('grip_force'))
                            if event=='ready':self.state['message']='연결 완료 · 토크 자동 변경 없음';self.ready.set()
                        elif event=='ack':
                            if data.get('joints'):self.state.update(joints=data['joints'],updated=time.time())
                            for key in ['active','latched','motion','grip_force']:
                                if key in data:self.state[key]=data[key]
                            if data.get('ok') and data.get('latched') is False:self.state.pop('last_error',None)
                            item=self.pending.get(data.get('request_id'))
                            if item:item['result']=data;item['event'].set()
                        elif event in ['error','fatal','notice','closed']:
                            self.state['message']=data.get('message','')
                            if event in ['error','fatal']:self.state['last_error']=data.get('message','')
                            if event in ['fatal','closed']:self.state.update(connected=False,active=None);self.ready.set()
        finally:
            with self.lock:
                self.state.update(connected=False,active=None)
                if self.owns:robot_link.LOCK.release();self.owns=False
                self.ready.set()
                for item in self.pending.values():item['event'].set()

    def send(self,action,wait=True,**kwargs):
        if action not in ['jog','halt','stop','resume','enable','disable','snapshot','disconnect','move','move_heartbeat','grip_force','grip_sample','grip_contact_stop']:
            raise ValueError('지원하지 않는 조작입니다.')
        request_id=uuid.uuid4().hex;item={'event':threading.Event(),'result':None}
        with self.lock:
            if not self.process or self.process.poll() is not None or not self.state['connected']:raise ValueError('수동 연결을 먼저 시작하세요.')
            if wait:self.pending[request_id]=item
        try:
            with self.write_lock:
                self.process.stdin.write(json.dumps(dict(action=action,request_id=request_id if wait else None,**kwargs))+'\n');self.process.stdin.flush()
            if wait:
                if not item['event'].wait(3):raise ValueError('조작 응답 시간 초과 · 정지 버튼을 누르세요.')
                result=item['result']
                if not result or not result.get('ok'):raise ValueError((result or {}).get('message','연결이 종료됐습니다.'))
            snapshot=self.snapshot()
            if wait and item['result'] and item['result'].get('telemetry'):snapshot['telemetry']=item['result']['telemetry']
            return snapshot
        finally:
            with self.lock:self.pending.pop(request_id,None)

    def close(self):
        process=self.process
        if process and process.poll() is None:
            try:self.send('disconnect')
            except Exception:pass
            try:process.stdin.close()
            except Exception:pass
            try:process.wait(timeout=4)
            except subprocess.TimeoutExpired:process.terminate()
        return self.snapshot()


manual=ManualControl()
