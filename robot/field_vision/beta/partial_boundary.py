"""Visible fixed-side edge and conservative association evidence for clipped views."""
import cv2
import numpy as np


def clipped_sides(box,w,h):
    p=np.asarray(box)
    return [name for name,test in [('left',p[:,0].min()<=1),('right',p[:,0].max()>=w-2),('top',p[:,1].min()<=1),('bottom',p[:,1].max()>=h-2)] if test] if len(p) else []


def trim_finger_merge(body,reference):
    """Cut a bottom-entering finger silhouette that merged into the object.

    Fit the fixed-side (left) edge above the fixed finger, then drop pixels left
    of that line in the finger rows. Keeps a genuine overlap only where the object
    itself continues the same edge line."""
    h,w=body.shape;finger=reference.get('fixed_finger')
    if not finger or finger.get('frame_size')!=[w,h]:return body
    top=max(40,int(np.asarray(finger['contour'])[:,1].min())-5)
    pts=[[float(np.flatnonzero(body[y])[0]),float(y)] for y in range(top) if body[y].any()]
    if len(pts)<40:return body
    pts=np.asarray(pts,np.float32)
    vx,vy,x0,y0=cv2.fitLine(pts,cv2.DIST_HUBER,0,.01,.01).ravel()
    if abs(vy)<.7:return body   # not a near-vertical edge; leave untouched
    trimmed=body.copy()
    for y in range(top,h):
        limit=int(round(x0+vx/vy*(y-y0)))-6
        if limit>0:trimmed[y,:min(w,limit)]=0
    return trimmed


def edge_evidence(rgb,body,reference,located):
    h,w=body.shape;rows=[]
    # Jaws enter from the bottom. A white moving finger can merge with a pale
    # object there (flow-6bcfafe6: edge x 290 -> 242 below row 360), so fit the
    # fixed-side edge only above the registered fixed finger.
    finger=reference.get('fixed_finger')
    top=h
    if finger and finger.get('frame_size')==[w,h]:top=max(40,int(np.asarray(finger['contour'])[:,1].min())-5)
    for y in range(top):
        xs=np.flatnonzero(body[y])
        if len(xs) and 8<xs[0]<w-8:rows.append([float(xs[0]),float(y)])
    if len(rows)<40:raise ValueError('고정 손가락 쪽 긴 경계가 충분히 보이지 않습니다.')
    points=np.asarray(rows,np.float32)
    vx,vy,x,y=cv2.fitLine(points,cv2.DIST_HUBER,0,.01,.01).ravel()
    angle=float(np.degrees(np.arctan2(vy,vx))%180);error=abs((angle-90+90)%180-90)
    slope=float(vx/vy) if abs(vy)>1e-6 else 999
    residual=np.abs(points[:,0]-(x+slope*(points[:,1]-y)))
    # This runs BEFORE the wrist rotation step (which corrects up to 45 deg), so a
    # 15 deg gate rejected fixable views (flow-2a93027c: phone, arrival yaw error
    # 10.6 deg + close-range perspective -> edge ~16 deg). Straightness still required.
    straight=bool(np.percentile(residual,75)<=12)
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB).astype(float)
    pixels=lab[body>0][::max(1,int(np.count_nonzero(body)/1500))]
    colors=np.asarray(reference.get('foreground',[]),float)
    color_fraction=float((np.min(np.linalg.norm(pixels[:,None]-colors[None],axis=2),axis=1)<65).mean()) if len(colors) and len(pixels) else 0.
    seed=np.zeros_like(body);cv2.fillConvexPoly(seed,np.rint(located['box_pixels']).astype(np.int32),1)
    connection=float(np.count_nonzero((seed>0)&(body>0))/max(1,np.count_nonzero(body)))
    neighbors=reference.get('neighbor_clearance',{})
    # v0.2.41 (audit B6/A22): evidence is RETURNED, never raised. Rotation and descent
    # need different evidence: the wrist can fix any straight, connected edge (rotation
    # is clipped to +-45 deg), but the gap may only be read on an edge within 15 deg of
    # the finger (the same limit gap_observation uses for tracking). Colour match and
    # the top-view neighbour strips are recorded only; the neighbour check itself stays
    # in grasp_flow (topview_clearance / side_free_mm fixed-side choice).
    connected=bool(connection>=.25)
    proof={'straight_edge':straight,'expected_region_connection':connected,'edge_within_15deg':bool(error<=15),
           'loose_lab_match':color_fraction>=.15,'topview_both_sides_clear':neighbors.get('clear') is True}
    # The edge is fitted above the fixed finger only, but the gap is read at the
    # finger-tip rows below it (flow-7528dd18: fit to y~338, gap rows 343~404 ->
    # no samples). The object edge is straight, so extend the fitted line over the
    # full frame height; fit quality is reported in usable_for_rotation/usable_for_gap.
    line={'points':[[float(x+slope*(0-y)),0.],[float(x+slope*(h-1-y)),float(h-1)]],'fitted_rows':[float(points[:,1].min()),float(points[:,1].max())],
          'angle_deg':angle,'expected_deg':90,'error_deg':error,'color_fraction':color_fraction,'connection_fraction':connection,
          'association':proof,'side':'fixed','clipped_sides':clipped_sides(located['box_pixels'],w,h),
          'usable_for_rotation':straight and connected,'usable_for_gap':straight and connected and error<=15}
    return line


