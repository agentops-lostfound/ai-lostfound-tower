"""Explicit provisional biting strip; physical TCP remains user-calibrated."""
import numpy as np


def contact_reference(finger):
    points=np.asarray(finger['contour'],float);top=float(points[:,1].min());bottom=float(points[:,1].max())
    end=min(float(finger['frame_size'][1]),top+max(24,(bottom-top+1)*.45))
    import cv2
    mask=np.zeros((finger['frame_size'][1],finger['frame_size'][0]),np.uint8)
    cv2.fillPoly(mask,[points.astype(np.int32)],1)
    y=int((top+end)/2);xs=np.flatnonzero(mask[y])
    point=[int(xs[-1]) if len(xs) else int(points[:,0].max()),y]
    return {'status':'provisional','id':'fixed-distal-strip-v1','image_rows':[int(top),int(end)],
            'image_point':point,
            'model_point':'URDF gripper_frame + active TCP local correction',
            'model_verified':False,'jaw_policy':'50% 개방 · 고정 손가락 안쪽 접촉 구간 기준',
            'note':'회전형 손가락의 실제 닫힘 접촉점은 실측 전 미확정. TCP 등록에도 같은 물리 지점을 사용하세요.'}
