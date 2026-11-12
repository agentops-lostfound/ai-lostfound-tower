"""CPU display-only tracking. Never feeds annotations back into model inputs."""
import threading
import time

import cv2
import numpy as np


class LiveOverlay:
    def __init__(self, max_age=30):
        self.lock=threading.RLock()
        self.gray=None
        self.tracks=[]
        self.max_age=max_age
        self.generation=0
        self.show_candidates=False

    @staticmethod
    def grayscale(image):
        return cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)

    def _advance(self, track, previous, current):
        old=track['points']
        new,status,errors=cv2.calcOpticalFlowPyrLK(previous,current,old,None,winSize=(31,31),maxLevel=3)
        if new is None: return False
        reverse,back,_=cv2.calcOpticalFlowPyrLK(current,previous,new,None,winSize=(31,31),maxLevel=3)
        if reverse is None: return False
        good=(status.ravel()==1)&(back.ravel()==1)&(np.linalg.norm(reverse-old,axis=2).ravel()<1.2)&(errors.ravel()<35)
        if int(good.sum())<4: return False
        a,b=old[good].reshape(-1,2),new[good].reshape(-1,2)
        transform,inliers=cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2.5)
        if transform is None or inliers is None or int(inliers.sum())<4: return False
        scale=float(np.linalg.norm(transform[0,:2]))
        if not .7<scale<1.4: return False
        corners=cv2.transform(track['corners'],transform.astype(np.float32))
        box=np.array([corners[:,:,0].min(),corners[:,:,1].min(),corners[:,:,0].max(),corners[:,:,1].max()])
        height,width=current.shape
        if box[2]-box[0]<12 or box[3]-box[1]<12 or box[0]<-20 or box[1]<-20 or box[2]>width+20 or box[3]>height+20: return False
        track['points']=new[good][inliers.ravel().astype(bool)].reshape(-1,1,2)
        track['corners']=corners;track['bbox']=box.tolist()
        return True

    def set_detections(self, reference, frame_id, items, previews=()):
        reference_gray=self.grayscale(reference)
        with self.lock:
            self.generation+=1
            tracks=[]
            for obj in list(items)[:8]+list(previews)[:2]:
                if obj.get('quality')=='rejected': continue
                x1,y1,x2,y2=map(int,obj['bbox'])
                mask=np.zeros_like(reference_gray)
                mask[max(0,y1):y2,max(0,x1):x2]=255
                points=cv2.goodFeaturesToTrack(reference_gray,maxCorners=60,qualityLevel=.01,minDistance=4,mask=mask)
                if points is None or len(points)<4: continue
                track={'id':f'{self.generation}_{len(tracks)}','category':obj['category'],'bbox':list(obj['bbox']),
                    'corners':np.array([[[x1,y1]],[[x2,y1]],[[x2,y2]],[[x1,y2]]],dtype=np.float32),
                    'points':points,'quality':obj.get('quality','detected'),'frame_id':frame_id,
                    'created':time.time(),'preview':bool(obj.get('preview')),'index':obj['index']}
                if self.gray is not None:
                    if self.gray.shape!=reference_gray.shape or not self._advance(track,reference_gray,self.gray): continue
                tracks.append(track)
            self.tracks=tracks
            if self.gray is None: self.gray=reference_gray

    def update(self, image):
        gray=self.grayscale(image)
        with self.lock:
            if self.gray is not None and self.gray.shape==gray.shape:
                self.tracks=[t for t in self.tracks if time.time()-t['created']<(120 if t.get('target') else self.max_age) and self._advance(t,self.gray,gray)]
            else: self.tracks=[]
            self.gray=gray

    def refine(self, frame_id, items):
        by_index={o['index']:o for o in items}
        with self.lock:
            for track in self.tracks:
                if track['frame_id']==frame_id and track['index'] in by_index and not track['preview']:
                    obj=by_index[track['index']]
                    track['quality']=obj['quality'];track['category']=obj['category']

    def visible(self):
        with self.lock:
            return [dict({k:t[k] for k in ('id','category','bbox','quality','frame_id','created','preview')},target=t.get('target')) for t in self.tracks
                    if time.time()-t['created']<(120 if t.get('target') else self.max_age) and (self.show_candidates or not t['preview'] and t['quality']!='rejected')]

    def draw(self, image):
        tracks=self.visible()
        if not tracks: return image
        pixels=np.asarray(image.convert('RGB')).copy()
        for track in tracks:
            x1,y1,x2,y2=map(int,track['bbox'])
            uncertain=track['preview'] or track['quality'] in ('review','rejected')
            color=(80,190,255) if track.get('target') else (235,178,98) if uncertain else (188,245,121)
            if uncertain:
                for x in range(x1,x2,14):
                    cv2.line(pixels,(x,y1),(min(x+8,x2),y1),color,2)
                    cv2.line(pixels,(x,y2),(min(x+8,x2),y2),color,2)
                for y in range(y1,y2,14):
                    cv2.line(pixels,(x1,y),(x1,min(y+8,y2)),color,2)
                    cv2.line(pixels,(x2,y),(x2,min(y+8,y2)),color,2)
            else: cv2.rectangle(pixels,(x1,y1),(x2,y2),color,2)
            mode='CANDIDATE' if uncertain else 'TRACKING' if time.time()-track['created']>1 else 'DETECTED'
            label=track['category']+('?' if uncertain else '')+' | '+mode
            if track.get('target'): label='TARGET '+track['target']+' | CANDIDATE'
            size=cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,.43,1)[0]
            top=max(0,y1-24)
            cv2.rectangle(pixels,(x1,top),(min(pixels.shape[1]-1,x1+size[0]+12),top+22),(23,33,25),-1)
            cv2.putText(pixels,label,(x1+5,top+15),cv2.FONT_HERSHEY_SIMPLEX,.43,color,1,cv2.LINE_AA)
        from PIL import Image
        return Image.fromarray(pixels)

    def mark_target(self, frame_id, index, target_id):
        with self.lock:
            for track in self.tracks:
                track.pop('target',None)
                if track['frame_id']==frame_id and track['index']==index and not track['preview']:
                    track['target']=target_id
                    # Start the screenshot window when matching finishes,
                    # rather than spending it during model inference.
                    track['created']=time.time()
