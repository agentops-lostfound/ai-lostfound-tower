"""로컬 Studio 등록정보와 실장비 상태 조회. 이동 명령 경로 없음."""
import os
import json
from pathlib import Path
import subprocess
import threading
import time
import requests

BASE=os.environ.get('FIELD_VISION_STUDIO_API','http://127.0.0.1:7860/api')
CONTAINER=os.environ.get('FIELD_VISION_STUDIO_CONTAINER','physical-ai-studio-cuda')
SERIAL=os.environ.get('FIELD_VISION_FOLLOWER_SERIAL','')
PROJECT=os.environ.get('FIELD_VISION_PROJECT_ID','')
LOCK=threading.Lock()
LAST=None


def status(probe=False):
    global LAST
    if not SERIAL or not PROJECT:
        raise ValueError('FIELD_VISION_FOLLOWER_SERIAL과 FIELD_VISION_PROJECT_ID를 설정하세요.')
    projects=requests.get(BASE+'/projects',timeout=5);projects.raise_for_status()
    project=next((p for p in projects.json() if p['id']==PROJECT),None)
    if not project: raise ValueError('현재 장비의 Studio 프로젝트를 찾지 못했습니다.')
    r=requests.get(BASE+f'/projects/{PROJECT}/robots',timeout=5);r.raise_for_status()
    robot=next((r for r in r.json() if r.get('type')=='SO101_Follower' and r.get('payload',{}).get('serial_number')==SERIAL),None)
    if not robot: raise ValueError('지정한 팔로워 시리얼의 등록정보가 없습니다.')
    r=requests.get(BASE+'/runtime/sessions',timeout=5);r.raise_for_status();sessions=r.json()
    if probe:
        if sessions: raise ValueError('Studio 실행 세션이 있습니다. 직렬 직접 조회를 생략합니다.')
        if not LOCK.acquire(blocking=False): raise ValueError('장비 조회 중입니다. 잠시 후 다시 시도하세요.')
        try:
            source=(Path(__file__).parent/'robot_probe.py').read_text(encoding='utf-8')
            payload=robot['payload']
            cmd=['docker','exec','-i',CONTAINER,'/app/application/backend/.venv/bin/python','-c',source]
            done=subprocess.run(cmd,input=json.dumps({'port':payload['connection_string'],'calibration':payload['calibration']}),
                                capture_output=True,text=True,encoding='utf-8',timeout=18)
            try: result=json.loads(done.stdout)
            except ValueError: raise ValueError('장비 조회 응답을 읽지 못했습니다: '+done.stderr[-300:])
            if done.returncode or result.get('error'): raise ValueError(result.get('error','장비 조회 실패'))
            LAST=dict(result,captured=time.time(),serial=SERIAL,port=payload['connection_string'])
        finally: LOCK.release()
    return {'studio_connected':True,'project_id':PROJECT,'project_name':project['name'],
        'robot_id':robot['id'],'serial':SERIAL,'robot_name':robot['name'],'sessions':sessions,
        'observation':LAST,'robot_ready':False,'motion_available':False,
        'next_step':'보관함과 로봇 좌표 보정 · 이동 경로 검증 필요'}
