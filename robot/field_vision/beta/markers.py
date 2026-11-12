"""위치 기준 ArUco는 보존하고 물품 검출 입력에서만 제외한다."""
import cv2
import numpy as np
from PIL import Image


def exclude_markers(image,fallback=None):
    rgb=np.asarray(image.convert('RGB')).copy()
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    boxes=[]
    # 아직 팀의 마커 사전이 고정되지 않아 표준 사전을 함께 지원한다.
    for name in ['DICT_4X4_1000','DICT_5X5_1000','DICT_6X6_1000','DICT_7X7_1000','DICT_ARUCO_ORIGINAL']:
        detector=cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco,name)))
        corners,ids,_=detector.detectMarkers(gray)
        if ids is None: continue
        for points in corners:
            p=points.reshape(-1,2)
            x,y=p.min(axis=0);r,b=p.max(axis=0)
            # Include the white backing around the printed code.
            pad=max(6,int(max(r-x,b-y)*.65))
            box=[max(0,int(x)-pad),max(0,int(y)-pad),min(image.width,int(r)+pad+1),min(image.height,int(b)+pad+1)]
            if any(abs(box[0]-q[0])+abs(box[1]-q[1])<12 for q in boxes): continue
            boxes.append(box)
    # v0.2.58: a marker missed in this frame (3 of 4 found) was detected as an object.
    # Fill in any previously seen marker box that has no detection near it now.
    found=len(boxes)
    for q in fallback or []:
        cx,cy=(q[0]+q[2])/2,(q[1]+q[3])/2
        if not any(abs((p[0]+p[2])/2-cx)+abs((p[1]+p[3])/2-cy)<40 for p in boxes):boxes.append(list(q))
    for x,y,r,b in boxes:
        margin=10
        patch=rgb[max(0,y-margin):min(image.height,b+margin),max(0,x-margin):min(image.width,r+margin)]
        rgb[y:b,x:r]=np.median(patch.reshape(-1,3),axis=0).astype(np.uint8)
    boxes=_Boxes(boxes);boxes.found=found
    return Image.fromarray(rgb),boxes


class _Boxes(list):
    """Marker boxes; .found = how many were detected in THIS frame (rest = remembered)."""


def is_marker_box(box, markers):
    x,y,r,b=box
    area=max(1,(r-x)*(b-y))
    for a,c,d,e in markers:
        overlap=max(0,min(r,d)-max(x,a))*max(0,min(b,e)-max(y,c))
        if overlap/area>.5: return True
    return False
