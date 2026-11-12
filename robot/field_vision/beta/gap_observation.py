"""One occlusion-aware measurement shared by correction and descent checks."""
import cv2
import numpy as np
from .grasp_geometry import pink_tube
from .coarse_grasp import fixed_gap


class GapObserver:
    def __init__(self,image,color,finger,settings=None):
        self.color=color;self.finger=finger;self.settings=settings or {}
        shape=pink_tube(image,partial=True,color=color)
        self.box=np.asarray(shape['box_pixels'],np.float32)
        self.boundary=shape.get('visible_boundary')
        self.gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
        self.points=self.features(self.gray,self.box)
        from .grasp_reference import contact_reference
        self.contact=contact_reference(finger)
        self.last_registration={'method':'before_open','shift_px':0.}

    def features(self,gray,box):
        mask=np.zeros(gray.shape,np.uint8)
        cv2.fillPoly(mask,[np.rint(box).astype(np.int32)],255)
        cv2.fillPoly(mask,[np.asarray(self.finger['contour'],np.int32)],0)
        return cv2.goodFeaturesToTrack(gray,100,.015,5,mask=mask)

    def measure(self,image,fresh=False):
        from .object_reference import large_item
        if large_item(self.color):
            # v0.2.78: wide items re-find the edge nearest to the finger on every frame
            # instead of tracking a box that may sit on the wrong part (flow-0d4bc00a).
            shape=pink_tube(image,partial=True,color=self.color)
            self.box=np.asarray(shape['box_pixels'],np.float32);self.boundary=shape.get('visible_boundary')
            result=fixed_gap(image,self.color,self.finger,self.settings,shape=shape)
            result['registration']={'method':'nearest_edge_per_frame','remeasured':True,'shift_px':0.}
            self.last_registration=result['registration']
            return result
        gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
        if gray.shape!=self.gray.shape:raise ValueError('ARM 영상 해상도 변경 · 개방 전 외형을 다시 등록해야 합니다.')
        transform=None;inlier_count=0;scale=1.
        # fresh=True: re-detect the outline instead of tracking (weak edge retry).
        if not fresh and self.points is not None and len(self.points)>=6:
            dst,status,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,self.points,None)
            if dst is not None:
                back,back_status,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,dst,None)
                if back is not None:
                    ok=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(back-self.points,axis=2).ravel()<1.5)
                    # Occluded points on the fixed finger are not object evidence.
                    finger=np.zeros(gray.shape,np.uint8);cv2.fillPoly(finger,[np.asarray(self.finger['contour'],np.int32)],1)
                    xy=np.rint(dst.reshape(-1,2)).astype(int)
                    valid=(xy[:,0]>=0)&(xy[:,0]<gray.shape[1])&(xy[:,1]>=0)&(xy[:,1]<gray.shape[0])
                    for i in np.flatnonzero(valid):
                        if finger[xy[i,1],xy[i,0]]:ok[i]=False
                    ok &= valid
                    if ok.sum()>=6:
                        transform,inliers=cv2.estimateAffinePartial2D(self.points[ok],dst[ok],method=cv2.RANSAC,ransacReprojThreshold=2)
                        inlier_count=0 if inliers is None else int(inliers.sum())
        if inlier_count<6:transform=None
        if transform is not None:
            scale=float(np.linalg.norm(transform[0,:2]))
            if not .8<=scale<=1.25:transform=None
        if transform is not None:
            new_box=cv2.transform(self.box[None],transform)[0]
            if self.boundary:
                self.boundary=dict(self.boundary,points=cv2.transform(np.float32([self.boundary['points']]),transform)[0].tolist())
                points=np.asarray(self.boundary['points']);direction=points[1]-points[0]
                angle=float(np.degrees(np.arctan2(direction[1],direction[0]))%180)
                if abs((angle-90+90)%180-90)>15 or np.any(points[:,0]<8) or np.any(points[:,0]>image.width-8):
                    transform=None
        if transform is not None:
            shift=float(np.linalg.norm(new_box.mean(0)-self.box.mean(0)))
            registration={'method':'visible_feature_registration','inliers':inlier_count,'shift_px':shift,
                          'remeasured':shift>8 or abs(scale-1)>.05}
        else:
            # No reliable correspondence: re-acquire a complete matched box.
            fresh=pink_tube(image,partial=True,color=self.color)
            new_box=np.asarray(fresh['box_pixels'],np.float32)
            self.boundary=fresh.get('visible_boundary')
            if fresh.get('method')!='matched_target_features' and not fresh.get('clipped'):
                # Textureless items can still be re-acquired by their full
                # appearance envelope, but a shrunken occluded fragment cannot.
                before=np.sort(np.linalg.norm(np.roll(self.box,-1,axis=0)-self.box,axis=1))[::2]
                after=np.sort(np.linalg.norm(np.roll(new_box,-1,axis=0)-new_box,axis=1))[::2]
                ratios=after/np.maximum(before,1)
                # A changed ratio alone is evidence, not an identity veto.
            registration={'method':'fresh_target_match','remeasured':True,
                          'shift_px':float(np.linalg.norm(new_box.mean(0)-self.box.mean(0)))}
        self.box=new_box;self.gray=gray;self.points=self.features(gray,new_box)
        self.last_registration=registration
        edges=np.linalg.norm(np.roll(new_box,-1,axis=0)-new_box,axis=1)
        result=fixed_gap(image,self.color,self.finger,self.settings,
                         shape={'box_pixels':new_box.tolist(),'width_pixels':float(edges.min()),'visible_boundary':self.boundary})
        result['registration']=registration
        return result


def fixed_passed(clearance):
    fixed=[f for f in clearance.get('fingers',[]) if f.get('finger')=='fixed']
    return bool(fixed) and all(f.get('side_ok',False) and f.get('gap_px',0)>=clearance.get('required_px',4) for f in fixed)


def shared_clearance(auxiliary,gap):
    """Replace the legacy fixed-finger metric with the correction metric."""
    moving=[f for f in auxiliary.get('fingers',[]) if f.get('finger')!='fixed']
    fixed={'finger':'fixed','gap_px':gap['gap_px'],'side_ok':gap['in_band']}
    required=gap['low_px']
    moving_ok=all(f.get('side_ok',False) and f.get('gap_px',0)>=auxiliary.get('required_px',4) for f in moving)
    return dict(auxiliary,fingers=[fixed]+moving,required_px=required,fixed_gap=gap,
                clear=gap['in_band'] and moving_ok and (bool(moving) or auxiliary.get('clear',False)),reason='공통 고정 손가락 간격 %.1fpx / 허용 %.1f~%.1fpx'%(gap['gap_px'],gap['low_px'],gap['high_px']))


def ensure_fixed_clearance(check,correct,attempts=2):
    """Correction and final descent use the same observation; never waive fixed failure."""
    for attempt in range(attempts+1):
        clearance=check()
        if fixed_passed(clearance):return clearance
        if attempt==attempts:break
        correct()
    raise ValueError('고정 손가락 간격 재보정 실패 · 하강하지 않습니다.')
