"""Bounded image-gap correction; no per-item offsets. Pixel-per-mm is measured, not assumed."""
import cv2
import numpy as np
from .grasp_geometry import pink_tube


def fixed_gap(image,color,fixed_finger,settings=None,*,shape=None):
    shape=shape or pink_tube(image,partial=True,camera='고정 손가락 간격',color=color)
    w,h=image.size
    if fixed_finger['frame_size']!=[w,h]:raise ValueError('고정 손가락 등록 해상도가 다릅니다.')
    body=np.zeros((h,w),np.uint8);finger=body.copy()
    # The visible contour has the occluding finger cut out. Use the completed
    # object envelope, never that contour, to test overlap.
    cv2.fillPoly(body,[np.rint(shape['box_pixels']).astype(np.int32)],1)
    cv2.fillPoly(finger,[np.asarray(fixed_finger['contour'],np.int32)],1)
    gaps=[]
    ys=np.flatnonzero(finger.any(axis=1))
    if not len(ys):raise ValueError('고정 손가락 윤곽이 비어 있습니다.')
    # Registered finger enters from the bottom; its distal tip is the top end.
    from .grasp_reference import contact_reference
    contact=contact_reference(fixed_finger)
    end=contact['image_rows'][1]
    for y in range(int(ys[0]),end):
        a=np.flatnonzero(finger[y]);b=np.flatnonzero(body[y])
        boundary=shape.get('visible_boundary')
        if boundary and not boundary.get('usable_for_gap',True):
            # v0.2.41 (audit B6): a weak edge may skip rotation but never decide descent.
            raise ValueError('간격 근거 부족 · 고정 손가락 쪽 경계선이 직선/연결/15° 조건을 만족하지 않습니다 (오차 %.1f°).'%boundary.get('error_deg',float('nan')))
        if boundary:
            p,q=np.asarray(boundary['points'],float)
            if y<min(p[1],q[1]) or y>max(p[1],q[1]) or abs(q[1]-p[1])<1:continue
            left=p[0]+(q[0]-p[0])*(y-p[1])/(q[1]-p[1])
            if len(a):gaps.append(float(left-a[-1]))
        elif len(a) and len(b):gaps.append(float(b[0]-a[-1]))
    extrapolated=None
    if len(gaps)<max(8,int(h*.02)) and not shape.get('visible_boundary'):
        # v0.2.52 (flow-41de0344, USB 13x45mm): at approach height a short object can sit
        # entirely above the finger-tip rows in the image, so no row holds both. Extend
        # the object's long edge on the fixed-finger side down into the tip rows, only
        # when the object ends within 120px of them.
        box=np.asarray(shape['box_pixels'],float);edges4=[(box[i],box[(i+1)%4]) for i in range(4)]
        longs=sorted(edges4,key=lambda e:-np.linalg.norm(e[1]-e[0]))[:2]
        inner=float(finger.nonzero()[1].max())
        p,q=min(longs,key=lambda e:abs((e[0][0]+e[1][0])/2-inner))
        # v0.2.70 (flow-ce91cb8f): the USB's end overlapped the tip rows by 1px (bottom 358,
        # tip top 357) -> 1-2 shared rows, too few, and the old 0<= test refused to extend.
        # A small overlap (<=40px) is extended the same way.
        if abs(q[1]-p[1])>=1 and -40<=ys[0]-box[:,1].max()<=120:
            gaps=[]
            for y in range(int(ys[0]),end):
                a=np.flatnonzero(finger[y])
                if len(a):gaps.append(float(p[0]+(q[0]-p[0])*(y-p[1])/(q[1]-p[1])-a[-1]))
            extrapolated={'edge':[p.tolist(),q.tolist()],'object_bottom_row':float(box[:,1].max()),'tip_top_row':int(ys[0])}
    if len(gaps)<max(8,int(h*.02)):raise ValueError('고정 손가락과 물품 경계를 같은 높이의 영상에서 확인할 수 없습니다.')
    settings=settings or {};scale=w/640;low=settings.get('gap_low_px',6)*scale;high=min(settings.get('gap_high_px',56)*scale,max((low+5*scale),shape['width_pixels']*.6,20*scale))
    gap=float(np.percentile(gaps,20))
    return {'gap_px':gap,'low_px':low,'high_px':high,'in_band':bool(low<=gap<=high),
            'sample_rows':len(gaps),'minimum_row_gap_px':min(gaps),'median_gap_px':float(np.median(gaps)),
            'percentile':20,'visible_boundary':shape.get('visible_boundary'),'contact_reference':contact,'tip_rows':[int(ys[0]),end],'object_box':shape['box_pixels'],
            'extrapolated_edge':extrapolated,
            'note':'영상의 같은 행에서 고정 손가락 안쪽과 물품 경계 간격'+(' (물품 긴 변을 손가락 끝 행까지 연장)' if extrapolated else '')+'. 깊이/접촉 성공 판정 아님'}


