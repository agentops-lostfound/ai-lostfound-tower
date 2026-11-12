"""Top-view detector dataset (v0.2.54): auto-labelled capture, copy-paste synthesis, YOLO export.

The scene is a fixed camera over a single-colour green foam board, so every non-foam
blob inside the ArUco board is an object. The user puts ONE category on the board per
capture session and moves the items around; each stable frame is saved with its blobs
labelled as that category. '_empty' sessions record the bare board for synthesis.
"""
import json
import math
import random
import shutil
import threading
import time
import cv2
import numpy as np
from PIL import Image
from .config import DATA

ROOT=DATA/'detector_dataset'
EMPTY='_empty'
MIN_AREA=300           # px at full resolution; smaller blobs are noise
FOAM_V_MIN=110         # dark objects pick up a green cast; lit foam is V>=110 (2026-11-12)
FOAM_S_MIN=60          # silver USB reflects the foam at S 32-58; foam itself is S>=72 (2026-11-12)
MARKER_RADIUS=60


def board_polygon(image):
    from .coordinates import geometry
    _,points,_=geometry(image)
    return np.asarray(points,np.float32)


def object_mask(rgb,polygon):
    h,w=rgb.shape[:2]
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    foam=(hsv[:,:,0]>=35)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=FOAM_S_MIN)&(hsv[:,:,2]>=FOAM_V_MIN)
    board=np.zeros((h,w),np.uint8)
    cv2.fillConvexPoly(board,np.rint(cv2.convexHull(polygon)).astype(np.int32),1)
    for p in polygon:cv2.circle(board,(int(p[0]),int(p[1])),MARKER_RADIUS,0,-1)
    mask=((~foam)&(board>0)).astype(np.uint8)*255
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
    return mask,board


_STATIC={'key':None,'mask':None}


def static_mask(shape):
    """Non-foam things that are part of the bare board (sticker, marker rims), from '_empty' captures."""
    files=sorted((ROOT/'raw').glob('*/*.json')) if (ROOT/'raw').exists() else []
    empties=[f.with_suffix('.jpg') for f in files if json.loads(f.read_text(encoding='utf-8')).get('class_id')==EMPTY]
    key=(tuple(str(e) for e in empties),shape)
    if _STATIC['key']!=key:
        union=np.zeros(shape,np.uint8)
        for path in empties:
            im=Image.open(path)
            if im.size!=(shape[1],shape[0]):continue
            try:m,_=object_mask(np.asarray(im.convert('RGB')),board_polygon(im))
            except ValueError:continue
            union|=m
        _STATIC.update(key=key,mask=cv2.dilate(union,np.ones((9,9),np.uint8)))
    return _STATIC['mask']


def auto_boxes(image):
    """Blobs on the board -> [(x,y,w,h)], or raise ValueError when the frame is unusable."""
    rgb=np.asarray(image.convert('RGB'))
    polygon=board_polygon(image)
    mask,board=object_mask(rgb,polygon)
    mask[static_mask(mask.shape)>0]=0
    edge=board-cv2.erode(board,np.ones((15,15),np.uint8))
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    boxes=[];blobs=[]
    for i in range(1,n):
        x,y,w,h,area=stats[i]
        if area<MIN_AREA:continue
        if (edge[labels==i]>0).any():raise ValueError('판 가장자리에 걸친 물체(손 등)가 있습니다')
        boxes.append([int(x),int(y),int(w),int(h)]);blobs.append((labels==i))
    return boxes,blobs,rgb


def _gray_small(image):
    return cv2.resize(cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY),(160,90)).astype(np.float32)


