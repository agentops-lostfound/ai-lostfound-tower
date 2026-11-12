"""Board-plane position correction fitted from user top-view reports.

Each point in position_calibration_points.json holds the detected board position
(board_mm, x right / y down in the top view), the board position actually sent
(board_target_mm, if a correction was already applied) and the user's report of
where the closed-jaw centre had to move (user_required_move_topview_mm: right/up).
The fit is a similarity about the points' centre: delta = s*(b-c) + r*perp(b-c) + t.
"""
import json,math,time
import numpy as np
from .config import DATA

POINTS=DATA/'position_calibration_points.json'
PROFILE=DATA/'board_correction.json'
MAX_SHIFT_MM=25.


def needed_delta(point):
    """Board-frame delta (target - detected) that would have hit the object."""
    move=point['user_required_move_topview_mm']
    board=np.asarray(point['board_mm'],float)
    sent=np.asarray(point.get('board_target_mm') or board,float)
    return sent-board+np.array([move['right'],-move['up']],float)


def fit(points):
    used=[p for p in points if p.get('user_required_move_topview_mm')]
    if len(used)<3:raise ValueError('보정점 3개 이상 필요')
    B=np.array([p['board_mm'] for p in used],float);D=np.array([needed_delta(p) for p in used])
    # Far-tilted points carry extra uncertainty (tilt, uncompensated following).
    W=np.sqrt(np.repeat([.5 if p.get('far_tilt') else 1. for p in used],2))
    c=B.mean(0);X=B-c;n=len(X)
    M=np.r_[np.c_[X[:,0],-X[:,1],np.ones(n),np.zeros(n)],np.c_[X[:,1],X[:,0],np.zeros(n),np.ones(n)]]
    y=np.r_[D[:,0],D[:,1]]
    rows=np.r_[np.arange(n),np.arange(n)+n]
    sol,*_=np.linalg.lstsq(M*W[:,None],y*W,rcond=None)
    profile={'center_mm':c.tolist(),'scale':float(sol[0]),'rotation':float(sol[1]),'shift_mm':[float(sol[2]),float(sol[3])],
             'points':[p['target_id'] for p in used],'fitted':time.time(),'method':'similarity-delta-v1'}
    residual=[float(np.linalg.norm(apply_delta(profile,b)-d)) for b,d in zip(B,D)]
    profile['residual_mm']=residual
    return profile


def apply_delta(profile,board_mm):
    a=profile['scale'];r=profile['rotation'];t=np.asarray(profile['shift_mm'],float)
    x=np.asarray(board_mm,float)-np.asarray(profile['center_mm'],float)
    delta=np.array([a*x[0]-r*x[1],a*x[1]+r*x[0]])+t
    norm=float(np.linalg.norm(delta))
    if norm>MAX_SHIFT_MM:delta*=MAX_SHIFT_MM/norm
    return delta


def load():
    try:return json.loads(PROFILE.read_text(encoding='utf-8'))
    except (OSError,ValueError):return None


def corrected(board_mm,profile=None):
    """Return (board target mm, info). No profile -> unchanged."""
    profile=load() if profile is None else profile
    if not profile or not profile.get('enabled',True):return list(map(float,board_mm)),None
    delta=apply_delta(profile,board_mm)
    return (np.asarray(board_mm,float)+delta).tolist(),{'delta_mm':delta.tolist(),'fitted':profile.get('fitted'),'method':profile.get('method')}


def refit_and_save():
    points=json.loads(POINTS.read_text(encoding='utf-8'))
    profile=fit(points);profile['enabled']=True
    PROFILE.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    return profile