def gap_aim(result):
    """Target inside the band with margin, not the band edge (edge = re-overlap risk)."""
    low,high=result['low_px'],result['high_px'];margin=.25*(high-low)
    return low+margin if result['gap_px']<low else high-margin


def correct_gap(measure,move,log,settings=None,learned_slope=None,max_moves=6,*,session=None,on_progress=None):
    """Move the fixed finger into the image gap band by a measured amount.

    The step size comes from the measured overlap and the image response (px per mm
    along the tool opening axis), not a fixed 4mm. A slope learned on an earlier run
    allows a direct first step; otherwise one probe of `probe_mm` measures it.
    Total travel from the start is bounded by `correction_mm`, so a probe that went
    the wrong way can still be undone and continued. Callbacks own motion safety.
    """
    settings=settings or {};limit=float(settings.get('correction_mm',12.))
    current=measure();log('간격 확인',current)
    if current['in_band']:return {'status':'within_band','moves':(session or {}).get('moves',0),'final':current,'slope_px_per_mm':learned_slope,'travel_mm':(session or {}).get('command_mm',0.)}
    slope=learned_slope if learned_slope is not None and np.isfinite(learned_slope) and abs(learned_slope)>=.5 else None
    session=session if session is not None else {}
    position=float(session.get('command_mm',0));moves=int(session.get('moves',0))
    # Reference direction: the learned sign, else the first effective measurement.
    sign=None if slope is None else np.sign(slope)
    short_moves=0;reversals=0
    while moves<max_moves:
        if slope is None:
            step=float(settings.get('probe_mm',4.));label='영상 반응 확인 이동'
        else:
            step=(gap_aim(current)-current['gap_px'])/slope;label='측정 간격 기반 위치 조정'
        clipped=float(np.clip(position+step,-limit,limit))-position
        if abs(clipped)<.5:
            raise ValueError('고정 손가락 간격 보정 한도 %.0fmm 안에서 허용 간격에 도달할 수 없습니다. 하강하지 않습니다.'%limit)
        actual=move(clipped);moves+=1
        # Envelope is in command space. Feedback is only for px/mm estimation.
        position+=clipped;session.update(command_mm=position,moves=moves)
        after=measure()
        if not np.isfinite(actual) or abs(actual)<1.5:
            # v0.2.41 (audit B3): under 1.5mm of real travel (servo dead zone / sag) the
            # px/mm ratio is noise: skip slope and sign judgement and continue from the
            # re-measured gap. v0.2.43 (flow-23834736, phone): the 2nd short move had
            # already reached the band (27.6px in 18.6..28.6) but the short-move stop ran
            # first. Band is checked first, and short moves never stop by themselves;
            # max_moves and the travel limit still bound the loop.
            short_moves+=1
            log('실제 이동량 부족 · 기울기 판정 생략',dict(after,command_step_mm=clipped,step_mm=actual,travel_mm=position,short_move=True))
            current=after
            if after['in_band']:return {'status':'within_band','moves':moves,'final':after,'slope_px_per_mm':slope,'travel_mm':position,'short_moves':short_moves}
            continue
        measured=(after['gap_px']-current['gap_px'])/actual
        log(label,dict(after,command_step_mm=clipped,step_mm=actual,travel_mm=position,slope_px_per_mm=measured))
        if not np.isfinite(measured) or abs(measured)<.5:
            raise ValueError('좌우 이동에 대한 영상 간격 변화가 불명확합니다. 하강하지 않습니다.')
        if sign is not None and np.sign(measured)!=sign:
            # v0.2.41 (audit B4): one reversed effective move is adopted and re-checked;
            # stop only when a second effective move confirms the reversal.
            reversals+=1;session['reversed']=float(measured)
            if reversals>=2:
                raise ValueError('영상 간격 반응 방향이 이전 측정과 반대입니다(유효 이동 2회 확인). 외형 검출을 확인해야 합니다. 하강하지 않습니다.')
            slope=measured;current=after
            if after['in_band']:return {'status':'within_band','moves':moves,'final':after,'slope_px_per_mm':slope,'travel_mm':position,'unconfirmed_reversal':True}
            continue
        if sign is None:sign=np.sign(measured)
        slope=measured;current=after
        session.setdefault('slopes',[]).append(measured)
        session['slope_px_per_mm']=measured
        if on_progress:on_progress(session)
        if after['in_band']:
            return {'status':'within_band','moves':moves,'final':after,'slope_px_per_mm':slope,'travel_mm':position}
    raise ValueError('위치 조정 %d회 후에도 고정 손가락 간격이 허용 범위 밖입니다. 하강하지 않습니다.'%max_moves)


