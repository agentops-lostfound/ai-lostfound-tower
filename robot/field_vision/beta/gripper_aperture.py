"""User-measured effective inner opening at the actual contact height."""
import json,math,time,hashlib
from .config import DATA

PERCENTS=[40,50,60,70,80,100]
PATH=DATA/'gripper_aperture.json'
WIDE_MM=60.        # objects at least this wide open to WIDE_PERCENT
WIDE_PERCENT=80   # user: moving finger opens toward the board edge for phone/power bank


def load(path=None):
    file=path or PATH
    return json.loads(file.read_text(encoding='utf8')) if file.exists() else {'revision':None,'height_mm':5.,'margin_mm':6.,'rows':[],'measured':False}


def save(data,path=None):
    height=float(data.get('height_mm',5));margin=float(data.get('margin_mm',6))
    if not math.isfinite(height) or not 5<=height<=30 or not math.isfinite(margin) or not 2<=margin<=20:raise ValueError('높이5~30mm, 양쪽 합계 여유2~20mm 범위입니다.')
    rows=[];seen=set();previous=-1
    supplied=data.get('rows',[])
    if not isinstance(supplied,list) or len(supplied)>len(PERCENTS):raise ValueError('측정표는 개방률별 최대6개입니다.')
    if any(not isinstance(r,dict) or type(r.get('percent')) is not int for r in supplied):raise ValueError('표에 있는 정수 개방률을 사용하세요.')
    for r in sorted(supplied,key=lambda r:r['percent']):
        percent=r['percent'];width=float(r['width_mm'])
        if percent not in PERCENTS or percent in seen or not math.isfinite(width) or not 0<width<=200:raise ValueError('개방률별 실측 폭은0~200mm 사이의 양수입니다.')
        if width<previous:raise ValueError('개방률이 커질수록 실측 폭이 작아졌습니다. 측정값을 확인하세요.')
        seen.add(percent);previous=width;rows.append({'percent':percent,'width_mm':width})
    limits=data.get('gripper_limits',[1345,2800])
    if len(limits)!=2 or not all(type(v)==int for v in limits) or limits[0]>=limits[1]:raise ValueError('그리퍼 틱 범위 오류')
    result=dict(revision=str(time.time_ns()),height_mm=height,margin_mm=margin,rows=rows,measured=bool(rows),
        gripper_limits=limits,reference='fixed-distal-strip-v1',note='접촉 높이에서 실제 두 손가락 안쪽 최소 폭. 사용자 실측, 보간 없음.')
    file=path or PATH;temp=file.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(file)
    return result


HEIGHT_REUSE_MM=3.  # v0.2.45 C4: reuse the measured table within 3mm of its contact height


def choose(width,height=5,profile=None):
    profile=load() if profile is None else profile;margin=float(profile.get('margin_mm',6))
    height_diff=abs(float(profile.get('height_mm',5))-height)
    rows=profile.get('rows',[]) if height_diff<=HEIGHT_REUSE_MM else []
    height_warning='실측 높이와 %.1fmm 차이 · 표 재사용'%height_diff if rows and height_diff>.5 else None
    if not rows:
        if width>=60 and profile.get('rows'):raise ValueError('이 집기 높이의 개방 폭 미측정 · 실측 높이%.1fmm와 %.1fmm 차이(허용 %.0fmm) · 집기 높이를 맞추거나 다시 실측하세요.'%(float(profile.get('height_mm',5)),height_diff,HEIGHT_REUSE_MM))
        if width>=60:raise ValueError('집게 개방 폭 미측정 · 폭60mm 이상 물품은 설정 → 집게 개방 폭에서 실측 후 시작하세요.')
        return dict(percent=50,width_mm=None,object_width_mm=width,margin_mm=margin,verified=False,revision=None,
                    warning='개방 폭 미측정: 60mm 미만 시험용50% 예외이며 집기 가능 보장 아님')
    if width>=WIDE_MM and not any(r['percent']>=WIDE_PERCENT for r in rows):
        # User rule (2026-11-11): wide objects (phone 73mm) may open 70~80%. 50%=82mm
        # left ~9mm total slack, so the moving finger landed on the phone. 70% is not
        # measured; the largest measured width is a monotonic LOWER bound, so gap bands
        # computed from it stay conservative while the moving side gains room.
        lower=max(rows,key=lambda r:r['percent'])
        if lower['width_mm']>=width+margin*.5:
            return dict(percent=WIDE_PERCENT,width_mm=float(lower['width_mm']),object_width_mm=width,margin_mm=margin,verified=True,
                        width_is_lower_bound=True,lower_bound_percent=lower['percent'],revision=profile['revision'],
                        gripper_limits=profile['gripper_limits'],height_mm=height,
                        note='넓은 물품 %d%% 개방 · 폭은 %d%% 실측값을 하한으로 사용'%(WIDE_PERCENT,lower['percent']))
    # v0.2.45: once 80% is measured the lower-bound branch above no longer fires;
    # wide objects must still never fall back to 50% (phone 72.7mm -> 82mm left
    # ~9mm slack and the moving finger landed on it).
    candidates=[r for r in rows if r['percent']>=WIDE_PERCENT] if width>=WIDE_MM else rows
    eligible=sorted([r for r in candidates if r['width_mm']>=width+margin],key=lambda r:r['percent'])
    if not eligible:raise ValueError('집게 개방 폭 부족 · 물품%.1fmm + 양쪽 여유%.1fmm > 실측 최대%.1fmm'%(width,margin,max(r['width_mm'] for r in rows)))
    result=dict(eligible[0],object_width_mm=width,margin_mm=margin,verified=True,revision=profile['revision'],gripper_limits=profile['gripper_limits'],height_mm=height)
    if height_warning:result['warning']=height_warning
    return result


def ticks(percent,minimum,maximum):return round(minimum+(maximum-minimum)*percent/100)


def contact_ticks(object_width_mm,profile=None):
    """Gripper ticks where an object of this width should first be touched (v0.2.51).

    Linear between measured rows (percent -> inner width); below the smallest measured
    opening the first two rows' slope is extended. None when fewer than two rows.
    """
    profile=load() if profile is None else profile
    rows=sorted(profile.get('rows',[]),key=lambda r:r['percent'])
    if len(rows)<2:return None
    lo,hi=profile.get('gripper_limits',[1345,2800])
    pts=[(ticks(r['percent'],lo,hi),float(r['width_mm'])) for r in rows]
    for (t0,w0),(t1,w1) in zip(pts,pts[1:]):
        if w0<=object_width_mm<=w1:return round(t0+(t1-t0)*(object_width_mm-w0)/(w1-w0))
    (t0,w0),(t1,w1)=(pts[0],pts[1]) if object_width_mm<pts[0][1] else (pts[-2],pts[-1])
    return round(t0+(t1-t0)*(object_width_mm-w0)/(w1-w0))
