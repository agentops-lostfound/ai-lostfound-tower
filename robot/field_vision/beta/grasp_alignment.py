"""ARM image alignment gate. Missing jaw evidence blocks descent."""
import json
import math
from pathlib import Path
import cv2
import numpy as np
from .grasp_geometry import pink_tube


def measure(image,color='pink'):
    shape=pink_tube(image,partial=True,camera='ARM 방향 확인',color=color)
    rgb=np.asarray(image.convert('RGB'));h,w=rgb.shape[:2]
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB);hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    mask=((lab[:,:,0]>115)&(np.abs(lab[:,:,1].astype(float)-128)<10)&(hsv[:,:,1]<60)).astype('uint8')*255
    mask[:int(h*.55)]=0
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for c in contours:
        area=cv2.contourArea(c);x,y,bw,bh=cv2.boundingRect(c)
        if area<max(300,w*h*.003) or bh<h*.08:continue
        m=cv2.moments(c)
        if m['m00']:candidates.append([m['m10']/m['m00'],m['m01']/m['m00'],area,[x,y,bw,bh]])
    left=[c for c in candidates if c[0]<w*.4];right=[c for c in candidates if c[0]>w*.6]
    if left and right:
        l=max(left,key=lambda c:c[2]);r=max(right,key=lambda c:c[2])
        method='separated_jaws'
    else:
        # Closed jaws are NOT required to occupy opposite screen thirds.
        # Crop below the tube/label bridge and require a stable pair in two bands.
        pairs=[]
        for top in [.85,.9]:
            lower=mask.copy();lower[:int(h*top)]=0
            cs,_=cv2.findContours(lower,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            blobs=[]
            for contour in cs:
                area=cv2.contourArea(contour)
                if area<w*h*.01:continue
                moment=cv2.moments(contour)
                blobs.append([moment['m10']/moment['m00'],moment['m01']/moment['m00'],area,list(cv2.boundingRect(contour))])
            if len(blobs)<2:raise ValueError('닫힌 집게 하단의 양쪽 경계 미검출 · 회전/하강 중단')
            pair=sorted(sorted(blobs,key=lambda c:c[2],reverse=True)[:2],key=lambda c:c[0])
            if pair[1][0]-pair[0][0]<w*.12 or abs(pair[1][1]-pair[0][1])>h*.12:
                raise ValueError('닫힌 집게 쌍의 간격/높이 불명확 · 회전/하강 중단')
            pairs.append(pair)
        angles=[math.degrees(math.atan2(r[1]-l[1],r[0]-l[0])) for l,r in pairs]
        if abs(angles[0]-angles[1])>12:raise ValueError('집게 방향이 영상 구간별로 불일치 · 회전/하강 중단')
        l,r=pairs[0];method='closed_jaws_two_lower_bands'
    if abs(l[1]-r[1])>h*.18:raise ValueError('ARM 집게 쌍이 불명확합니다. 회전·하강 중단')
    opening=math.degrees(math.atan2(r[1]-l[1],r[0]-l[0]))
    error=(shape['long_axis_deg']-opening-90+90)%180-90
    return {'object_axis_deg':shape['long_axis_deg'],'opening_axis_deg':opening,
        'error_deg':error,'aligned':abs(error)<=12,'jaw_centers':[l[:2],r[:2]],'jaw_boxes':[l[3],r[3]],'object_box':shape.get('box_pixels'),'method':method,
        'note':'흰 집게 색상 후보 기반 · 실제 접촉/3D 높이 확인 아님'}


def descent_clearance(result,image_size):
    """Conservative image-plane veto, never a proof of collision-free descent."""
    w,h=image_size
    if result.get('method')!='separated_jaws' or not result.get('object_box'):
        return {'clear':False,'reason':'양쪽 집게 끝의 전체 외곽이 확인되지 않음 · 하강 금지'}
    body=cv2.convexHull(np.asarray(result['object_box'],np.float32))
    overlaps=[]
    for index,(x,y,bw,bh) in enumerate(result['jaw_boxes']):
        # An outer edge may leave the frame. The edge facing the object must be visible.
        if (index==0 and x+bw>=w-1) or (index==1 and x<=1):
            return {'clear':False,'reason':'물품 쪽 집게 경계가 보이지 않음 · 하강 금지'}
        jaw=np.array([[x,y],[x+bw,y],[x+bw,y+bh],[x,y+bh]],np.float32)
        area,_=cv2.intersectConvexConvex(body,jaw)
        overlaps.append(float(area))
    if any(a>4 for a in overlaps):
        return {'clear':False,'reason':'집게 후보 영역과 물품 외형이 겹침 · 하강 금지','overlap_pixels':overlaps}
    axis=np.asarray(result['jaw_centers'][1])-result['jaw_centers'][0]
    axis=axis/np.linalg.norm(axis)
    center=np.asarray(result['object_box']).mean(axis=0)
    endpoints=[float(np.dot(np.asarray(c)-center,axis)) for c in result['jaw_centers']]
    if endpoints[0]>=0 or endpoints[1]<=0:
        return {'clear':False,'reason':'물품 중심이 양쪽 집게 사이에 있지 않음 · 하강 금지'}
    return {'clear':True,'reason':'영상상 겹침/중심 검사 통과 · 실제 높이 미검증','overlap_pixels':overlaps}


def camera_profile(camera):
    profile={key:camera.get(key) for key in ('source','device_path','width','height','input_size','frame_size')}
    for key in ('input_size','frame_size'):
        if profile[key] is not None:
            profile[key]=list(profile[key])
    return profile


def load_fixed_finger(path, camera):
    if not Path(path).exists():
        raise ValueError('ARM 고정 손가락 윤곽 등록이 필요합니다.')
    registration=json.loads(Path(path).read_text(encoding='utf-8'))
    if registration.get('method')!='white_finger_green_background':
        raise ValueError('흰색 손가락 기준으로 고정 윤곽을 다시 등록하세요.')
    if registration['camera']!=camera_profile(camera):
        raise ValueError('ARM 카메라 설정이 달라졌습니다. 고정 손가락 윤곽을 다시 등록하세요.')
    return registration


def visible_fingers(image, *, registration=False):
    rgb=np.asarray(image.convert('RGB'))
    h,w=rgb.shape[:2]
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)
    if registration:
        # On the green board, include neutral white and grey plastic.
        # Limit the search to the fixed finger's side of the frame.
        mask=((lab[:,:,0]>110)&(lab[:,:,1]>=122)&(lab[:,:,1]<=147)&
              (lab[:,:,2]>=116)&(lab[:,:,2]<=144)).astype('uint8')*255
        mask[:,int(w*.41):]=0
    else:
        mask=((lab[:,:,0]>120)&(lab[:,:,1]>130)&(lab[:,:,1]<146)&
              (lab[:,:,2]>123)&(lab[:,:,2]<138)).astype('uint8')*255
    mask[:int(h*.55)]=0
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    # The fixed finger enters the lower-left side of this wrist camera.
    # The moving finger normally leaves the right edge at half aperture.
    fingers=[]
    for contour in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
        x,y,width,height=cv2.boundingRect(contour)
        if y+height<h-4 or height<h*.08 or cv2.contourArea(contour)<h*w*.005:
            continue
        if x<w*.15 or x+width>w*.90:
            fingers.append((contour,(x,y,width,height)))
    return fingers