def side_free_mm(image,box,short_vector_pixels,width_mm,max_mm=40.,threshold=.18):
    """Free green-background distance beyond each long edge, along the short axis.

    Measured on top-view pixels (not detections), so an undetected neighbor still
    counts. 'positive' is the +short_vector_pixels side. Used to put the fixed
    finger on the freer side."""
    rgb=np.asarray(image.convert('RGB'));h,w=rgb.shape[:2];p=np.asarray(box,float)
    v=np.asarray(short_vector_pixels,float);length=np.linalg.norm(v)
    if length<2:raise ValueError('탑뷰 짧은축 폭 부족')
    unit=v/length;center=p.mean(0);projection=(p-center)@unit;low,high=projection.min(),projection.max()
    long=np.array([-unit[1],unit[0]]);extent=np.max(np.abs((p-center)@long))
    yy,xx=np.mgrid[:h,:w];points=np.stack([xx-center[0],yy-center[1]],axis=-1)
    u=points@unit;t=points@long;ppm=length/max(width_mm,1)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV);green=(hsv[:,:,0]>=35)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=12)
    target=np.zeros((h,w),np.uint8);cv2.fillConvexPoly(target,np.rint(p).astype(np.int32),1)
    band=(np.abs(t)<=extent*.7)&(target==0)
    result={}
    for side,sign,edge in [('negative',-1,low),('positive',1,high)]:
        free=float(max_mm)
        for d in np.arange(0,max_mm,1.):
            a=edge+sign*(2+d*ppm);b=edge+sign*(2+(d+1)*ppm)
            mask=band&(u>=min(a,b))&(u<max(a,b))
            count=int(mask.sum())
            if count==0 or float((~green[mask]).mean())>threshold:free=float(d);break
        result[side+'_mm']=free
    result.update(max_mm=float(max_mm),threshold=threshold,method='green_background_scan')
    return result


def topview_clearance(image,box,short_vector_pixels,width_mm,margin_mm=3):
    rgb=np.asarray(image.convert('RGB'));h,w=rgb.shape[:2];p=np.asarray(box,float)
    v=np.asarray(short_vector_pixels,float);length=np.linalg.norm(v)
    if length<2:raise ValueError('탑뷰 짧은축 폭 부족')
    unit=v/length;center=p.mean(0);projection=(p-center)@unit;low,high=projection.min(),projection.max()
    long=np.array([-unit[1],unit[0]]);extent=np.max(np.abs((p-center)@long))
    # Strips sit beyond the selected object; inspect pixels, not detections.
    yy,xx=np.mgrid[:h,:w];points=np.stack([xx-center[0],yy-center[1]],axis=-1)
    u=points@unit;t=points@long;px_per_mm=length/max(width_mm,1);strip=max(5,margin_mm*px_per_mm)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV);green=(hsv[:,:,0]>=35)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=12)
    target=np.zeros((h,w),np.uint8);cv2.fillConvexPoly(target,np.rint(p).astype(np.int32),1)
    result=[]
    for side,mask in [('negative',(u<low-2)&(u>=low-2-strip)),('positive',(u>high+2)&(u<=high+2+strip))]:
        mask &= (np.abs(t)<=extent*.7)&(target==0)
        count=int(mask.sum());ratio=float((~green[mask]).mean()) if count else 1
        result.append({'side':side,'non_background_fraction':ratio,'pixels':count,'clear':count>=20 and ratio<=.18})
    return {'clear':all(r['clear'] for r in result),'strips':result,'method':'direct_green_background_strips','threshold':.18}


NEAR_RUN_PX=8          # this many non-foam pixels in a row = the object starts
NEAR_MIN_ROWS=40


