"""Category-independent appearance from the selected detection, not a color name."""
import cv2
import numpy as np


def shape_from_mask(mask):
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    contours=[c for c in contours if cv2.contourArea(c)>=max(20,mask.size*.001)]
    if not contours:raise ValueError('선택 물품의 외곽을 분리하지 못했습니다.')
    contour=max(contours,key=cv2.contourArea)
    rect=cv2.minAreaRect(contour);box=cv2.boxPoints(rect)
    vectors=np.roll(box,-1,axis=0)-box;lengths=np.linalg.norm(vectors,axis=1)
    i=int(np.argmax(lengths));long=float(lengths[i]);short=float(lengths[(i+1)%4])
    if short<2:raise ValueError('물품 외곽의 폭을 계산할 수 없습니다.')
    direction=vectors[i]/long;center=np.asarray(rect[0]);angle=float(np.degrees(np.arctan2(*direction[::-1]))%180)
    return dict(method='selected_object_appearance',center_pixels=center.tolist(),grasp_center_pixels=center.tolist(),
                box_pixels=box.tolist(),contour_pixels=contour.reshape(-1,2).tolist(),
                long_axis_segment=[(center-direction*long*.35).tolist(),(center+direction*long*.35).tolist()],
                long_axis_deg=angle,opening_axis_deg=(angle+90)%180,length_pixels=long,width_pixels=short,
                axis_reliable=long/short>=1.2,area_pixels=float(cv2.contourArea(contour)),
                arm_camera_orientation_candidate=abs(angle-90)<20,depth_known=False,grasp_success_verified=False)