class Capture:
    def __init__(self,engine):
        self.engine=engine;self.lock=threading.Lock();self.thread=None;self.stop_event=threading.Event()
        self.info={'running':False,'class_id':None,'session':None,'saved':0,'skipped':{},'message':'대기','last':None}

    def status(self):
        with self.lock:info=json.loads(json.dumps(self.info))
        info['counts']=counts()
        return info

    def start(self,class_id,interval=1.0):
        with self.lock:
            if self.info['running']:raise ValueError('이미 수집 중입니다. 먼저 정지하세요.')
            session=time.strftime('%Y%m%d-%H%M%S')+'-'+class_id
            self.info.update(running=True,class_id=class_id,session=session,saved=0,skipped={},message='수집 시작',last=None)
        self.stop_event.clear()
        self.thread=threading.Thread(target=self._loop,args=(class_id,session,interval),daemon=True);self.thread.start()
        return self.status()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
        with self.lock:self.info.update(running=False,message='정지')
        return self.status()

    def _skip(self,reason):
        with self.lock:
            self.info['skipped'][reason]=self.info['skipped'].get(reason,0)+1;self.info['message']='건너뜀 · '+reason

    def _loop(self,class_id,session,interval):
        folder=ROOT/'raw'/session;folder.mkdir(parents=True,exist_ok=True)
        cut_dir=ROOT/'cutouts'/class_id;cut_dir.mkdir(parents=True,exist_ok=True)
        previous=None;last_saved=None;last_time=0.
        while not self.stop_event.wait(interval):
            try:
                image,seq,ts=self.engine.cameras['top'].snapshot()
                if time.time()-ts>1:self._skip('오래된 프레임');continue
                small=_gray_small(image)
                stable=previous is not None and float(np.abs(small-previous).mean())<3.0
                previous=small
                if not stable:self._skip('움직이는 중');continue
                # Bare-board backgrounds differ only by light/shadow/block layout, so a much
                # smaller change counts as new (v0.2.56); at most one save per 3 s.
                same=0.8 if class_id==EMPTY else 3.0
                if last_saved is not None and float(np.abs(small-last_saved).mean())<same:self._skip('이전 저장과 같은 장면');continue
                if class_id==EMPTY and time.time()-last_time<3:self._skip('빈 판 저장 간격 3초');continue
                boxes,blobs,rgb=auto_boxes(image)
                if class_id==EMPTY and boxes:self._skip('빈 판 수집인데 물체가 보임');continue
                if class_id!=EMPTY and not boxes:self._skip('물체 없음');continue
                n=len(list(folder.glob('*.jpg')))
                name='%04d'%n;image.save(folder/(name+'.jpg'),quality=95)
                (folder/(name+'.json')).write_text(json.dumps({'class_id':class_id,'boxes':boxes,'size':list(image.size),
                    'frame_id':seq,'captured':ts},ensure_ascii=False),encoding='utf-8')
                for k,(box,blob) in enumerate(zip(boxes,blobs)):
                    x,y,w,h=box;pad=4
                    x0,y0=max(0,x-pad),max(0,y-pad);x1,y1=min(rgb.shape[1],x+w+pad),min(rgb.shape[0],y+h+pad)
                    alpha=cv2.dilate(blob.astype(np.uint8)*255,np.ones((5,5),np.uint8))[y0:y1,x0:x1]
                    Image.fromarray(np.dstack([rgb[y0:y1,x0:x1],alpha])).save(cut_dir/('%s-%s-%d.png'%(session,name,k)))
                last_saved=small;last_time=time.time()
                with self.lock:
                    self.info['saved']+=1;self.info['message']='저장 %d장 · 박스 %d개'%(self.info['saved'],len(boxes))
                    self.info['last']={'path':str(folder/(name+'.jpg')),'boxes':boxes}
            except ValueError as exc:self._skip(str(exc)[:60])
            except Exception as exc:self._skip('오류 '+type(exc).__name__)


def counts():
    result={}
    for meta in (ROOT/'raw').glob('*/*.json') if (ROOT/'raw').exists() else []:
        try:c=json.loads(meta.read_text(encoding='utf-8'))
        except ValueError:continue
        r=result.setdefault(c['class_id'],{'frames':0,'boxes':0});r['frames']+=1;r['boxes']+=len(c['boxes'])
    return result


def preview(path,boxes):
    im=np.asarray(Image.open(path).convert('RGB')).copy()
    for x,y,w,h in boxes:cv2.rectangle(im,(x,y),(x+w,y+h),(255,60,60),3)
    return Image.fromarray(im)


# ---------------------------------------------------------------- synthesis / export