def nearest_edge(rgb,reference):
    """v0.2.78: the object edge NEAREST to the fixed finger, found by scanning outward.

    User 11-12: "경계면에서 제일 중요한 조건이 집게에서 가장 가까이에서 먼저 잡혀야".
    The region-first outline (colour patch -> body -> left side) put the edge on a logo
    patch (flow-0d4bc00a descent: -4.9px, wrong side move) or let the open moving finger
    bend it (flow-4e8b8c8d: +20 / -24 deg). Here each image row ABOVE the fixed finger tip
    (the finger hides nothing there) is scanned from the finger's inner line outward;
    the first run of non-foam pixels is the edge. If the object already covers the
    finger line, scan back toward the finger side to the first foam -> negative gap.
    A robust straight line through those points is extended down to the tip rows.
    Returns a visible_boundary dict (same keys as edge_evidence) or raises ValueError.
    """
    h,w=rgb.shape[:2];finger=reference.get('fixed_finger')
    if not finger or finger.get('frame_size')!=[w,h]:raise ValueError('고정 손가락 등록이 없어 가까운 경계를 찾을 수 없습니다.')
    contour=np.asarray(finger['contour'],np.float32)
    if float(contour[:,0].mean())>=w/2:
        # finger on the right: mirror, measure as if on the left, mirror the line back
        flipped=dict(reference,fixed_finger=dict(finger,contour=np.column_stack([w-1-contour[:,0],contour[:,1]]).tolist()))
        out=nearest_edge(np.ascontiguousarray(rgb[:,::-1]),flipped)
        out['points']=[[w-1-px,py] for px,py in out['points']];out['angle_deg']=(180-out['angle_deg'])%180
        return out
    tip_top=int(contour[:,1].min());x0=int(contour[:,0].max())
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    # Foam = green hue. Saturation >=10 (not 25): under strong light the foam beside the
    # phone bleached to S 13~25 and read as 'object' (flow-0d4bc00a). Very dark = object.
    foam=(hsv[:,:,0]>=35)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=10)&(hsv[:,:,2]>=60)
    obj=cv2.morphologyEx((~foam).astype(np.uint8),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))>0
    from .grasp_alignment import visible_fingers
    from PIL import Image
    moving=np.zeros((h,w),bool)
    for c,_ in visible_fingers(Image.fromarray(np.ascontiguousarray(rgb))):
        m=np.zeros((h,w),np.uint8);cv2.drawContours(m,[c],-1,1,-1);moving|=m>0
    rows=[];overlap=0
    for y in range(max(3,tip_top-230),max(4,tip_top-20)):
        line=obj[y]&~moving[y]
        if moving[y,x0:].any() and not line[x0:].any():continue
        if line[x0+1:x0+7].sum()>=4:
            # the object already covers the finger line: walk back to the first foam
            edge=next((x for x in range(x0,max(4,x0-120),-1) if not line[x-4:x+1].any()),None)
            if edge is not None:rows.append([float(edge+1),float(y)]);overlap+=1
            continue
        edge=next((x for x in range(x0+1,w-NEAR_RUN_PX) if line[x:x+NEAR_RUN_PX].all()),None)
        if edge is not None:rows.append([float(edge),float(y)])
    if len(rows)<NEAR_MIN_ROWS:raise ValueError('고정 손가락 가까운 쪽 경계 행 부족 (%d행)'%len(rows))
    pts=np.asarray(rows,np.float32)
    def fit(p):
        vx,vy,x,y=cv2.fitLine(p,cv2.DIST_HUBER,0,.01,.01).ravel()
        slope=float(vx/vy) if abs(vy)>1e-6 else 999.
        return slope,float(x),float(y)
    slope,x,y=fit(pts)
    res=np.abs(pts[:,0]-(x+slope*(pts[:,1]-y)))
    inl=pts[res<6]
    if len(inl)>=NEAR_MIN_ROWS:
        slope,x,y=fit(inl);res=np.abs(inl[:,0]-(x+slope*(inl[:,1]-y)));pts=inl
    angle=float(np.degrees(np.arctan2(1.,slope))%180);error=abs((angle-90+90)%180-90)
    straight=bool(np.percentile(res,75)<=4)
    return {'points':[[float(x+slope*(0-y)),0.],[float(x+slope*(h-1-y)),float(h-1)]],
            'fitted_rows':[float(pts[:,1].min()),float(pts[:,1].max())],'rows':int(len(pts)),'overlap_rows':int(overlap),
            'angle_deg':angle,'expected_deg':90,'error_deg':error,'side':'fixed','source':'nearest_to_finger',
            'residual_p75':float(np.percentile(res,75)),
            'usable_for_rotation':straight,'usable_for_gap':straight and error<=15}
