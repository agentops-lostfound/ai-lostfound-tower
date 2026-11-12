"""현재 분홍 튜브 시험의 물체 외곽/집게 내측 경계. 가려짐은 미검출 처리."""
import cv2
import numpy as np
from .grasp_geometry import target_mask


def edges(image,color='pink'):
    rgb=np.asarray(image.convert('RGB'));h,w=rgb.shape[:2]
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB);hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    pink=target_mask(rgb,color,partial=True)
    pink[int(h*.92):]=0
    pink=cv2.morphologyEx(pink,cv2.MORPH_CLOSE,np.ones((21,21),np.uint8))
    contours,_=cv2.findContours(pink,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    plausible=[]
    for c in contours:
        x,y,bw,bh=cv2.boundingRect(c)
        if isinstance(color,dict):
            if cv2.contourArea(c)>max(40,w*h*.001):plausible.append(c)
        elif cv2.contourArea(c)>2000 and bh>h*.35 and .2*w<x+bw/2<.8*w:plausible.append(c)
    if not plausible:return {'valid':False,'reason':'튜브 외형 미검출','bilateral_contact_candidate':False}
    contour=max(plausible,key=cv2.contourArea)
    hull=cv2.convexHull(contour);body=np.zeros((h,w),np.uint8);cv2.drawContours(body,[hull],-1,255,-1)
    white=(lab[:,:,0]>100)&(np.abs(lab[:,:,1].astype(float)-128)<9)&(hsv[:,:,1]<55)
    left=[];right=[];bodyrows=[]
    for y in range(int(h*.66),int(h*.84)):
        xs=np.flatnonzero(body[y])
        if len(xs)<20:continue
        a,b=int(xs[0]),int(xs[-1]);bodyrows.append([a,y,b,y])
        # Continuous 18px finger material excludes a narrow white rim/label.
        def runs(mask):
            z=np.r_[False,mask,False].astype(np.int8);starts=np.flatnonzero(np.diff(z)==1);ends=np.flatnonzero(np.diff(z)==-1)
            return [(s,e) for s,e in zip(starts,ends) if e-s>=18]
        ls=runs(white[y,:a]);rs=runs(white[y,b+1:])
        if ls:
            inner=max(e for s,e in ls);gap=a-inner
            if gap<w*.35:left.append([int(inner),int(y),int(gap)])
        if rs:
            inner=min(s for s,e in rs)+b+1;gap=inner-b
            if gap<w*.35:right.append([int(inner),int(y),int(gap)])
    lg=float(np.median([p[2] for p in left])) if len(left)>=12 else None
    rg=float(np.median([p[2] for p in right])) if len(right)>=12 else None
    return {'valid':lg is not None and rg is not None,'left_gap_pixels':lg,'right_gap_pixels':rg,
        'left_edge':left[::5],'right_edge':right[::5],'body_edges':bodyrows[::5],
        'bilateral_contact_candidate':lg is not None and rg is not None and lg<=5 and rg<=5,
        'reason':'집게 양쪽 외부 경계 추적' if lg is not None and rg is not None else '집게 한쪽 미검출 · 접촉 판단 불가',
        'grasp_success':False,'depth_verified':False}


def overlay(image,result):
    rgb=np.asarray(image.convert('RGB')).copy()
    for key,color in [('left_edge',(70,180,255)),('right_edge',(70,180,255))]:
        for x,y,g in result.get(key,[]):cv2.circle(rgb,(int(x),int(y)),3,color,-1)
    for a,y,b,_ in result.get('body_edges',[]):
        cv2.circle(rgb,(int(a),int(y)),3,(255,195,70),-1);cv2.circle(rgb,(int(b),int(y)),3,(255,195,70),-1)
    from PIL import Image
    return Image.fromarray(rgb)