def _paste(canvas,cut,cx,cy,angle,scale,shadow=None):
    rgba=np.asarray(cut);h,w=rgba.shape[:2]
    M=cv2.getRotationMatrix2D((w/2,h/2),angle,scale)
    cos,sin=abs(M[0,0]),abs(M[0,1]);nw,nh=int(h*sin+w*cos)+2,int(h*cos+w*sin)+2
    M[0,2]+=nw/2-w/2;M[1,2]+=nh/2-h/2
    rot=cv2.warpAffine(rgba,M,(nw,nh),flags=cv2.INTER_LINEAR,borderValue=(0,0,0,0))
    x0,y0=int(cx-nw/2),int(cy-nh/2);H,W=canvas.shape[:2]
    if x0<0 or y0<0 or x0+nw>W or y0+nh>H:return None
    a=(rot[:,:,3:4].astype(np.float32)/255.)
    if shadow:
        # soft contact shadow: blurred alpha, offset, darkens what is underneath
        dx,dy,strength=shadow
        sh=cv2.GaussianBlur(rot[:,:,3],(0,0),3).astype(np.float32)/255.*strength
        M2=np.float32([[1,0,dx],[0,1,dy]]);sh=cv2.warpAffine(sh,M2,(nw,nh))[:,:,None]
        canvas[y0:y0+nh,x0:x0+nw]=(canvas[y0:y0+nh,x0:x0+nw].astype(np.float32)*(1-sh)).astype(np.uint8)
    region=canvas[y0:y0+nh,x0:x0+nw].astype(np.float32)
    canvas[y0:y0+nh,x0:x0+nw]=(region*(1-a)+rot[:,:,:3]*a).astype(np.uint8)
    ys,xs=np.nonzero(rot[:,:,3]>127)
    if not len(xs):return None
    return [x0+int(xs.min()),y0+int(ys.min()),int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1)]


def _photometric(img,rng):
    """Natural lighting variation for a whole synthetic frame (v0.2.57)."""
    x=img.astype(np.float32)/255.
    x=x**rng.uniform(.8,1.25)                                     # gamma
    x=x*rng.uniform(.75,1.2)+rng.uniform(-.04,.04)               # exposure / offset
    x=x*np.float32([rng.uniform(.93,1.07),1.,rng.uniform(.93,1.07)])   # colour temperature
    if rng.random()<.6:                                           # broad soft light/shadow field
        h,w=x.shape[:2];yy,xx=np.mgrid[0:h,0:w].astype(np.float32)
        cx,cy=rng.uniform(0,w),rng.uniform(0,h);r=rng.uniform(.3,.9)*max(w,h)
        field=np.exp(-((xx-cx)**2+(yy-cy)**2)/(2*r*r))
        x=x*(1+rng.uniform(-.25,.2)*field[:,:,None])
    if rng.random()<.3:x=cv2.GaussianBlur(x,(0,0),rng.uniform(.4,1.1))
    x=x+np.random.default_rng(rng.randint(0,1<<30)).normal(0,rng.uniform(0,.015),x.shape).astype(np.float32)
    return (np.clip(x,0,1)*255).astype(np.uint8)


TOP_SIZE=(1280,720)
# Long side in top-view pixels (≈2.36 px/mm) for references photographed by another camera.
TYPICAL_LONG_PX={'phone':350,'wallet':260,'power_bank':320,'hand_cream':300,'lip_balm':160,'usb':100}


