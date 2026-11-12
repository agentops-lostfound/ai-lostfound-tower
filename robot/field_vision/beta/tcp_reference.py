"""ArUco reference approach and independently observed TCP position samples."""
import time
import threading
import json
import cv2
import numpy as np
from PIL import Image
from .config import DATA
from .coordinates import geometry
from .robot_frame import transform,load as frame_config
from .robot_actions import actions, fresh, validate_goal
from .approach_path import context,plan_path,pose
from .tcp_calibration import signature,stationary_sample,draft,write_json

LOCK=threading.RLock()
LATEST=None
POINTS={'center':(0,0),'left':(-40,0),'right':(40,0),'near':(0,40),'far':(0,-40)}


def board_point(config,key):
    if config['mode']!='aruco' or not config['width_mm'] or not config['height_mm']:
        raise ValueError('실제 ArUco 4개와 저장된 가로·세로 mm가 필요합니다.')
    if key not in POINTS:raise ValueError('기준점을 선택하세요.')
    point=np.array([config['width_mm']/2,config['height_mm']/2])+POINTS[key]
    if np.any(point<0) or np.any(point>[config['width_mm'],config['height_mm']]):raise ValueError('선택한 기준점이 보관함 밖입니다.')
    return point.tolist()


def reference_info(image,key,height):
    if type(height) not in (int,float) or not np.isfinite(height) or not 30<=height<=100:
        raise ValueError('기준점 접근 높이는 마커 평면 위 30~100mm입니다.')
    config,corners,ids=geometry(image);point=board_point(config,key)
    target=transform(point,height)
    board=np.array([[0,0],[config['width_mm'],0],[config['width_mm'],config['height_mm']],[0,config['height_mm']]],np.float32)
    matrix=cv2.getPerspectiveTransform(board,corners.astype(np.float32))
    pixel=cv2.perspectiveTransform(np.array(point,np.float32).reshape(1,1,2),matrix)[0,0]
    return {'key':key,'board_mm':point,'height_mm':height,'target_robot_mm':target['approach_mm'],
            'surface_mm':target['surface_mm'],'corners_pixels':corners.tolist(),'detected_ids':ids,
            'pixel':pixel.tolist(),'frame':frame_config(),'width_mm':config['width_mm'],'height_board_mm':config['height_mm'],
            'note':'노랑은 마커 평면의 목표 수직 투영점입니다. 높이가 있는 집게와 영상에서 겹치는 것만으로 3D 도착을 확정하지 않습니다.'}


def snapshot():
    with LOCK:return json.loads(json.dumps(LATEST)) if LATEST else None


def overlay(image,info):
    rgb=np.asarray(image.convert('RGB')).copy();p=tuple(np.rint(info['pixel']).astype(int))
    cv2.polylines(rgb,[np.rint(info['corners_pixels']).astype(np.int32)],True,(60,190,160),2)
    cv2.drawMarker(rgb,p,(255,220,35),cv2.MARKER_CROSS,36,3)
    cv2.circle(rgb,p,18,(255,220,35),2)
    text='TARGET %.1f, %.1f mm | height +%.1f mm'%(*info['board_mm'],info['height_mm'])
    cv2.rectangle(rgb,(0,0),(rgb.shape[1],38),(20,30,20),-1)
    cv2.putText(rgb,text,(10,25),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,220,35),2,cv2.LINE_AA)
    return Image.fromarray(rgb)


def start(engine,key,height):
    with actions.lock:
        if actions.snapshot()['running']:raise ValueError('기존 동작을 종료하세요.')
        return _start(engine,key,height)


