"""보관함 평면 → 측정한 로봇 기준 좌표(mm). 이동/IK 없음."""
from .robot_link import SERIAL
import json
import time
import numpy as np
from .config import DATA
from .coordinates import load as board_config

PATH=DATA/'robot_frame.json'


def load():
    return json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else None


def fit(points, width, height):
    p=np.asarray(points,dtype=float)
    if p.shape!=(3,3) or not np.isfinite(p).all() or np.max(np.abs(p))>3000:
        raise ValueError('세 기준점의 로봇 기준 X,Y,Z(mm)를 모두 입력하세요. 각 값은 ±3000mm 이내입니다.')
    if not width or not height: raise ValueError('보관함 실측 치수를 먼저 저장하세요.')
    u=p[1]-p[0];v=p[2]-p[0]
    lu,lv=np.linalg.norm(u),np.linalg.norm(v)
    if abs(lu-width)>max(5,width*.03) or abs(lv-height)>max(5,height*.03):
        raise ValueError('기준점 사이 거리가 보관함 가로·세로와 다릅니다. 단위와 측정 기준을 확인하세요.')
    x=u/lu;y=v/lv
    if abs(float(x@y))>.08: raise ValueError('가로·세로 기준축이 직각이 아닙니다. 기준점 측정을 확인하세요.')
    # Orthonormal axes preserve distance, rather than fitting a stretched plane.
    y=(y-x*(x@y));y/=np.linalg.norm(y)
    normal=np.cross(x,y)
    # The board is assumed horizontal for this first beta.
    if abs(normal[2])<.95: raise ValueError('이번 베타는 수평 보관함만 지원합니다. Z 기준을 확인하세요.')
    if normal[2]<0:normal=-normal
    residual=float(np.linalg.norm(p[0]+y*height-p[2]))
    return {'origin':p[0].tolist(),'x_axis':x.tolist(),'y_axis':y.tolist(),'up_axis':normal.tolist(),
            'measurement_residual_mm':residual}


def save(points):
    c=board_config()
    if c['mode']!='aruco': raise ValueError('실제 ArUco 모드에서 보정하세요.')
    result=fit(points,c['width_mm'],c['height_mm'])
    result.update(points=points,board_config=c,saved=time.time(),serial=SERIAL,
                  reference='measured_robot_frame_mm',robot_ready=False)
    DATA.mkdir(exist_ok=True);temp=PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(PATH)
    return result


def transform(point, approach_mm, config=None):
    c=config or load()
    if c is None: raise ValueError('보관함↔로봇 기준점 보정이 필요합니다.')
    if c['board_config']!=board_config(): raise ValueError('보관함 설정이 변경됐습니다. 로봇 기준점 보정을 다시 확인하세요.')
    p=np.asarray(point,dtype=float)
    if p.shape!=(2,) or not np.isfinite(p).all(): raise ValueError('보관함 X,Y(mm)가 필요합니다.')
    if not np.isfinite(approach_mm) or not 20<=approach_mm<=200: raise ValueError('접근 높이는 20~200mm입니다.')
    w,h=c['board_config']['width_mm'],c['board_config']['height_mm']
    if not (0<=p[0]<=w and 0<=p[1]<=h): raise ValueError('보관함 영역 밖의 위치입니다.')
    base=np.asarray(c['origin'])+p[0]*np.asarray(c['x_axis'])+p[1]*np.asarray(c['y_axis'])
    above=base+approach_mm*np.asarray(c['up_axis'])
    return {'surface_mm':base.tolist(),'approach_mm':above.tolist(),'height_above_marker_plane_mm':approach_mm,
            'reference':'measured_robot_frame_mm','robot_ready':False,'motion_sent':False,
            'note':'측정한 기준 좌표의 목표 미리보기 · IK/집게 TCP/장애물/로봇 축 정합 검증 전'}
