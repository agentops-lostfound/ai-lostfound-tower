"""저장 자세를 모델에서 재현하는 임시 정합 후보. 실제 이동에 사용하지 않는다."""
from .robot_link import SERIAL
import hashlib
import json
from pathlib import Path
import time
import shutil
import numpy as np
from .config import DATA
from .kinematics import Model,NAMES
from .robot_frame import load as frame_config

SOURCES=[
    ('20261110-154814-9f8ab7/pose-f41c1a3e47',[180,0,80],'영점 계산에 사용'),
    ('20261110-160805-074d69/pose-87481b6c12',[150,0,80],'추가 비교 자세'),
    ('20261110-161216-6fe4e3/pose-c76bfa65f5',[150,30,80],'추가 비교 자세'),
]


def reproduce(config,raw):
    raw=np.asarray(raw,float)
    if raw.shape!=(5,) or not np.isfinite(raw).all():raise ValueError('5개 관절 엔코더 값이 필요합니다.')
    if abs(raw[4]-config['reference_raw_ticks'][4])>5:
        raise ValueError('5번 손목 회전의 별도 정합이 필요합니다. 기준에서 변경된 자세는 재현하지 않습니다.')
    return np.asarray(config['reference_model_radians'])+(raw-config['reference_raw_ticks'])*np.asarray(config['directions'])*2*np.pi/4096


def build():
    model=Model();poses=[]
    for relative,target,role in SOURCES:
        path=DATA/'manual_sessions'/relative/'pose.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        by_name={j['name']:j for j in data['state']['joints']}
        raw=[by_name[n]['raw_ticks'] for n in NAMES]
        poses.append({'label':data['label'],'source':relative,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'captured':data['captured'],'raw_ticks':raw,'user_target_xyz_mm':target,'role':role,'measurements_approximate':True})
    reference=model.inverse(poses[0]['user_target_xyz_mm'],tool_down=True)
    if not reference['reachable_in_model']:raise ValueError('중앙 기준 모델 자세를 구하지 못했습니다.')
    config={'serial':SERIAL,'created':time.time(),'model_sha256':model.hash,'joint_names':NAMES,
        'reference_raw_ticks':poses[0]['raw_ticks'],'reference_model_radians':reference['joint_radians'],
        'directions':[1,1,1,1,0],'roll_mapping':'기준값에 고정 · 부호/영점 미검증',
        'joint_limits_radians':model.limits.tolist(),'model_base_offset_mm':model.base_offset.tolist(),
        'chain':[{'name':n,'origin':t.tolist(),'axis':a.tolist()} for n,t,a in model.chain],
        'robot_frame':frame_config(),'hardware_motion_allowed':False,'alignment_status':'provisional_visualization_only',
        'assumptions':['중앙 XY와 높이 65mm는 사용자 대략 측정 기준','중앙에서 집게 축이 수직 아래라고 가정',
            '1~4번 회전 방향 + 가설을 사용','5번은 기준값 고정 · 회전 시 미지원','실제 집게 TCP 및 충돌 검증 전'],
        'poses':poses}
    for pose in poses:
        q=reproduce(config,pose['raw_ticks']);fk=model.forward(q)
        pose.update(joint_radians=q.tolist(),model_xyz_mm=fk['position'].tolist(),model_points_mm=fk['points'],
            difference_mm=(fk['position']-pose['user_target_xyz_mm']).tolist(),
            difference_norm_mm=float(np.linalg.norm(fk['position']-pose['user_target_xyz_mm'])))
        folder=DATA/'media/reproduction'/Path(pose['source']).name;folder.mkdir(parents=True,exist_ok=True)
        pose['images']={}
        for key in ['top','arm']:
            source=DATA/'manual_sessions'/pose['source']/(key+'.jpg')
            if source.exists():
                shutil.copyfile(source,folder/(key+'.jpg'))
                pose['images'][key]='/media/reproduction/'+folder.name+'/'+key+'.jpg'
    destination=Path(__file__).parent/'static/reproduction-config.json'
    destination.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    (DATA/'provisional_reproduction.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    return config


if __name__=='__main__':
    config=build()
    print(json.dumps([{'label':p['label'],'model_xyz_mm':p['model_xyz_mm'],'difference_norm_mm':p['difference_norm_mm']} for p in config['poses']],ensure_ascii=True))