def _start(engine,key,height):
    # Resolve current markers BEFORE launch; an invalid reference never moves.
    image,_,ts=engine.cameras['top'].snapshot()
    if time.time()-ts>1:raise ValueError('탑뷰 최신 프레임이 필요합니다.')
    info=reference_info(image,key,height)
    reference=json.loads((DATA/'working_calibration.json').read_text(encoding='utf-8'))
    state=fresh()
    if state['active']:raise ValueError('수동 조작을 종료하세요.')
    if state['latched']:
        from .manual_control import manual
        manual.send('resume')
    def run():
        global LATEST
        with LOCK:LATEST=None
        fresh_image,_,captured=engine.cameras['top'].snapshot()
        current=reference_info(fresh_image,key,height)
        if time.time()-captured>1 or current['frame']!=info['frame'] or np.max(np.abs(np.asarray(current['corners_pixels'])-info['corners_pixels']))>8:
            raise ValueError('이동 전 보관함/카메라 기준이 바뀌었습니다.')
        state=actions.check();model,q,_,_=context(reference,state)
        route=plan_path(reference,state,info['target_robot_mm'],info['surface_mm'][2],relaxed=True,fixed_roll=float(q[4]))
        actions.log('reference_path','ArUco 기준점 자동 계산 · 손목 회전 유지 · 최대 기울기 10°',target=info,route=route)
        record=dict(info,reference_signature=signature(reference),route=route,started=time.time(),status='moving',move_id=actions.snapshot()['run_id'])
        with LOCK:LATEST=json.loads(json.dumps(record))
        try:
            for i,waypoint in enumerate(route['waypoints']):
                validate_goal(waypoint['target'],actions.check())
                actions.move(waypoint['target'],f'ArUco 기준점 접근 {i+1}/{len(route["waypoints"])}',arrival_tolerance_ticks=12 if i==len(route['waypoints'])-1 else 46)
            current=actions.check();actual_pose=pose(reference,current)
            if actual_pose['down_error_deg']>10:raise ValueError('기준점 도착 기울기가 10°를 넘습니다. 개방 중단')
            by={j['name']:j for j in current['joints']}
            opening={n:j['raw_ticks'] for n,j in by.items()}
            opening['gripper']=round((by['gripper']['min_ticks']+by['gripper']['max_ticks'])/2)
            actions.move(opening,'기준점 도착 후 집게 50% 개방',gripper_only=True)
            record['status']='arrived'
        except Exception as exc:
            record.update(status='stopped',error=str(exc));raise
        finally:
            from .manual_control import manual
            feedback=manual.snapshot()
            if feedback.get('connected') and feedback.get('age') is not None and feedback['age']<.8:
                record['feedback_model_pose']=pose(reference,feedback)
            record['finished']=time.time()
            with LOCK:LATEST=record
            write_json(DATA/'tcp_reference_last.json',record)
            actions.log('reference_result','기준점 이동 종료 · 실물 위치는 별도 측정 필요',result=record)
    return actions.launch('tcp_reference',run)


def record_observation(engine,delta,height,*,verification=False,move_id=None):
    """delta: required physical correction right/down in board mm, never FK."""
    with actions.lock:
        if actions.snapshot()['running']:raise ValueError('기준점 이동 종료 후 실제 차이를 입력하세요.')
        last=snapshot()
        if not last or 'finished' not in last:raise ValueError('먼저 기준점으로 이동하세요.')
        if not move_id or last['move_id']!=move_id:raise ValueError('기준점 이동 기록이 바뀌었습니다. 현재 결과를 다시 확인하세요.')
        delta=np.asarray(delta,float)
        if delta.shape!=(2,) or not np.isfinite(delta).all() or np.max(np.abs(delta))>50:
            raise ValueError('실물 이동 필요량은 탑뷰 오른쪽/아래쪽 기준 ±50mm 이내입니다.')
        reference=json.loads((DATA/'working_calibration.json').read_text(encoding='utf-8'))
        image,_,ts=engine.cameras['top'].snapshot();info=reference_info(image,last['key'],last['height_mm'])
        if (time.time()-ts>1 or last['reference_signature']!=signature(reference) or info['frame']!=last['frame']
                or np.max(np.abs(np.asarray(info['corners_pixels'])-last['corners_pixels']))>8):
            raise ValueError('기준점 이동 후 좌표 기준이 바뀌었습니다. 다시 이동하세요.')
        measured_board=(np.asarray(last['board_mm'])-delta).tolist()
        sample=stationary_sample(measured_board,height)
        sample.update(source='physical_observation_after_reference_move',required_board_motion_mm=delta.tolist(),reference_target_board_mm=last['board_mm'])
        d=draft()
        if any(s.get('reference_move_id')==move_id for s in d['samples']):raise ValueError('이 이동의 실물 관측은 이미 등록했습니다.')
        if d.get('reference_signature') not in (None,sample['reference_signature']):raise ValueError('기존 등록과 기준이 다릅니다. 새 보정을 시작하세요.')
        if verification:
            from .tcp_calibration import verify_sample
            if not d.get('fit'):raise ValueError('먼저 공통 오차 계산을 완료하세요.')
            d['fit']['verification']=verify_sample(d['fit'],sample,d['samples']);d['fit']['verified']=True
        else:
            sample['reference_move_id']=move_id
            d.setdefault('samples',[]).append(sample);d['reference_signature']=sample['reference_signature'];d.pop('fit',None)
        write_json(DATA/'tcp_draft.json',d)
        return sample
