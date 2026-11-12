"""Temporal grasp evidence in the wrist camera; uncertainty is not success."""
import cv2
import numpy as np
from .grasp_geometry import target_mask


class LiftTracker:
    def __init__(self,image,reference,frame_id,captured):
        rgb=np.asarray(image.convert('RGB'));self.previous=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        mask=target_mask(rgb,reference,partial=True)
        mask=cv2.erode(mask,np.ones((5,5),np.uint8))
        background=cv2.bitwise_not(cv2.dilate(mask,np.ones((25,25),np.uint8)))
        fixed=reference.get('fixed_finger',{}) if isinstance(reference,dict) else {}
        if fixed.get('frame_size')==[image.width,image.height]:
            finger=np.zeros_like(mask);cv2.fillPoly(finger,[np.asarray(fixed['contour'],np.int32)],255)
            finger=cv2.dilate(finger,np.ones((15,15),np.uint8));mask[finger>0]=0;background[finger>0]=0
        # Unregistered moving finger occupies the lower wrist image. It must
        # not masquerade as a moving background reference.
        background[int(image.height*.65):]=0
        self.points=cv2.goodFeaturesToTrack(self.previous,100,.015,5,mask=mask)
        self.bg=cv2.goodFeaturesToTrack(self.previous,100,.015,8,mask=background)
        self.origin=None if self.points is None else self.points.copy()
        self.bg_origin=None if self.bg is None else self.bg.copy()
        self.frame_id=frame_id;self.captured=captured;self.frames=0;self.samples=[]
        # v0.2.71 (flow-aace61d2, blue lip balm): the balm was held, but the round body
        # rolled in the one-finger grip, so its printed text (the tracked features) slid
        # ~52px while the silhouette stayed put -> judged 'not held'. Keep the outline too.
        self.reference=reference;self.last_image=None
        self.outline=self.locate(image)

    def locate(self,image):
        if not isinstance(self.reference,dict):return None
        try:
            from .object_reference import matched_shape
            from . import arm_roi
            with arm_roi.paused():shape=matched_shape(image,self.reference)
            return {'center':[float(v) for v in shape['center_pixels']],'length':float(shape['length_pixels']),'width':float(shape['width_pixels'])}
        except (ValueError,KeyError,TypeError):return None

    @staticmethod
    def track(a,b,points,origin):
        if points is None or len(points)<3:return None,None,None
        moved,status,_=cv2.calcOpticalFlowPyrLK(a,b,points,None)
        if moved is None:return None,None,None
        back,back_status,_=cv2.calcOpticalFlowPyrLK(b,a,moved,None)
        if back is None:return None,None,None
        good=(status.ravel()==1)&(back_status.ravel()==1)&(np.linalg.norm((back-points).reshape(-1,2),axis=1)<1.5)
        moved=moved[good];origin=origin[good]
        displacement=np.linalg.norm((moved-origin).reshape(-1,2),axis=1)
        return moved,origin,float(np.median(displacement)) if len(moved)>=6 else None

    def sample(self,image,frame_id,captured):
        if frame_id==self.frame_id or captured<=self.captured:return
        gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
        if gray.shape!=self.previous.shape:return
        self.points,self.origin,obj=self.track(self.previous,gray,self.points,self.origin)
        self.bg,self.bg_origin,bg=self.track(self.previous,gray,self.bg,self.bg_origin)
        self.frames+=1;self.samples.append(dict(frame_id=frame_id,captured=captured,object_shift_px=obj,background_shift_px=bg,
            object_tracks=0 if self.points is None else len(self.points),background_tracks=0 if self.bg is None else len(self.bg)))
        self.previous=gray;self.frame_id=frame_id;self.captured=captured;self.last_image=image

    def result(self,lift_mm):
        valid=[s for s in self.samples if s['object_shift_px'] is not None and s['background_shift_px'] is not None]
        last=self.samples[-1] if self.samples else {}
        status='unconfirmed';reason='물체/배경의 연속 추적 근거 부족'
        if lift_mm<15:reason='실제 관절 피드백 기준 상승량 15mm 미만'
        elif len(valid)>=3 and last in valid:
            obj=last['object_shift_px'];bg=last['background_shift_px']
            stable=sum(s['object_shift_px']<=12 for s in valid)/len(valid)>=.8
            if stable and obj<=12 and bg>=5 and bg>=obj+3:
                status='held_likely';reason='상승 중 물체는 집게 기준 위치 유지, 배경은 이동 · 영상 기반 파지 추정'
            elif obj>20 and bg>=5:
                status='not_held_likely';reason='상승 중 물체가 집게 기준 위치를 유지하지 못함 · 미파지/미끄러짐 추정'
            else:reason='물체와 배경 움직임 차이가 충분하지 않음'
        outline=self.outline_evidence(last.get('background_shift_px'))
        if outline and status!='held_likely' and lift_mm>=15 and outline['held']:
            status='held_likely';reason='표면 무늬는 움직였지만(원통 회전 추정) 물체 외곽은 집게 기준 위치 유지, 배경은 이동 · 영상 기반 파지 추정'
        return dict(status=status,reason=reason,lift_mm=float(lift_mm),frames=self.frames,samples=self.samples,outline=outline,
                    grasp_success=False,method='wrist_relative_temporal_tracking',physical_success_verified=False)

    def outline_evidence(self,background_shift):
        start=getattr(self,'outline',None);image=getattr(self,'last_image',None)
        if not start or image is None:return None
        end=self.locate(image)
        if not end:return {'held':False,'start':start,'end':None}
        shift=float(((end['center'][0]-start['center'][0])**2+(end['center'][1]-start['center'][1])**2)**.5)
        ratio=[end['length']/max(start['length'],1),end['width']/max(start['width'],1)]
        # Same place and size in the wrist view while the board clearly moved away.
        held=shift<=20 and all(.8<=r<=1.25 for r in ratio) and (background_shift or 0)>=30
        return {'held':bool(held),'shift_px':shift,'size_ratio':ratio,'background_shift_px':background_shift,'start':start,'end':end}
