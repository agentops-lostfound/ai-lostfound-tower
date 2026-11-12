"""고정 초록색 보관함의 표시 후보와 물체 부분 중복을 보수적으로 정리."""
import cv2
import numpy as np


def suppress_parts(items):
    kept=[]
    for obj in sorted(items,key=lambda o:(o['bbox'][2]-o['bbox'][0])*(o['bbox'][3]-o['bbox'][1]),reverse=True):
        x,y,r,b=obj['bbox'];area=max(1,(r-x)*(b-y))
        duplicate=False
        for parent in kept:
            if parent['category']!=obj['category']: continue
            a,c,d,e=parent['bbox'];parent_area=max(1,(d-a)*(e-c))
            if area/parent_area>.2 or parent['score']<obj['score']: continue
            # A cap can protrude slightly beyond the tube detector's box.
            pad=min(16,max(d-a,e-c)*.06)
            overlap=max(0,min(r,d+pad)-max(x,a-pad))*max(0,min(b,e+pad)-max(y,c-pad))
            if overlap/area>.85: duplicate=True;break
        if not duplicate: kept.append(obj)
    return sorted(kept,key=lambda o:o['score'],reverse=True)


def is_support_preview(image,obj):
    # Only low-confidence display candidates are filtered by appearance.
    # Never reject a confirmed object simply because its colour is green.
    if not obj.get('preview'): return False
    x,y,r,b=map(int,obj['bbox'])
    if not .75<(r-x)/max(1,b-y)<1.3: return False
    crop=np.asarray(image.crop((x,y,r,b)).convert('RGB'))
    if not crop.size: return False
    hsv=cv2.cvtColor(crop,cv2.COLOR_RGB2HSV)
    green=cv2.inRange(hsv,np.array([30,35,35]),np.array([100,255,255]))
    return float((green>0).mean())>.9


def suppress_supports(items):
    """v0.2.58: drop a weak box that holds a much stronger, much smaller detection.

    A foam block under a USB (OWL 0.17 'card holder') contains the USB (0.66); the
    block is its support, not a second object. Category is ignored on purpose.
    """
    def area(b):return max(1,(b[2]-b[0])*(b[3]-b[1]))
    kept=[]
    for obj in items:
        a=obj['bbox'];support=False
        for other in items:
            if other is obj:continue
            b=other['bbox']
            inside=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))/area(b)
            if inside>.85 and area(a)>=2*area(b) and other.get('score',0)>=obj.get('score',0)+.2:support=True;break
        if not support:kept.append(obj)
    return kept


def reject_attached_parts(image,items):
    """v0.2.62: a board-trained YOLO box that is only a small piece of a bigger connected
    object (hand-cream cap detected as 'usb' 0.52) is not an object on its own.

    Uses the foam-background mask: the blob under the box must not extend far beyond it.
    """
    import cv2
    try:
        from .detector_dataset import object_mask,board_polygon
        rgb=np.asarray(image.convert('RGB'));mask,_=object_mask(rgb,board_polygon(image))
    except Exception:
        return items
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    for obj in items:
        # all detectors (v0.2.64): OWL also boxed the upper hand-cream cap as a separate item
        if obj.get('quality')=='rejected':continue
        x0,y0,x1,y1=[int(v) for v in obj['bbox']]
        window=labels[max(0,y0):y1,max(0,x0):x1]
        ids,counts=np.unique(window[window>0],return_counts=True)
        if not len(ids):continue
        k=int(ids[np.argmax(counts)]);cx,cy,cw,ch,_=stats[k]
        box_area=max(1,(x1-x0)*(y1-y0));blob_area=max(1,cw*ch)
        if blob_area>2.2*box_area:
            obj['quality']='rejected';obj.setdefault('reasons',[]).append('더 큰 물체의 일부(뚜껑·받침 등)')
            obj['attached_to']=[int(cx),int(cy),int(cx+cw),int(cy+ch)]
    return items
