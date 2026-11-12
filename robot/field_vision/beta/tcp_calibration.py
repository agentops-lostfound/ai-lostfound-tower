"""Object-independent base translation / tool-center calibration from taught points."""
import hashlib
import json
import time
import uuid
import numpy as np
from .config import DATA


def signature(reference):
    keys=('model_sha256','reference_raw_ticks','reference_model_radians','robot_frame','serial')
    return hashlib.sha256(json.dumps({k:reference[k] for k in keys},sort_keys=True).encode()).hexdigest()


def read_json(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def active_profile(model_hash,directory=None):
    directory=DATA if directory is None else directory
    value=read_json(directory/'tcp_active.json')
    if not value:return None
    reference=read_json(directory/'working_calibration.json')
    frame=read_json(directory/'robot_frame.json')
    if (not value.get('verified') or not reference or value.get('reference_signature')!=signature(reference)
            or value.get('model_sha256')!=model_hash or reference['robot_frame']!=frame):
        raise ValueError('공통 TCP 보정 이후 로봇/보관함 기준이 바뀌었습니다. TCP 보정을 다시 검증하세요.')
    return value


def fit_samples(samples):
    if len(samples)<4:raise ValueError('서로 다른 집게 기울기의 기준 자세가 최소 4개 필요합니다.')
    rotations=np.asarray([s['rotation'] for s in samples],float)
    positions=np.asarray([s['model_position_mm'] for s in samples],float)
    measured=np.asarray([s['measured_position_mm'] for s in samples],float)
    if rotations.shape!=(len(samples),3,3) or positions.shape!=measured.shape or positions.shape!=(len(samples),3):
        raise ValueError('기준 자세 형식 오류')
    if not all(np.isfinite(a).all() for a in (rotations,positions,measured)):
        raise ValueError('유효한 실측 좌표가 필요합니다.')
    if not np.allclose(rotations.transpose(0,2,1)@rotations,np.eye(3),atol=1e-5):
        raise ValueError('집게 회전행렬 오류')
    matrix=np.concatenate([np.concatenate([np.eye(3),rot],axis=1) for rot in rotations])
    singular=np.linalg.svd(matrix,compute_uv=False)
    if singular[-1]<1e-6 or singular[0]/singular[-1]>50:
        raise ValueError('베이스 오차와 TCP 오차를 분리할 수 없는 자세입니다. 손목 회전만 하지 말고 집게를 앞뒤·좌우로 기울여 추가 등록하세요.')
    params=np.linalg.lstsq(matrix,(measured-positions).ravel(),rcond=None)[0]
    errors=(matrix@params).reshape(-1,3)+positions-measured
    distances=np.linalg.norm(errors,axis=1)
    rms=float(np.sqrt(np.mean(distances**2)))
    if rms>3 or distances.max()>6:
        raise ValueError('기준점 정합 오차가 큽니다 (RMS %.1fmm / 최대 %.1fmm). 좌표·집게 끝 기준과 영점을 다시 확인하세요.'%(rms,distances.max()))
    if np.linalg.norm(params[:3])>80 or np.linalg.norm(params[3:])>80:
        raise ValueError('보정량이 80mm를 넘습니다. 단위·관절 영점·로봇 축 정합 확인이 필요합니다.')
    return {'base_translation_mm':params[:3].tolist(),'tcp_local_mm':params[3:].tolist(),
            'rms_mm':rms,'max_error_mm':float(distances.max()),'condition_number':float(singular[0]/singular[-1]),
            'sample_errors_mm':errors.tolist(),'sample_count':len(samples),'verified':False}


def verify_sample(profile,sample,samples):
    measured=np.asarray(sample['measured_position_mm'])
    if min(np.linalg.norm(measured-np.asarray(s['measured_position_mm'])) for s in samples)<30:
        raise ValueError('검증은 등록했던 기준점에서 30mm 이상 떨어진 다른 지점에서 진행하세요.')
    predicted=np.asarray(sample['model_position_mm'])+profile['base_translation_mm']+np.asarray(sample['rotation'])@profile['tcp_local_mm']
    error=float(np.linalg.norm(predicted-measured))
    if error>5:raise ValueError('별도 지점 검증 오차 %.1fmm로 5mm 기준 초과 · 보정 적용 안 함'%error)
    return {'error_mm':error,'sample':sample,'predicted_mm':predicted.tolist(),'passed':True}


def draft():
    return read_json(DATA/'tcp_draft.json',{'samples':[]})


def status():
    from .kinematics import Model
    d=draft();result={'draft':d,'active':None,'validation_error':None}
    try:result['active']=active_profile(Model(use_position_calibration=False).hash)
    except ValueError as exc:result['validation_error']=str(exc)
    samples=d.get('samples',[])
    result['pose_diversity']={'count':len(samples),'ready':False,'condition_number':None}
    if samples:
        result['pose_diversity']['contact_reference_consistent']=all(s.get('contact_reference_id')=='fixed-distal-strip-v1' for s in samples)
        matrix=np.concatenate([np.c_[np.eye(3),np.asarray(s['rotation'])] for s in samples])
        singular=np.linalg.svd(matrix,compute_uv=False)
        condition=float(singular[0]/max(singular[-1],1e-12)) if len(singular)==6 else float('inf')
        result['pose_diversity'].update(ready=len(samples)>=4 and condition<=50,condition_number=condition if np.isfinite(condition) else None)
    return result


def stationary_sample(board_xy,height):
    from .robot_actions import actions,fresh
    from .robot_frame import transform,load
    from .kinematics import Model,NAMES
    from .approach_path import SIGN
    # Capture only, no torque or position writes. Serial ownership stays shared.
    if actions.snapshot()['running']:raise ValueError('실행을 종료한 뒤 기준점을 등록하세요.')
    before=fresh()
    if before['active']:raise ValueError('수동 이동을 멈춘 뒤 등록하세요.')
    if any(not j['in_range'] for j in before['joints']):raise ValueError('관절 범위 안에서 등록하세요.')
    jaw=next(j for j in before['joints'] if j['name']=='gripper')
    half=(jaw['min_ticks']+jaw['max_ticks'])/2
    if abs(jaw['raw_ticks']-half)>30:raise ValueError('집게를 50% 개방한 뒤 표시한 고정 손가락 접촉 구간의 같은 실물 지점을 기준점에 맞추세요.')
    if type(height) not in (int,float) or not np.isfinite(height) or not 0<=height<=100:raise ValueError('기준점 높이는 마커 평면 위 0~100mm입니다.')
    reference=read_json(DATA/'working_calibration.json')
    if not reference or reference['robot_frame']!=load():raise ValueError('보관함↔로봇 기준점 설정을 먼저 확인하세요.')
    target=np.asarray(transform(board_xy,20)['surface_mm'])+height*np.asarray(load()['up_axis'])
    time.sleep(.35)
    after=fresh();by={j['name']:j for j in after['joints']};old={j['name']:j for j in before['joints']}
    if after['active'] or any(abs(by[n]['raw_ticks']-old[n]['raw_ticks'])>3 for n in NAMES+['gripper']):
        raise ValueError('등록 중 팔이 움직였습니다. 고정한 상태에서 다시 등록하세요.')
    q0=np.asarray(reference['reference_model_radians']);r=np.asarray(reference['reference_raw_ticks'])
    raw=np.asarray([by[n]['raw_ticks'] for n in NAMES]);q=q0+(raw-r)*SIGN*2*np.pi/4096
    model=Model(use_position_calibration=False)
    if model.hash!=reference['model_sha256']:raise ValueError('로봇 모델과 영점 보정이 다릅니다.')
    f=model.forward(q)
    return {'id':uuid.uuid4().hex,'captured':time.time(),'raw_ticks':raw.tolist(),
            'model_position_mm':f['position'].tolist(),'rotation':f['rotation'].tolist(),
            'measured_position_mm':target.tolist(),'board_mm':list(board_xy),'height_mm':height,
            'reference_signature':signature(reference),'gripper_ticks':jaw['raw_ticks'],'aperture_percent':50,'contact_reference_id':'fixed-distal-strip-v1','contact_status':'provisional'}


def update(operation,board_xy=None,height=0,sample_id=None):
    from .robot_actions import actions
    from .manual_control import manual
    with actions.lock:
        if actions.snapshot()['running']:raise ValueError('동작 중에는 TCP 보정을 변경할 수 없습니다.')
        if manual.snapshot().get('active'):raise ValueError('수동 이동을 멈춘 뒤 보정을 변경하세요.')
        d=draft();path=DATA/'tcp_draft.json'
        if operation=='reset':
            d={'samples':[]};write_json(path,d)
        elif operation=='disable':
            current=read_json(DATA/'tcp_active.json')
            if current:
                write_json(DATA/'archives'/('tcp-'+uuid.uuid4().hex+'.json'),current)
                (DATA/'tcp_active.json').unlink()
        elif operation in ('capture','verify'):
            sample=stationary_sample(board_xy,height)
            if d.get('reference_signature') not in (None,sample['reference_signature']):raise ValueError('기준 설정이 바뀌었습니다. 새 보정을 시작하세요.')
            if operation=='capture':
                d.setdefault('samples',[]).append(sample);d.pop('fit',None);d['reference_signature']=sample['reference_signature']
            else:
                if not d.get('fit'):raise ValueError('먼저 기준점 계산을 완료하세요.')
                d['fit']['verification']=verify_sample(d['fit'],sample,d['samples']);d['fit']['verified']=True
            write_json(path,d)
        elif operation=='delete':
            d['samples']=[s for s in d['samples'] if s['id']!=sample_id];d.pop('fit',None);write_json(path,d)
        elif operation=='fit':
            d['fit']=fit_samples(d['samples']);write_json(path,d)
        elif operation=='activate':
            if not d.get('fit',{}).get('verified'):raise ValueError('별도 지점 검증을 먼저 완료하세요.')
            reference=read_json(DATA/'working_calibration.json')
            if signature(reference)!=d['reference_signature']:raise ValueError('기준 설정이 바뀌었습니다. 다시 보정하세요.')
            profile=dict(d['fit'],reference_signature=d['reference_signature'],model_sha256=reference['model_sha256'],
                         id=uuid.uuid4().hex,created=time.time(),scope='all_objects',samples=d['samples'],
                         aperture_percent=50,tcp_definition='center_between_fingertips_at_half_open')
            previous=read_json(DATA/'tcp_active.json')
            if previous:write_json(DATA/'archives'/('tcp-'+uuid.uuid4().hex+'.json'),previous)
            write_json(DATA/'tcp_active.json',profile)
        else:raise ValueError('지원하지 않는 보정 작업입니다.')
        return status()