def object_alignment(shape):
    # Camera mounting is fixed relative to the fixed finger. Unlike the pair
    # of jaw centroids, this reference does not tilt when one finger opens.
    error=float((shape['long_axis_deg']-90+90)%180-90)
    reliable=shape.get('axis_reliable',True)
    boundary=shape.get('visible_boundary') or {}
    # A CLIPPED box's axis is not the object's axis even when flagged reliable
    # (flow-8aef9ccd power bank: box 405x239px -> axis 0 deg, error -90, wrist
    # rotated 45 deg although the bank was parallel to the jaws).
    clipped=bool(shape.get('clipped') or shape.get('full_extent_clipped'))
    if clipped:reliable=False
    # v0.2.41 (audit B6/A22): rotate on any straight, connected edge; a clipped shape
    # with no usable edge falls through to 'no rotation' below (descent is gated
    # separately by fixed_gap's usable_for_gap check).
    # v0.2.78: the edge nearest to the fixed finger (wide items) always wins over the box axis.
    nearest=boundary.get('source')=='nearest_to_finger'
    if (not reliable or nearest) and boundary.get('angle_deg') is not None and boundary.get('usable_for_rotation'):
        # A wide object fills the frame (phone): the clipped box axis is unreliable,
        # but the fitted fixed-side edge is. Align that edge with the fixed finger
        # (flow-37fb91e8: box 87.6 deg 'aligned', edge 72.8 deg -> jaw landed on phone).
        edge_error=float((boundary['angle_deg']-90+90)%180-90)
        return {'aligned':abs(edge_error)<=8,'error_deg':edge_error,'object_axis_deg':float(boundary['angle_deg']),
                'axis_reliable':True,'axis_source':'fixed_side_edge','box_axis_deg':shape['long_axis_deg'],
                'method':'fixed_side_edge_with_fixed_camera','tolerance_deg':8,
                'note':'잘린 큰 물체: 고정 손가락 쪽 경계선 기울기로 손목 방향 판단'}
    return {'aligned':not reliable or abs(error)<=12,'error_deg':error if reliable else 0,'object_axis_deg':shape['long_axis_deg'],
            'axis_reliable':reliable,
            'method':'object_axis_with_fixed_camera_and_encoder_check','tolerance_deg':12,
            'note':'고정 카메라의 물품 축과 관절 방향 검사 사용. 회전 손가락 중심 연결선은 사용하지 않음'}


def anchor_plan(plan,anchor):
    anchor=np.asarray(anchor,float)
    if anchor.shape!=(3,) or not np.isfinite(anchor).all():raise ValueError('유효한 영상 보정 후 위치가 필요합니다.')
    plan['approach_xyz_mm']=anchor.tolist()
    plan['verification_lift_xyz_mm']=anchor.tolist()
    plan['grasp_xyz_mm']=[float(anchor[0]),float(anchor[1]),plan['grasp_xyz_mm'][2]]