def _fill_object(bg):
    """Non-background components (>=20% of the largest), holes filled; None when too small."""
    h,w=bg.shape
    mask=(~bg).astype(np.uint8)*255
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    if n<2:return None
    big=stats[1:,4].max();keep=np.zeros((h,w),np.uint8)
    for i in range(1,n):
        if stats[i,4]>=.2*big:keep[labels==i]=255
    contours,_=cv2.findContours(keep,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    filled=np.zeros((h,w),np.uint8);cv2.drawContours(filled,contours,-1,255,-1)
    return filled if filled.mean()/255.>=.3 else None


def _solidity(mask):
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    hull=cv2.convexHull(np.concatenate(contours))
    return float((mask>0).sum())/max(1.,cv2.contourArea(hull))


def _reference_alpha(rgb):
    """Object mask of a tight registry crop.

    1) foam pixels are background; 2) if the four corners share one colour (pale board under
    other light, desk), pixels of that colour connected to the border are background too, but
    only when the result is one solid shape — otherwise the corners were the object itself
    (crop filled by a tube). Whole crop when nothing sensible remains."""
    h,w=rgb.shape[:2]
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    foam=(hsv[:,:,0]>=35)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=FOAM_S_MIN)&(hsv[:,:,2]>=FOAM_V_MIN)
    full=np.full((h,w),255,np.uint8)
    base=_fill_object(foam)
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB).astype(np.float32);k=max(3,min(h,w)//12)
    corners=np.concatenate([lab[:k,:k].reshape(-1,3),lab[:k,-k:].reshape(-1,3),lab[-k:,:k].reshape(-1,3),lab[-k:,-k:].reshape(-1,3)])
    ref=np.median(corners,0)
    if np.median(np.linalg.norm(corners-ref,axis=1))<8:
        near=(np.linalg.norm(lab-ref,axis=2)<16).astype(np.uint8)
        n,labels=cv2.connectedComponents(near)
        edge=set(np.unique(np.concatenate([labels[0],labels[-1],labels[:,0],labels[:,-1]])))-{0}
        corner=_fill_object(foam|np.isin(labels,list(edge)))
        if corner is not None and _solidity(corner)>=.85:return corner
    return base if base is not None else full


def registry_cutouts(classes,skip=('usb',)):
    """v0.2.66: one RGBA cut-out per registered reference photo -> ROOT/cutouts_registry/<category>.

    Lets categories that were never captured on the board still be synthesised. Crops from a
    non-top-view source are rescaled to a typical top-view size for that category. usb is
    skipped: it has >100 real board cut-outs and some usb references are ARM close-ups."""
    from .config import MEDIA
    out=ROOT/'cutouts_registry'
    if out.exists():shutil.rmtree(out)
    made={}
    for ref in _registry().references():
        cat=ref['category']
        if cat not in classes or cat in skip:continue
        path=MEDIA/ref['image'].replace('/media/','',1)
        if not path.exists():continue
        rgb=np.asarray(Image.open(path).convert('RGB'))
        boxes=path.parent/'boxes.jpg'
        top=False
        if boxes.exists():
            with Image.open(boxes) as b:top=b.size==TOP_SIZE
        if not top:
            s=TYPICAL_LONG_PX.get(cat,200)/float(max(rgb.shape[:2]))
            rgb=cv2.resize(rgb,(max(1,int(rgb.shape[1]*s)),max(1,int(rgb.shape[0]*s))),interpolation=cv2.INTER_AREA)
        alpha=_reference_alpha(rgb)
        folder=out/cat;folder.mkdir(parents=True,exist_ok=True)
        Image.fromarray(np.dstack([rgb,alpha])).save(folder/('%s-%s.png'%(ref['item_id'],ref['id'][:8])))
        made[cat]=made.get(cat,0)+1
    return made


def _registry():
    from .storage import Store
    return Store(DATA/'vision.sqlite3')


def build(classes,synthetic=1500,val_fraction=.15,seed=0):
    """Write ROOT/yolo (images/labels train+val, data.yaml). classes: ordered category ids."""
    rng=random.Random(seed);out=ROOT/'yolo'
    if out.exists():shutil.rmtree(out)
    for split in ['train','val']:
        (out/'images'/split).mkdir(parents=True);(out/'labels'/split).mkdir(parents=True)
    index={c:i for i,c in enumerate(classes)}
    def write(name,image,boxes,split):
        W,H=image.size;image.save(out/'images'/split/(name+'.jpg'),quality=92)
        lines=['%d %.6f %.6f %.6f %.6f'%(index[c],(x+w/2)/W,(y+h/2)/H,w/W,h/H) for c,(x,y,w,h) in boxes]
        (out/'labels'/split/(name+'.txt')).write_text('\n'.join(lines),encoding='utf-8')
    real=0;empties=[];backgrounds=[]
    for meta in sorted((ROOT/'raw').glob('*/*.json')):
        c=json.loads(meta.read_text(encoding='utf-8'));img=meta.with_suffix('.jpg')
        if c['class_id']==EMPTY:empties.append(img);backgrounds.append((img,[]))
        elif c['class_id'] in index:backgrounds.append((img,[(c['class_id'],b) for b in c['boxes']]))
        if c['class_id']!=EMPTY and c['class_id'] not in index:continue
        split='val' if rng.random()<val_fraction else 'train'
        write('real-%s-%s'%(meta.parent.name,meta.stem),Image.open(img).convert('RGB'),[(c['class_id'],b) for b in c['boxes']] if c['class_id']!=EMPTY else [],split);real+=1
    registry=registry_cutouts(classes)
    cuts={c:sorted((ROOT/'cutouts'/c).glob('*.png'))+sorted((ROOT/'cutouts_registry'/c).glob('*.png')) for c in classes}
    cuts={c:v for c,v in cuts.items() if v}
    made=0
    polygons={}
    if backgrounds and cuts:
        for k in range(synthetic):
            # 2/3 bare board, 1/3 a real labelled frame with more objects added
            src,existing=rng.choice([b for b in backgrounds if not b[1]] or backgrounds) if rng.random()<.67 else rng.choice(backgrounds)
            bg=Image.open(src).convert('RGB');canvas=np.asarray(bg).copy()
            if src not in polygons:polygons[src]=board_polygon(bg)
            polygon=polygons[src];hull=cv2.convexHull(polygon).astype(np.float32)
            x0,y0=polygon.min(0);x1,y1=polygon.max(0);placed=list(existing)
            for _ in range(rng.randint(1,7)):
                c=rng.choice(list(cuts));cut=Image.open(rng.choice(cuts[c])).convert('RGBA')
                cut=Image.fromarray(np.dstack([np.clip(np.asarray(cut)[:,:,:3].astype(np.float32)*rng.uniform(.85,1.15),0,255).astype(np.uint8),np.asarray(cut)[:,:,3]]))
                for _ in range(20):
                    cx,cy=rng.uniform(x0+60,x1-60),rng.uniform(y0+60,y1-60)
                    if cv2.pointPolygonTest(hull,(cx,cy),True)<70:continue
                    shadow=(rng.uniform(-4,4),rng.uniform(1,6),rng.uniform(.15,.4)) if rng.random()<.8 else None
                    trial=canvas.copy();box=_paste(trial,cut,cx,cy,rng.uniform(0,360),rng.uniform(.9,1.1),shadow)
                    if box is None:continue
                    if any(_overlap(box,b)>.05 for _,b in placed):continue   # v0.2.66: share of the smaller box (IoU let a big paste hide a USB)
                    canvas=trial;placed.append((c,box));break
            if len(placed)==len(existing):continue
            write('syn-%05d'%k,Image.fromarray(_photometric(canvas,rng)),placed,'val' if rng.random()<val_fraction else 'train');made+=1
    (out/'data.yaml').write_text('path: %s\ntrain: images/train\nval: images/val\nnames:\n%s'%(out.as_posix(),''.join('  %d: %s\n'%(i,c) for i,c in enumerate(classes))),encoding='utf-8')
    summary={'real_frames':real,'synthetic':made,'empty_backgrounds':len(empties),'cutouts':{c:len(v) for c,v in cuts.items()},'registry_cutouts':registry,'classes':classes,'path':str(out)}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


def _overlap(a,b):
    ax,ay,aw,ah=a;bx,by,bw,bh=b
    ix=max(0,min(ax+aw,bx+bw)-max(ax,bx));iy=max(0,min(ay+ah,by+bh)-max(ay,by))
    return ix*iy/float(max(1,min(aw*ah,bw*bh)))


def _iou(a,b):
    ax,ay,aw,ah=a;bx,by,bw,bh=b
    ix=max(0,min(ax+aw,bx+bw)-max(ax,bx));iy=max(0,min(ay+ah,by+bh)-max(ay,by))
    inter=ix*iy;return inter/float(aw*ah+bw*bh-inter) if inter else 0.


def relabel():
    """Recompute boxes and cutouts of every saved capture with the current mask rules."""
    def cut_out(rgb,box,blob):
        x,y,w,h=box;pad=4
        x0,y0=max(0,x-pad),max(0,y-pad);x1,y1=min(rgb.shape[1],x+w+pad),min(rgb.shape[0],y+h+pad)
        alpha=cv2.dilate(blob.astype(np.uint8)*255,np.ones((5,5),np.uint8))[y0:y1,x0:x1]
        return Image.fromarray(np.dstack([rgb[y0:y1,x0:x1],alpha]))
    if (ROOT/'cutouts').exists():shutil.rmtree(ROOT/'cutouts')
    report={'frames':0,'boxes':0,'rejected':[]}
    for meta in sorted((ROOT/'raw').glob('*/*.json')):
        c=json.loads(meta.read_text(encoding='utf-8'))
        if c['class_id']==EMPTY:continue
        try:boxes,blobs,rgb=auto_boxes(Image.open(meta.with_suffix('.jpg')))
        except ValueError as exc:report['rejected'].append([str(meta),str(exc)]);continue
        c['boxes']=boxes;c['relabelled']=time.time();meta.write_text(json.dumps(c,ensure_ascii=False),encoding='utf-8')
        out=ROOT/'cutouts'/c['class_id'];out.mkdir(parents=True,exist_ok=True)
        for k,(box,blob) in enumerate(zip(boxes,blobs)):cut_out(rgb,box,blob).save(out/('%s-%s-%d.png'%(meta.parent.name,meta.stem,k)))
        report['frames']+=1;report['boxes']+=len(boxes)
    return report
