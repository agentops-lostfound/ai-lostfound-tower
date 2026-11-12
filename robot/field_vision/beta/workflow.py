"""Project beta workflow settings, persisted independently of camera settings."""
import json
import math
import threading
import time
from .config import DATA

LOCK=threading.RLock()
DEFAULTS=dict(auto_intake=False,found_place='',approach_height_mm=45.,grasp_height_mm=5.,
              # probe_mm: first response probe only when no learned px/mm exists.
              # correction_mm: TOTAL lateral travel limit from the start position.
              gap_low_px=6.,gap_high_px=56.,probe_mm=4.,correction_mm=12.,
              preoffset_k=.35,preoffset_c_mm=4.,preoffset_max_mm=30.,
              finish_mode='hold',return_on_unconfirmed=False,calibration_stop=False,
              # v0.2.46 drop-off: one taught joint pose + transfer height above the board plane.
              dropoff_pose=None,transfer_height_mm=120.,
              # Extra close after the first close stops: torque 200, then hold (user-set, v0.2.44).
              extra_close_seconds=1.5)

def load():
    with LOCK:
        path=DATA/'workflow.json'
        return dict(DEFAULTS,**(json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}))

def save(values):
    with LOCK:
        result=load()
        for key in DEFAULTS:
            if key in values and key!='dropoff_pose':result[key]=values[key]
        for key,low,high in [('approach_height_mm',30,100),('grasp_height_mm',5,30),('gap_low_px',2,30),('gap_high_px',10,100),('probe_mm',1,5),('correction_mm',1,20),('preoffset_k',0,1.2),('preoffset_c_mm',-10,15),('preoffset_max_mm',0,40),('transfer_height_mm',60,200),('extra_close_seconds',0.3,5)]:
            v=float(result[key])
            if not math.isfinite(v) or not low<=v<=high:raise ValueError(f'{key}: {low}~{high} 범위')
            result[key]=v
        if result['gap_high_px']<=result['gap_low_px']+4:raise ValueError('간격 상한은 하한보다 4px 이상 커야 합니다.')
        if result['finish_mode'] not in ['hold','return']:raise ValueError('종료 방식이 잘못되었습니다.')
        for key in ['auto_intake','return_on_unconfirmed','calibration_stop']:
            if type(result[key]) is not bool:raise ValueError('켜기/끄기 값이 필요합니다.')
        result['found_place']=str(result['found_place'])[:200]
        write(result);return result

def write(result):
    path=DATA/'workflow.json';tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)

def teach(operation,state):
    with LOCK:
        result=load()
        if operation=='clear':result['dropoff_pose']=None
        elif operation=='dropoff':
            if state.get('active'):raise ValueError('정지 상태에서 놓기 위치를 저장하세요.')
            result['dropoff_pose']={'ticks':{j['name']:j['raw_ticks'] for j in state['joints']},'created':time.time()}
        else:raise ValueError('지원하지 않는 놓기 위치 작업')
        result.pop('return_waypoints',None)
        write(result);return result
