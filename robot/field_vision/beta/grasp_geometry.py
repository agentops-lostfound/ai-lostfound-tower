"""분홍색 핸드크림 첫 집기 시험용 2D 외형 후보. 범용 집기 성공 판정 아님."""
import cv2
import numpy as np


def target_mask(rgb,color='pink',partial=False):
    if isinstance(color,dict):
        from .object_reference import appearance_mask
        return appearance_mask(rgb,color)
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB);hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    if color=='blue':return ((hsv[:,:,0]>=90)&(hsv[:,:,0]<=150)&(hsv[:,:,1]>=5)&(lab[:,:,2]<135)&(lab[:,:,0]>90)).astype(np.uint8)*255
    if color=='black':
        return (lab[:,:,0]<100).astype(np.uint8)*255
    if color=='white':
        return ((lab[:,:,0]>165)&(hsv[:,:,1]<55)&(lab[:,:,1]>=125)).astype(np.uint8)*255
    if color=='red':
        return (((hsv[:,:,0]<12)|(hsv[:,:,0]>168))&(hsv[:,:,1]>75)&(hsv[:,:,2]>60)).astype(np.uint8)*255
    if color!='pink':raise ValueError('지원하지 않는 목표 바탕색: '+str(color))
    return ((lab[:,:,1]>(137 if partial else 140))&(lab[:,:,0]>90)&(hsv[:,:,1]<210)).astype(np.uint8)*255

def pink_tube(image, *, cropped=False, camera='영상', partial=False,color='pink'):
    # Legacy function name retained for diagnostics; the live flow supplies an
    # appearance reference, with no class/color/elongation restriction.
    if isinstance(color,dict):
        from .object_reference import matched_shape
        return matched_shape(image,color)
    rgb=np.asarray(image.convert('RGB'));lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB);hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    mask=target_mask(rgb,color,partial)
    if partial and color=='blue':
        mask[lab[:,:,1]<129]=0  # Reject green/neutral board pixels in the wrist fixture.
        # Remove isolated low-saturation background pixels before bridging the label.
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    # The white product label can split a tube into two pink components.
    # Exclude the camera's bottom desk strip in this fixture, then bridge it.
    if not cropped and not partial:mask[int(image.height*.9):]=0
    # Pad tight detector crops: OpenCV's default border otherwise expands
    # sparse color spots into an almost full rectangular crop.
    if cropped:
        mask=cv2.copyMakeBorder(mask,21,21,21,21,cv2.BORDER_CONSTANT,value=0)
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((41,41),np.uint8))[21:-21,21:-21]
    else:
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((41,41),np.uint8))
    if partial and color=='pink':
        # Wrist fixture: target is central; exclude pink-tinted white fingers.
        mask[:,:int(image.width*.3)]=0;mask[:,int(image.width*.7):]=0
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for contour in contours:
        area=cv2.contourArea(contour)
        if not (image.width*image.height*.08 if cropped else 1500)<area<image.width*image.height*(.98 if cropped else .9 if partial else .65):continue
        rect=cv2.minAreaRect(contour);box=cv2.boxPoints(rect)
        edges=np.roll(box,-1,axis=0)-box;lengths=np.linalg.norm(edges,axis=1);index=int(np.argmax(lengths));long=float(lengths[index]);short=float(lengths[(index+1)%4])
        if long/max(short,1)<(1.2 if partial or color in {'black','white','red'} else 1.6) or area/max(long*short,1)<.4:continue
        direction=edges[index]/long;angle=float(np.degrees(np.arctan2(direction[1],direction[0]))%180)
        center=np.asarray(rect[0]);start=center-direction*long*.35;end=center+direction*long*.35
        candidates.append({'method':'pink_tube_test_color_mask','center_pixels':center.tolist(),'long_axis_deg':angle,
            'long_axis_segment':[start.tolist(),end.tolist()],'box_pixels':box.tolist(),'length_pixels':long,'width_pixels':short,
            'grasp_center_pixels':center.tolist(),'opening_axis_deg':(angle+90)%180,
            'arm_camera_orientation_candidate':abs(angle-90)<20,'area_pixels':area,
            'depth_known':False,'grasp_success_verified':False})
    if not candidates:raise ValueError(camera+'에서 선택한 '+color+' 물품 외형을 찾지 못했습니다.')
    return max(candidates,key=lambda c:c['area_pixels'])