def open_jaw_clearance(image, color, *, diagnostics=False, fixed_finger=None):
    """Evaluate visible finger silhouettes from the lower edge of the wrist image."""
    shape=pink_tube(image,partial=True,camera='개방 간격 확인',color=color)
    w,h=image.size
    hull=cv2.convexHull(np.asarray(shape['box_pixels'],np.float32))
    xmin,ymin,bw,bh=cv2.boundingRect(hull)
    fingers=visible_fingers(image)
    if fixed_finger is not None:
        if fixed_finger['frame_size']!=[w,h]:
            raise ValueError('ARM 영상 크기가 등록된 고정 손가락 윤곽과 다릅니다.')
        contour=np.asarray(fixed_finger['contour'],np.int32).reshape(-1,1,2)
        # Reject current-frame left candidates, including a finger joined
        # to a similarly colored label. Keep right-side checks when visible.
        fingers=[(contour,cv2.boundingRect(contour))]+[
            (candidate,box) for candidate,box in fingers if box[0]>=w*.15]
    left=[entry for entry in fingers if entry[1][0]<w*.15]
    if len(left)!=1:
        return {'clear':False,'reason':'고정 손가락 경계 미확인', **({'outline': hull.reshape(-1,2).tolist(), 'candidates':[c.reshape(-1,2).tolist() for c,_ in fingers]} if diagnostics else {})}
    # Use the finger silhouette, retaining the conservative object envelope.
    body=np.zeros((h,w),np.uint8)
    cv2.fillConvexPoly(body,np.rint(hull).astype(np.int32),255)
    distance=cv2.distanceTransform(255-body,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
    required=4*w/640
    details=[]
    for contour,box in fingers:
        visible=np.zeros_like(body)
        cv2.drawContours(visible,[contour],-1,255,-1)
        gap=float(distance[visible!=0].min())
        x,y,width,height=box
        fixed=x<w*.15
        on_side=(x+width/2<xmin+bw/2) if fixed else (x+width/2>xmin+bw/2)
        detail={'finger':'fixed' if fixed else 'moving','gap_px':round(gap,2),'side_ok':bool(on_side)}
        if diagnostics:
            finger_points=np.argwhere(visible)
            nearest=finger_points[np.argmin(distance[visible!=0])]
            body_points=np.argwhere(body)
            other=body_points[np.argmin(np.sum((body_points-nearest)**2,axis=1))]
            detail.update(contour=contour.reshape(-1,2).tolist(),
                          nearest_points=[nearest[::-1].tolist(),other[::-1].tolist()],
                          overlap_px=int(np.count_nonzero(visible & body)))
        details.append(detail)
    clear=all(d['side_ok'] and d['gap_px']>=required for d in details)
    smallest=min(d['gap_px'] for d in details)
    return {'clear':clear,'fingers':details,'required_px':required,
            'fixed_finger_source':'registered' if fixed_finger is not None else 'color',
            **({'outline': hull.reshape(-1,2).tolist()} if diagnostics else {}),
            'reason':f'가시 손가락 최소 간격 {smallest:.1f}px / 기준 {required:.1f}px · '+('통과' if clear else '하강 중단')}



def draw_clearance(image, result):
    from PIL import Image
    rgb=np.asarray(image.convert('RGB')).copy()
    outline=result.get('outline')
    body=np.zeros(rgb.shape[:2],np.uint8)
    if outline:
        polygon=np.rint(outline).astype(np.int32)
        cv2.fillConvexPoly(body,polygon,255)
        cv2.polylines(rgb,[polygon],True,(255,190,30),2)
    for contour in result.get('candidates',[]):
        cv2.polylines(rgb,[np.asarray(contour,np.int32)],True,(40,210,255),2)
    for finger in result.get('fingers',[]):
        if 'contour' not in finger:
            continue
        contour=np.asarray(finger['contour'],np.int32)
        mask=np.zeros_like(body)
        cv2.drawContours(mask,[contour],-1,255,-1)
        overlap=(mask & body)!=0
        rgb[overlap]=(rgb[overlap]*.35+np.array([255,45,50])*.65).astype(np.uint8)
        cv2.polylines(rgb,[contour],True,(40,210,255),2)
        a,b=map(tuple,finger['nearest_points'])
        cv2.line(rgb,a,b,(255,255,255),2)
        cv2.circle(rgb,a,6,(255,255,255),2)
    label='YELLOW: tube box   CYAN: finger   RED: overlap'
    cv2.rectangle(rgb,(0,0),(rgb.shape[1],48),(20,20,20),-1)
    cv2.putText(rgb,label,(8,18),cv2.FONT_HERSHEY_SIMPLEX,.47,(255,255,255),1,cv2.LINE_AA)
    gaps=' / '.join(f"{f['finger']}: {f['gap_px']:.1f}px ({f.get('overlap_px',0)} overlap px)" for f in result.get('fingers',[]))
    cv2.putText(rgb,gaps or 'No confirmed finger pair',(8,39),cv2.FONT_HERSHEY_SIMPLEX,.47,(255,255,255),1,cv2.LINE_AA)
    return Image.fromarray(rgb)

def measure_visible_side(image, fixed_finger, outline):
    """Estimate same-row clearance against the green tray for review."""
    if not outline:
        return {'sample_rows':0}
    rgb=np.asarray(image.convert('RGB'))
    h,w=rgb.shape[:2]
    lab_a=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)[:,:,1]
    finger=np.zeros((h,w),np.uint8)
    cv2.fillPoly(finger,[np.asarray(fixed_finger['contour'],np.int32)],1)
    tube=np.zeros_like(finger)
    cv2.fillConvexPoly(tube,np.rint(outline).astype(np.int32),1)
    gaps=[]
    for y in range(max(0,int(np.nonzero(finger)[0].min())),h):
        fingers=np.flatnonzero(finger[y])
        box=np.flatnonzero(tube[y])
        if not len(fingers) or not len(box):
            continue
        row=lab_a[y]
        edge=int(fingers[-1])
        start=max(edge+1,int(box[0])-16,14)
        end=min(int(box[0])+25,w-12)
        for x in range(start,end):
            if np.count_nonzero(row[x-14:x-2]<124)>=8 and np.count_nonzero(row[x:x+12]>=126)>=10:
                gaps.append(x-edge)
                break
    result={'sample_rows':len(gaps)}
    if len(gaps)>=10:
        result.update(median_px=float(np.median(gaps)),minimum_px=int(min(gaps)))
    return result
