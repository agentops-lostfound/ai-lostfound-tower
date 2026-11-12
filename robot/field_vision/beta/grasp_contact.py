"""분홍 튜브와 흰 집게의 접촉 후보. 힘/깊이/성공을 영상 한 장으로 확정하지 않는다."""
import cv2
import numpy as np


def contact_candidate(image):
    rgb=np.asarray(image.convert('RGB'));h,w=rgb.shape[:2]
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB);hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    pink=((lab[:,:,1]>=137)&(lab[:,:,0]>85)&(hsv[:,:,1]<210)).astype(np.uint8)*255
    pink=cv2.morphologyEx(pink,cv2.MORPH_CLOSE,np.ones((13,13),np.uint8))
    pink[int(h*.93):]=0
    contours,_=cv2.findContours(pink,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour);area=cv2.contourArea(contour)
        if area<1500 or bh<80 or bh/max(1,bw)<1.2:continue
        if abs((x+bw/2)-w/2)>w*.38:continue
        candidates.append((area,contour))
    if not candidates:return {'valid':False,'reason':'분홍색 세로 튜브 외형 미검출','bilateral_contact_candidate':False}
    contour=max(candidates,key=lambda pair:pair[0])[1]
    body=np.zeros((h,w),np.uint8);cv2.drawContours(body,[contour],-1,255,-1)
    x,y,bw,bh=cv2.boundingRect(contour)
    # White fingers below the image centre; label pixels inside the body
    # cannot count as fingers outside the left/right silhouette.
    white=((lab[:,:,0]>100)&(lab[:,:,1]>=119)&(lab[:,:,1]<=136)&(hsv[:,:,1]<85)).astype(np.uint8)
    # Only components connected toward the camera-side bottom can represent
    # the fingers. White lettering in the product cannot establish contact.
    count,labels,stats,_=cv2.connectedComponentsWithStats(white,8)
    keep=[]
    for i in range(1,count):
        sx,sy,sw,sh,area=stats[i]
        if area>=150 and sy+sh>=h*.97 and sy<h*.75:keep.append(i)
    white=np.isin(labels,keep)
    left=[];right=[];both=[]
    for row in range(max(int(h*.48),y),min(int(h*.88),y+bh)):
        xs=np.flatnonzero(body[row])
        if not len(xs):continue
        a,b=int(xs[0]),int(xs[-1]);window=max(12,round(w*.09))
        l=np.flatnonzero(white[row,max(0,a-window):a]);r=np.flatnonzero(white[row,b+1:min(w,b+window)])
        lg=a-(max(0,a-window)+int(l[-1])) if len(l)>=6 else None
        rg=1+int(r[0]) if len(r)>=6 else None
        if lg is not None:left.append(lg)
        if rg is not None:right.append(rg)
        if lg is not None and rg is not None and lg<=6 and rg<=6:both.append(row)
    valid=len(left)>=8 and len(right)>=8
    return {'valid':valid,'body_bbox':[x,y,x+bw,y+bh],'body_width_pixels':bw,
        'left_gap_pixels':float(np.median(left)) if left else None,'right_gap_pixels':float(np.median(right)) if right else None,
        'bilateral_contact_rows':len(both),'bilateral_contact_candidate':valid and len(both)>=8,
        'source':'pink_body_white_fingers_2d_rule','depth_verified':False,'grasp_success':False,
        'reason':'양쪽 실루엣 간격 후보 · 3D 접촉/힘은 미확정'}


def verify_lift(before,after):
    """ARM-camera background should move while an attached object stays near
    the same camera-relative location. Return evidence, never auto success."""
    a=np.asarray(before.convert('RGB'));b=np.asarray(after.convert('RGB'))
    if a.shape!=b.shape:raise ValueError('비교 영상 크기가 다릅니다.')
    first=contact_candidate(before);last=contact_candidate(after)
    if not first.get('body_bbox') or not last.get('body_bbox'):
        return {'status':'unconfirmed','reason':'양쪽 영상의 물체 추적이 필요합니다.','grasp_success':False}
    def center(box):return np.array([(box[0]+box[2])/2,(box[1]+box[3])/2])
    shift=center(last['body_bbox'])-center(first['body_bbox'])
    gray_a=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY);gray_b=cv2.cvtColor(b,cv2.COLOR_RGB2GRAY)
    mask=np.ones(gray_a.shape,np.uint8)*255
    for box in [first['body_bbox'],last['body_bbox']]:
        x,y,r,z=box;mask[max(0,y-15):min(mask.shape[0],z+15),max(0,x-15):min(mask.shape[1],r+15)]=0
    mask[int(mask.shape[0]*.48):]=0
    points=cv2.goodFeaturesToTrack(gray_a,80,.02,8,mask=mask)
    background=None;count=0
    if points is not None:
        moved,status,_=cv2.calcOpticalFlowPyrLK(gray_a,gray_b,points,None)
        if moved is not None:
            good=status.ravel()==1;count=int(good.sum())
            if count>=6:background=np.median((moved-points)[good].reshape(-1,2),axis=0)
    object_motion=float(np.linalg.norm(shift));bg_motion=float(np.linalg.norm(background)) if background is not None else None
    candidate=bool(last['bilateral_contact_candidate'] and object_motion<15 and bg_motion is not None and bg_motion>5)
    return {'status':'held_candidate' if candidate else 'unconfirmed','object_shift_pixels':shift.tolist(),
        'background_shift_pixels':background.tolist() if background is not None else None,'background_tracks':count,
        'before_contact':first,'after_contact':last,'grasp_success':False,
        'reason':'상대 움직임 증거만 기록 · 물체가 실제로 떠 있는지 외부 확인 필요'}