def palette(pixels):
    bins=(pixels.astype(np.int32)//24)
    keys,counts=np.unique(bins,axis=0,return_counts=True)
    order=np.argsort(counts)[::-1][:12]
    return [np.median(pixels[np.all(bins==keys[i],axis=1)],axis=0).tolist() for i in order]


def palette_weights(pixels,colors):
    """Pixel share of each palette color (nearest-color assignment)."""
    if not len(pixels) or not len(colors):return []
    sample=pixels[::max(1,len(pixels)//4000)].astype(np.float32)
    nearest=np.argmin(np.linalg.norm(sample[:,None]-np.asarray(colors,np.float32)[None],axis=2),axis=1)
    return (np.bincount(nearest,minlength=len(colors))/len(sample)).tolist()


def dominant_colors(colors,weights,cover=.85):
    """Colors that together cover most of the object. Small details such as a
    phone camera lens (black) must not make every dark neighbor look like the
    target in the ARM view (flow-41bc1bd2: black power bank chosen for a white phone)."""
    if not weights or len(weights)!=len(colors):return colors
    order=np.argsort(weights)[::-1];chosen=[];total=0.
    for i in order:
        chosen.append(colors[i]);total+=weights[i]
        if total>=cover:break
    return chosen


def build_reference(image,bbox):
    rgb=np.asarray(image.convert('RGB'));h,w=rgb.shape[:2]
    x,y,r,b=map(int,bbox);x=max(0,x);y=max(0,y);r=min(w,r);b=min(h,b)
    if r-x<5 or b-y<5:raise ValueError('물품 검출 박스가 너무 작습니다.')
    pad=max(8,round(max(r-x,b-y)*.12));sx=max(0,x-pad);sy=max(0,y-pad);sr=min(w,r+pad);sb=min(h,b+pad)
    crop=rgb[sy:sb,sx:sr];mask=np.full(crop.shape[:2],cv2.GC_BGD,np.uint8)
    mask[y-sy:b-sy,x-sx:r-sx]=cv2.GC_PR_FGD
    if not np.any(mask==cv2.GC_BGD):raise ValueError('물품 주위 배경이 필요합니다. 검출 영역을 확인하세요.')
    try:cv2.grabCut(crop,mask,None,np.zeros((1,65)),np.zeros((1,65)),3,cv2.GC_INIT_WITH_MASK)
    except cv2.error as exc:raise ValueError('선택 물품 외곽 분리 실패') from exc
    fg=np.isin(mask,[cv2.GC_FGD,cv2.GC_PR_FGD]);local=fg[y-sy:b-sy,x-sx:r-sx].astype(np.uint8)*255
    shape=shape_from_mask(local)
    lab=cv2.cvtColor(crop,cv2.COLOR_RGB2LAB)
    if np.count_nonzero(fg)<20 or np.count_nonzero(~fg)<20:raise ValueError('물품과 배경을 구분할 근거가 부족합니다.')
    foreground=palette(lab[fg])
    reference={'kind':'selected_object_lab','foreground':foreground,'foreground_weights':palette_weights(lab[fg],foreground),
               'background':palette(lab[~fg]),'source_bbox':[x,y,r,b],'source_size':[w,h]}
    gray=cv2.cvtColor(rgb[y:b,x:r],cv2.COLOR_RGB2GRAY)
    points,descriptors=cv2.SIFT_create(nfeatures=350).detectAndCompute(gray,None)
    if descriptors is not None and len(points)>=8:
        reference['visual_template']={'points':[list(k.pt) for k in points],'descriptors':descriptors.astype(int).tolist(),'box':shape['box_pixels']}
    reference['aspect_ratio']=shape['length_pixels']/shape['width_pixels']
    return reference,shape


def _foam_green(rgb):
    """Same green test as background_mask (bin foam)."""
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    return (hsv[:,:,0]>=35)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=25)


def _green_target(reference):
    """True when most of the object's palette weight is itself foam-green."""
    colors=np.asarray(reference['foreground'],np.float32)
    if not len(colors):return False
    weights=np.asarray(reference.get('foreground_weights') or [1.]*len(colors),np.float32)
    if len(weights)!=len(colors):weights=np.ones(len(colors),np.float32)
    # Lab, not HSV: dark near-neutral colors (black USB, L~40) get a large HSV
    # saturation and a green-ish hue from the top view's green cast.
    green=(colors[:,0]>=60)&(colors[:,1]<=116)
    return float(weights[green].sum())>.5*float(weights.sum())


def appearance_mask(rgb,reference):
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB).astype(np.float32)
    def distance(colors):
        result=np.full(lab.shape[:2],np.inf,np.float32)
        for color in colors:result=np.minimum(result,np.linalg.norm(lab-np.asarray(color),axis=2))
        return result
    fg=distance(dominant_colors(reference['foreground'],reference.get('foreground_weights')));bg=distance(reference['background'])
    mask=((fg<35)&(fg+4<bg)).astype(np.uint8)*255
    # v0.2.52: a small dark object's top-view crop mixes in green foam, so its palette
    # gets greenish/gray entries (USB: L106 a105, L149 a118). In the ARM view those
    # matched shadowed foam and merged with the target (overlay jumped to the frame
    # edge). Foam-green pixels are never the target unless the target itself is green.
    if not _green_target(reference):mask[_foam_green(rgb)]=0
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    profile=reference.get('fixed_finger')
    if profile and profile['frame_size']==[rgb.shape[1],rgb.shape[0]]:
        cv2.fillPoly(mask,[np.asarray(profile['contour'],np.int32)],0)
    return mask


def quick_features(image,bbox):
    """Cheap visible color evidence for re-location, not a semantic description."""
    try:
        ref,_=build_reference(image,bbox)
        rgb=np.asarray(image.convert('RGB'));x,y,r,b=map(int,bbox);crop=rgb[y:b,x:r]
        mask=appearance_mask(crop,ref)>0
        hsv=cv2.cvtColor(crop,cv2.COLOR_RGB2HSV);pixels=hsv[mask]
        if len(pixels)<20:return {'body_color':'unknown'}
        colored=pixels[(pixels[:,1]>30)&(pixels[:,2]>70)]
        if len(colored)>len(pixels)*.25:
            hist=np.bincount((colored[:,0]//10).astype(int),minlength=18);peak=int(np.argmax(hist))
            if hist[max(0,peak-1):min(18,peak+2)].sum()<len(colored)*.6:return {'body_color':'unknown'}
            hue=float(np.median(colored[np.abs(colored[:,0].astype(int)-peak*10-5)<=15,0]))
            sat=float(np.median(colored[:,1]))
            color=('pink' if sat<170 else 'red') if hue>=160 or hue<8 else 'orange' if hue<22 else 'yellow' if hue<36 else 'green' if hue<85 else 'blue' if hue<135 else 'purple'
        else:
            value=float(np.median(pixels[:,2]));color='black' if value<75 else 'white' if value>185 else 'gray'
        return {'body_color':color,'source':'selected_foreground_pixels','color_only':True}
    except (ValueError,cv2.error):return {'body_color':'unknown'}


def target_component(mask,reference):
    """Keep only color regions that reach past the fixed finger's inner edge.

    After approach the target lies on the moving-finger side of the fixed finger
    (or overlaps it). A neighbor seen entirely beyond the fixed finger (the black
    power bank in flow-41bc1bd2) cannot be the target, even if it is the largest
    same-color region. Falls back to the unfiltered mask if nothing qualifies.
    """
    profile=reference.get('fixed_finger')
    if not profile or profile.get('frame_size')!=[mask.shape[1],mask.shape[0]]:return mask
    inner=float(np.asarray(profile['contour'])[:,0].max())
    count,labels,stats,centroids=cv2.connectedComponentsWithStats((mask>0).astype(np.uint8))
    # Centroid, not right edge: a neighbor whose edge just touches the finger
    # line (power bank x 0~200, finger inner ~190 in flow-6bcfafe6) is excluded,
    # while a target overlapping the finger still has its mass on the right.
    keep=[i for i in range(1,count) if centroids[i][0]>inner and stats[i,cv2.CC_STAT_AREA]>=mask.size*.002]
    if not keep:return mask
    return np.isin(labels,keep).astype(np.uint8)*255


def background_mask(rgb,reference):
    """Non-background pixels on the green foam bin, independent of target color.

    Fallback when top-view colors do not carry over to the ARM camera (exposure:
    sky-blue phone L~170 in top view looks almost white in the ARM view)."""
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    green=(hsv[:,:,0]>=35)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=25)
    mask=(~green).astype(np.uint8)*255
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    profile=reference.get('fixed_finger')
    if profile and profile['frame_size']==[rgb.shape[1],rgb.shape[0]]:
        cv2.fillPoly(mask,[np.asarray(profile['contour'],np.int32)],0)
        # The moving finger enters from the bottom edge beside the fixed finger.
        h=rgb.shape[0];inner=int(np.asarray(profile['contour'])[:,0].max())
        mask[int(h*.72):,max(0,inner-10):min(rgb.shape[1],inner+140)]=0
    return mask


def _enclosing_body(rgb,reference,shape):
    """v0.2.74 (flow-2cdc74f8, sky-blue phone): close up, the phone's top-view colours
    matched only a patch around its logo (12.6k px) while the whole non-green body was
    157k px; the 'edge' 200px inside the phone sent the gripper 20mm the wrong way.
    If the background (non-green) component holding the appearance patch is much larger,
    that component is the object."""
    from . import arm_roi
    mask=target_component(arm_roi.apply(background_mask(rgb,reference)),reference)
    count,labels,stats,_=cv2.connectedComponentsWithStats((mask>0).astype(np.uint8))
    x,y=[int(round(v)) for v in shape['center_pixels']]
    h,w=mask.shape
    if not (0<=x<w and 0<=y<h) or labels[y,x]==0:return None
    i=labels[y,x];area=int(stats[i,cv2.CC_STAT_AREA])
    if area<2.5*max(shape['area_pixels'],1) or area>.9*w*h:return None
    left=int(stats[i,cv2.CC_STAT_LEFT]);right=left+int(stats[i,cv2.CC_STAT_WIDTH])
    # Touching the left/right frame edge = merged with the wall, a marker sticker or a
    # neighbour (lip balm 260~639, USB 455~639 in past flows).
    # v0.2.75 (flow-2fad68ed): lower in the descent a large phone fills the frame up to
    # the far edge, so the strict rule dropped back to the logo patch (gap 216px, then
    # 'fixed-side edge not visible' at the floor -> rise and stop). For a large item
    # (>=60mm) only the fixed-finger side must be free; the far side may touch.
    finger=reference.get('fixed_finger') or {}
    finger_left=True
    if finger.get('frame_size')==[w,h]:finger_left=float(np.asarray(finger['contour'])[:,0].mean())<w/2
    large=float((reference.get('physical_size_mm') or {}).get('width',0))>=60
    near,far=(left<=2,right>=w-2) if finger_left else (right>=w-2,left<=2)
    if near or (far and not large):return None
    try:return shape_from_mask((labels==i).astype(np.uint8)*255)
    except ValueError:return None


def _located_shape(image,reference):
    from . import arm_roi
    roi=arm_roi.current_box(image.size)
    template=reference.get('visual_template')
    if template:
        gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
        keys,desc=cv2.SIFT_create(nfeatures=2000).detectAndCompute(gray,None)
        if desc is not None:
            pairs=cv2.BFMatcher().knnMatch(np.asarray(template['descriptors'],np.float32),desc,k=2)
            matches=[pair[0] for pair in pairs if len(pair)==2 and pair[0].distance<.75*pair[1].distance]
            if len(matches)>=8:
                src=np.float32([template['points'][m.queryIdx] for m in matches]);dst=np.float32([keys[m.trainIdx].pt for m in matches])
                H,inliers=cv2.findHomography(src,dst,cv2.RANSAC,4)
                if H is not None and inliers is not None and inliers.sum()>=6 and inliers.mean()>=.35:
                    box=cv2.perspectiveTransform(np.float32([template['box']]),H)[0]
                    inside=roi is None or (roi[0]<=box[:,0].mean()<=roi[2] and roi[1]<=box[:,1].mean()<=roi[3])
                    if inside and np.isfinite(box).all() and cv2.isContourConvex(box) and 300<cv2.contourArea(box)<image.width*image.height*.9:
                        mask=np.zeros(gray.shape,np.uint8);cv2.fillConvexPoly(mask,np.rint(box).astype(np.int32),255)
                        shape=shape_from_mask(mask)
                        original=np.asarray(template['box'],np.float32)
                        edge=np.roll(original,-1,axis=0)-original;i=int(np.argmax(np.linalg.norm(edge,axis=1)))
                        mid=(original[i]+original[(i+3)%4])/2;other=(original[(i+1)%4]+original[(i+2)%4])/2
                        axis=cv2.perspectiveTransform(np.float32([[mid,other]]),H)[0];v=axis[1]-axis[0]
                        shape.update(long_axis_deg=float(np.degrees(np.arctan2(v[1],v[0]))%180),method='matched_target_features',matched_points=int(inliers.sum()))
                        return shape
    rgb=np.asarray(image.convert('RGB'))
    try:
        # v0.2.69: only inside the tracked ARM detector box (wall/desk beyond the tray excluded).
        shape=shape_from_mask(target_component(arm_roi.apply(appearance_mask(rgb,reference)),reference))
        method='appearance_with_reference_shape_check'
        whole=_enclosing_body(rgb,reference,shape)
        if whole is not None:shape,method=whole,'background_body_enclosing_appearance'
    except ValueError:
        # Top-view colors did not carry over to the ARM camera; use the bin background.
        shape=shape_from_mask(target_component(arm_roi.apply(background_mask(rgb,reference)),reference))
        method='background_component'
    ratio=shape['length_pixels']/shape['width_pixels']/reference.get('aspect_ratio',1)
    from .partial_boundary import clipped_sides
    shape['clipped_sides']=clipped_sides(shape['box_pixels'],image.width,image.height)
    shape['clipped']=bool(shape['clipped_sides'])
    shape['aspect_ratio_penalty']=0 if shape['clipped'] or .65<=ratio<=1.55 else .25
    shape['method']=method
    if roi:shape['arm_roi']=roi
    return shape


def large_item(reference):
    """Wide item by MEASURED top-view width, never by category name."""
    return float(((reference or {}).get('physical_size_mm') or {}).get('width',0))>=60


def matched_shape(image,reference):
    if large_item(reference):
        # v0.2.78: for wide items the edge nearest to the fixed finger decides rotation
        # and gap; the region outline is kept only as context (see partial_boundary.nearest_edge).
        from .partial_boundary import nearest_edge
        rgb=np.asarray(image.convert('RGB'))
        try:near=nearest_edge(rgb,reference)
        except ValueError as exc:near={'error':str(exc)}
        try:shape=_matched_region(image,reference)
        except ValueError:
            if not near.get('usable_for_rotation'):raise
            (px,py),(qx,qy)=near['points'];w,h=image.size
            mask=np.zeros((h,w),np.uint8)
            cv2.fillPoly(mask,[np.int32([[px,py],[qx,qy],[w-1,h-1],[w-1,0]] if px<w/2 else [[px,py],[qx,qy],[0,h-1],[0,0]])],255)
            shape=shape_from_mask(mask);shape.update(method='nearest_edge_only',clipped=True,clipped_sides=['top','bottom'])
        if near.get('usable_for_rotation'):
            if shape.get('visible_boundary'):shape['region_boundary']=shape['visible_boundary']
            shape['visible_boundary']=near
        else:shape['nearest_edge_rejected']=near
        return shape
    return _matched_region(image,reference)


def _matched_region(image,reference):
    located=_located_shape(image,reference)
    from .partial_boundary import clipped_sides
    located['clipped_sides']=clipped_sides(located['box_pixels'],image.width,image.height)
    located['clipped']=bool(located['clipped_sides'])
    if reference.get('complete_outline'):
        from .outline_refinement import refine_outline
        return refine_outline(image,reference,located)
    return located
