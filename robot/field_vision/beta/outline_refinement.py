"""Complete a located object's silhouette against the green storage background."""
import cv2
import numpy as np
from .object_reference import shape_from_mask


def refine_outline(image,reference,located):
    rgb=np.asarray(image.convert('RGB'));h,w=rgb.shape[:2]
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    box=np.asarray(located['box_pixels'],np.float32)
    center=box.mean(0);edges=np.linalg.norm(np.roll(box,-1,axis=0)-box,axis=1)
    # An expanded rotated ROI preserves white caps without joining nearby objects.
    expanded=center+(box-center)*[1.45,1.35]
    region=np.zeros((h,w),np.uint8);cv2.fillConvexPoly(region,np.rint(expanded).astype(np.int32),255)
    from . import arm_roi
    region=arm_roi.apply(region)          # v0.2.69: never grow past the tracked detector box
    green=(hsv[:,:,0]>=35)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=12)
    if np.count_nonzero(green)<h*w*.08:raise ValueError('초록 보관함 배경 근거 부족 · 전체 외곽 재분리 불가')
    # Background hue is measured from the visible green foam, not the object palette.
    hue=float(np.median(hsv[:,:,0][green]))
    background=green & (np.abs(hsv[:,:,0].astype(float)-hue)<32)
    excluded=np.zeros((h,w),np.uint8)
    fixed=reference.get('fixed_finger')
    if fixed:cv2.fillPoly(excluded,[np.asarray(fixed['contour'],np.int32)],255)
    from .grasp_alignment import visible_fingers
    for contour,bounds in visible_fingers(image):
        x,y,bw,bh=bounds
        # Only silhouettes entering the bottom, outside the located object's core.
        if y+bh>=h-3 and (x+bw<center[0] or x>center[0]):cv2.drawContours(excluded,[contour],-1,255,-1)
    from .markers import exclude_markers
    _,markers=exclude_markers(image)
    for x,y,r,b in markers:excluded[y:b,x:r]=255
    mask=((~background)&(region>0)&(excluded==0)).astype(np.uint8)*255
    # Use background evidence as GrabCut seeds. Low-saturation foam and the
    # white cap can share hue; spatial color boundaries separate them.
    gc=np.full((h,w),cv2.GC_BGD,np.uint8)
    gc[region>0]=cv2.GC_PR_BGD
    gc[mask>0]=cv2.GC_PR_FGD
    core=np.zeros((h,w),np.uint8)
    cv2.fillConvexPoly(core,np.rint(center+(box-center)*.55).astype(np.int32),255)
    gc[(core>0)&(~background)&(excluded==0)]=cv2.GC_FGD
    gc[excluded>0]=cv2.GC_BGD
    if np.any(gc==cv2.GC_FGD):
        cv2.grabCut(rgb,gc,None,np.zeros((1,65)),np.zeros((1,65)),3,cv2.GC_INIT_WITH_MASK)
        mask=np.isin(gc,[cv2.GC_FGD,cv2.GC_PR_FGD]).astype(np.uint8)*255
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    mask[excluded>0]=0
    count,labels,stats,centers=cv2.connectedComponentsWithStats(mask)
    seed=np.zeros((h,w),np.uint8);cv2.fillConvexPoly(seed,np.rint(center+(box-center)*.7).astype(np.int32),1)
    candidates=[]
    for i in range(1,count):
        overlap=int(np.count_nonzero((labels==i)&(seed>0)))
        if overlap>=30:candidates.append((overlap,i))
    if not candidates:raise ValueError('대상 위치와 연결된 전체 외곽을 찾지 못했습니다.')
    _,chosen=max(candidates)
    body=(labels==chosen).astype(np.uint8)*255
    # Fill holes/printed text inside the connected object envelope.
    contours,_=cv2.findContours(body,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(body,contours,-1,255,-1)
    from .partial_boundary import trim_finger_merge
    body=trim_finger_merge(body,reference)
    shape=shape_from_mask(body)
    old_long=float(located['length_pixels']);old_short=float(located['width_pixels'])
    shape['extent_penalty']=0 if .85<=shape['length_pixels']/old_long<=1.55 and .55<=shape['width_pixels']/old_short<=1.45 else .25
    # A newly opened/closed jaw can hide the cap. Retain a small previous
    # longitudinal extent only, without restoring its potentially bad width.
    new_box=np.asarray(shape['box_pixels']);v=np.roll(new_box,-1,axis=0)-new_box
    direction=v[int(np.argmax(np.linalg.norm(v,axis=1)))];direction/=np.linalg.norm(direction)
    old_projection=box@direction;projection=new_box@direction
    low,high=float(projection.min()),float(projection.max())
    for edge_value,old_value in [(low,float(old_projection.min())),(high,float(old_projection.max()))]:
        extra=old_value-edge_value
        if abs(extra)<shape['length_pixels']*.1:
            ids=np.abs(projection-edge_value)<1
            if (edge_value==low and extra<0) or (edge_value==high and extra>0):new_box[ids]+=direction*extra
    shape['box_pixels']=new_box.tolist()
    shape['length_pixels']=float(np.ptp(new_box@direction))
    complete_center=new_box.mean(axis=0)
    shape['center_pixels']=shape['grasp_center_pixels']=complete_center.tolist()
    shape['long_axis_segment']=[(complete_center-direction*shape['length_pixels']*.35).tolist(),
                                (complete_center+direction*shape['length_pixels']*.35).tolist()]
    expected=reference.get('physical_size_mm')
    if expected:
        # Absolute pixel/mm is unknown at the wrist; compare the two dimension
        # scales, rather than borrowing the lateral motion's px/mm as depth.
        scales=np.array([shape['length_pixels']/expected['length'],shape['width_pixels']/expected['width']])
        ratio=float(scales[0]/scales[1])
        shape['aspect_ratio_penalty']=0 if .65<=ratio<=1.55 else .25
    from .partial_boundary import clipped_sides,edge_evidence
    sides=clipped_sides(shape['box_pixels'],w,h)
    if sides:
        shape['aspect_ratio_penalty']=0
        shape['visible_boundary']=edge_evidence(rgb,body,reference,located)
    shape.update(method='green_background_complete_outline',background_hue=hue,
                 located_box=located['box_pixels'],physical_size_mm=expected,
                 full_extent_clipped=bool(sides),clipped=bool(sides),clipped_sides=sides)
    return shape
