"""보관함 평면 좌표. 로봇 좌표 보정/이동은 포함하지 않는다."""
import json
import time
import cv2
import numpy as np
from .config import DATA

PATH=DATA/'board_coordinates.json'
DEFAULT={'mode':'temporary','points':[[.12,.16],[.91,.16],[.93,.86],[.09,.86]],
         'dictionary':'DICT_4X4_1000','ids':[0,1,2,3],'width_mm':None,'height_mm':None}
DICTIONARIES=['DICT_4X4_1000','DICT_5X5_1000','DICT_6X6_1000','DICT_7X7_1000','DICT_ARUCO_ORIGINAL']


def load():
    return json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else dict(DEFAULT)


def validate(value):
    c=dict(DEFAULT,**value)
    if c['mode'] not in ['temporary','aruco']: raise ValueError('좌표 기준 모드를 확인하세요.')
    if c['dictionary'] not in DICTIONARIES: raise ValueError('지원하는 ArUco 사전을 선택하세요.')
    ids=c['ids']
    if not isinstance(ids,list) or len(ids)!=4 or any(type(i)!=int or i<0 for i in ids) or len(set(ids))!=4:
        raise ValueError('좌상·우상·우하·좌하 순서로 서로 다른 정수 ID 4개가 필요합니다.')
    dictionary=cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco,c['dictionary']))
    if max(ids)>=len(dictionary.bytesList): raise ValueError('마커 ID가 선택 사전의 범위를 벗어났습니다.')
    p=np.asarray(c['points'],dtype=np.float32)
    if p.shape!=(4,2) or not np.isfinite(p).all() or np.any(p<0) or np.any(p>1):
        raise ValueError('네 꼭짓점은 0~1 좌표여야 합니다.')
    if not cv2.isContourConvex(p.reshape(-1,1,2)) or cv2.contourArea(p,oriented=True)<.01:
        raise ValueError('겹치지 않게 좌상→우상→우하→좌하 순서로 지정하세요.')
    w,h=c['width_mm'],c['height_mm']
    if (w is None)!=(h is None): raise ValueError('가로·세로 길이를 함께 입력하세요.')
    if w is not None:
        if not all(type(v) in (int,float) and np.isfinite(v) and 0<v<=10000 for v in [w,h]):
            raise ValueError('가로·세로는 0 초과 10000mm 이하입니다.')
    return c


def save(value):
    c=validate(value);DATA.mkdir(exist_ok=True)
    temp=PATH.with_suffix('.tmp');temp.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(PATH)
    return c


def geometry(image, config=None):
    c=validate(config or load());detected=[]
    if c['mode']=='temporary':
        points=np.asarray(c['points'],np.float32)*[image.width,image.height]
    else:
        gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
        parameters=cv2.aruco.DetectorParameters()
        parameters.adaptiveThreshWinSizeMax=53
        parameters.adaptiveThreshWinSizeStep=4
        parameters.cornerRefinementMethod=cv2.aruco.CORNER_REFINE_SUBPIX
        detector=cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco,c['dictionary'])),parameters)
        found={}
        # Small printed tags can alternate between detected/missing. Retry
        # the SAME frame at higher sampling; never reuse stale marker positions.
        for scale in [1,2,3]:
            sample=gray if scale==1 else cv2.resize(gray,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
            corners,ids,_=detector.detectMarkers(sample)
            current={}
            if ids is not None:
                for pts,ident in zip(corners,ids.ravel()):
                    ident=int(ident)
                    if ident in current: raise ValueError('중복된 ArUco ID가 보입니다.')
                    current[ident]=pts.reshape(4,2).mean(axis=0)/scale
            if len(set(current)&set(c['ids']))>len(set(found)&set(c['ids'])): found=current
            if all(i in found for i in c['ids']): break
        detected=list(found)
        missing=[i for i in c['ids'] if i not in found]
        if missing: raise ValueError('기준 마커 부족: '+', '.join(map(str,missing)))
        points=np.asarray([found[i] for i in c['ids']],np.float32)
    points=np.asarray(points,np.float32)
    normalized=points/[image.width,image.height]
    validate(dict(c,points=normalized.tolist()))
    return c,points,detected


def convert(image, point, config=None):
    c,points,detected=geometry(image,config)
    matrix=cv2.getPerspectiveTransform(points,np.array([[0,0],[1,0],[1,1],[0,1]],np.float32))
    p=np.asarray(point,np.float32)
    if p.shape!=(2,) or not np.isfinite(p).all(): raise ValueError('영상 좌표 x,y를 확인하세요.')
    uv=cv2.perspectiveTransform(p.reshape(1,1,2),matrix)[0,0]
    inside=bool(np.all(uv>=0)&np.all(uv<=1))
    return {'mode':c['mode'],'temporary':c['mode']=='temporary','normalized':uv.tolist(),'inside':inside,
        'mm':[float(uv[0]*c['width_mm']),float(uv[1]*c['height_mm'])] if c['width_mm'] else None,
        'origin':'top_left','axes':'x:right,y:down','marker_reference':'marker_centers',
        'corners_pixels':points.tolist(),'detected_ids':detected,'robot_ready':False,
        'note':'보관함 평면 투영 좌표 · 높이/렌즈왜곡/로봇 보정 미적용'}
