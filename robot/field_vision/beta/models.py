import contextlib
import copy
import functools
import gc
import hashlib
import io
import json
import re
import time

import numpy as np
from PIL import Image

from .config import CLASSES, MODEL_IDS, DETECTION_PROMPTS


def pixel_hash(image):
    return hashlib.sha256(str(image.size).encode()+image.convert('RGB').tobytes()).hexdigest()


def clamp_box(box, size):
    w, h = size
    x1, y1, x2, y2 = box
    return [max(0, min(w-1, int(x1))), max(0, min(h-1, int(y1))), max(1, min(w, int(x2))), max(1, min(h, int(y2)))]


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2-x1)*max(0, y2-y1)
    area = max(0, a[2]-a[0])*max(0, a[3]-a[1])+max(0, b[2]-b[0])*max(0, b[3]-b[1])-inter
    return inter/max(area, 1)


def detection_queries():
    pairs=[(category,prompt) for category,prompts in DETECTION_PROMPTS.items() for prompt in prompts]
    return [p for _,p in pairs],[c for c,_ in pairs]


def containment(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    smallest=min(max(0,a[2]-a[0])*max(0,a[3]-a[1]),max(0,b[2]-b[0])*max(0,b[3]-b[1]))
    return intersection/max(smallest,1)


def duplicate_detection(box,category,kept):
    return any(iou(box,o['bbox'])>.65 or category==o['category'] and containment(box,o['bbox'])>.9 for o in kept)


def trained_classes():
    """Categories the board YOLO actually learned (meta 'trained_classes', v0.2.66); [] if unknown."""
    from pathlib import Path
    folder=Path(__file__).resolve().parent.parent/'models'/'detector'
    if not (folder/'best.pt').exists():return []
    try:return list(json.loads((folder/'meta.json').read_text(encoding='utf-8')).get('trained_classes') or [])
    except (OSError,ValueError):return []


def trained_alone():
    """v0.2.66: one authority on the top view. When the board YOLO learned every enabled
    category it alone finds objects and decides their category; OWL is not run and the
    category is never re-voted by SigLIP zero-shot or registry photos."""
    learned=set(trained_classes())
    return bool(learned) and bool(CLASSES) and set(CLASSES)<=learned


def trained_status():
    """Card text for our board-trained YOLO (v0.2.61)."""
    from pathlib import Path
    folder=Path(__file__).resolve().parent.parent/'models'/'detector'
    if not (folder/'best.pt').exists():
        return {'status':'idle','message':'학습 모델 없음 · 설정 → 검출 데이터·학습'}
    try:names=list(json.loads((folder/'meta.json').read_text(encoding='utf-8')).get('names',{}).values())
    except (OSError,ValueError):names=[]
    learned=trained_classes()
    if trained_alone():return {'status':'idle','message':'학습 모델 단독 판정 · 탑뷰 검출·품목 모두 YOLO · '+', '.join(learned)}
    if learned:return {'status':'idle','message':'학습 모델 있음 · 탑뷰 우선 검출(빠진 품목은 OWL) · 학습: '+', '.join(learned)+' · 미학습: '+', '.join(c for c in CLASSES if c not in learned)}
    return {'status':'idle','message':'학습 모델 있음 · 탑뷰 우선 검출'+(' · '+', '.join(names) if names else '')}


def retry_gpu(fn):
    @functools.wraps(fn)
    def wrapped(self,*args,**kwargs):
        import torch
        resident=self.resident_enabled
        try:
            return fn(self,*args,**kwargs)
        except torch.cuda.OutOfMemoryError:
            if not resident:raise
            self.resident_enabled=False
            self.release()
            self.notify('gpu','fallback','GPU 메모리 부족 · 상주 해제 후 순차 방식으로 재시도합니다.')
        # Retry after the exception/traceback and inference tensors have unwound.
        gc.collect();torch.cuda.empty_cache()
        self.check()
        return fn(self,*args,**kwargs)
    return wrapped


class Models:
    def __init__(self, notify, cancel):
        self.notify, self.cancel = notify, cancel
        self.resident_enabled=True
        self._resident={}

    def check(self):
        if self.cancel.is_set():
            raise InterruptedError('사용자가 작업 중단을 요청했습니다.')

    def release(self):
        import torch
        for key,(model,processor) in self._resident.items():
            model.to('meta')
            self.notify(key,'idle','GPU 상주 해제')
        self._resident.clear()
        gc.collect();torch.cuda.empty_cache()

    @contextlib.contextmanager
    def use(self, key):
        self.check()
        import torch
        from transformers import AutoProcessor, AutoModel, Owlv2ForObjectDetection, Qwen3VLForConditionalGeneration
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA GPU를 사용할 수 없습니다.')
        torch.set_num_threads(8)
        if key=='qwen':self.release()
        started=time.time();model=None;keep=self.resident_enabled and key in ('owl','sig')
        try:
            if key in self._resident:
                model,processor=self._resident[key]
                self.notify(key,'running','GPU 상주 모델 재사용',load_seconds=0)
            else:
                self.notify(key,'loading','모델을 GPU로 로딩합니다.')
                processor=AutoProcessor.from_pretrained(MODEL_IDS[key],local_files_only=True,use_fast=True)
                cls={'owl':Owlv2ForObjectDetection,'sig':AutoModel,'qwen':Qwen3VLForConditionalGeneration}[key]
                model=cls.from_pretrained(MODEL_IDS[key],local_files_only=True,low_cpu_mem_usage=True,
                    dtype=torch.float16 if key=='qwen' else torch.float32,
                    attn_implementation='sdpa' if key=='qwen' else 'eager').eval().to('cuda')
                torch.cuda.synchronize()
                self.notify(key,'running',f'로딩 완료 · {time.time()-started:.2f}초',load_seconds=time.time()-started)
                if keep:self._resident[key]=(model,processor)
            self.check()
            yield model,processor
        except BaseException:
            keep=False
            self._resident.pop(key,None)
            raise
        finally:
            if keep and model is not None:
                self.notify(key,'idle','GPU 상주 대기',elapsed=time.time()-started,
                    allocated_mib=torch.cuda.memory_allocated()/2**20)
            else:
                if model is not None:model.to('meta')
                gc.collect();torch.cuda.empty_cache()
                self.notify(key,'idle','GPU 해제 완료',elapsed=time.time()-started,
                    allocated_mib=torch.cuda.memory_allocated()/2**20)

    def trained_detect(self,image,conf=.35):
        """v0.2.58: our own top-view YOLO (models/detector/best.pt) when it exists.

        Trained on this board (beta/detector_dataset.py); OWL still runs for anything it
        did not find. Reloaded automatically after a retrain (file mtime)."""
        from pathlib import Path
        path=Path(__file__).resolve().parent.parent/'models'/'detector'/'best.pt'
        if not path.exists():return []
        stamp=path.stat().st_mtime
        if getattr(self,'_yolo_stamp',None)!=stamp:
            from ultralytics import YOLO
            self.notify('yolo','loading','학습 모델 로딩')
            self._yolo=YOLO(str(path));self._yolo_stamp=stamp
        started=time.time()
        result=self._yolo.predict(image,conf=conf,imgsz=960,device=0,verbose=False)[0]
        names=result.names;items=[]
        for box,score,cls in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
            category=names[int(cls)]
            if category not in CLASSES:continue
            box=clamp_box(box,image.size)
            if min(box[2]-box[0],box[3]-box[1])<8:continue
            items.append(dict(index=len(items),category=category,detector_category=category,detector_prompt='trained_yolo',
                score=float(score),bbox=box,center=[(box[0]+box[2])/2,(box[1]+box[3])/2],quality='detected',reasons=[]))
        counts={}
        for o in items:counts[o['category']]=counts.get(o['category'],0)+1
        self.notify('yolo','idle','마지막 검출 %d개 · %.2f초%s'%(len(items),time.time()-started,(' · '+', '.join('%s %d'%kv for kv in counts.items())) if counts else ''))
        return items

    @retry_gpu
    def detect(self, image, threshold, roi=None, trained=False):
        import torch
        self.preview_candidates=[]
        trained_items=self.trained_detect(image) if trained else []
        if trained and trained_alone():return trained_items
        prompts,prompt_categories=detection_queries()
        if not prompts:raise ValueError('활성화된 카테고리가 없습니다. 설정 → 카테고리에서 추가하거나 켜세요.')
        with self.use('owl') as (model, proc), torch.inference_mode():
            data = proc(text=[prompts], images=image, return_tensors='pt').to('cuda')
            output = model(**data)
            result = proc.post_process_grounded_object_detection(output, threshold=min(.03,threshold),
                target_sizes=torch.tensor([[image.height, image.width]], device='cuda'))[0]
            raw = [(float(s), int(c), b.cpu().tolist()) for s,c,b in zip(result['scores'], result['labels'], result['boxes'])]
            strong=[row for row in raw if row[0]>=threshold]
            if not strong:
                probabilities=output.logits.sigmoid()
                best=float(probabilities.max())
                label=int(probabilities.reshape(-1,probabilities.shape[-1]).max(dim=0).values.argmax())
                self.notify('owl','running',f'검출 보류 · 최고 점수 {best:.3f} / 임계값 {threshold:.3f} · 문구: {prompts[label]}')
            items = list(trained_items)
            for score, label, box in sorted(strong, reverse=True, key=lambda row: row[0]):
                box = clamp_box(box, image.size)
                if any(iou(box,o['bbox'])>.45 or containment(box,o['bbox'])>.85 for o in trained_items):continue
                # One physical region should not become four class-prompt candidates.
                if duplicate_detection(box,prompt_categories[label],items):
                    continue
                w, h = box[2]-box[0], box[3]-box[1]
                reasons = []
                if min(w,h) < 16: reasons.append('너무 작은 박스')
                if w*h/(image.width*image.height) > .9: reasons.append('장면 대부분을 포함한 박스')
                center = [(box[0]+box[2])/2, (box[1]+box[3])/2]
                if roi and not (roi[0]<=center[0]/image.width<=roi[2] and roi[1]<=center[1]/image.height<=roi[3]):
                    reasons.append('ROI 밖')
                items.append(dict(index=len(items), category=prompt_categories[label], detector_category=prompt_categories[label], detector_prompt=prompts[label],
                    score=score, bbox=box, center=center, quality='review' if reasons else 'detected', reasons=reasons))
                if len(items) >= 12: break
            for score,label,box in sorted(raw,reverse=True,key=lambda r:r[0]):
                if score>=threshold or score<max(.03,threshold*.35): continue
                box=clamp_box(box,image.size)
                if min(box[2]-box[0],box[3]-box[1])<16 or (box[2]-box[0])*(box[3]-box[1])>image.width*image.height*.85: continue
                if any(iou(box,o['bbox'])>.45 or containment(box,o['bbox'])>.85 for o in items+self.preview_candidates): continue
                cx,cy=(box[0]+box[2])/2/image.width,(box[1]+box[3])/2/image.height
                if roi and not (roi[0]<=cx<=roi[2] and roi[1]<=cy<=roi[3]): continue
                self.preview_candidates.append(dict(index=100+len(self.preview_candidates),category=prompt_categories[label],
                    bbox=box,score=score,quality='review',preview=True,reasons=['임계값 미달 · 표시 전용 후보']))
                if len(self.preview_candidates)>=2: break
            return items

    @retry_gpu
    def embed_items(self,image,items,callback):
        # Do not publish partial embeddings/callbacks before an OOM retry succeeds.
        working=copy.deepcopy(items);pending=[]
        self._embed_items(image,working,lambda obj,crop:pending.append((obj,crop)))
        items[:]=working
        for obj,crop in pending:callback(obj,crop)

    def _embed_items(self, image, items, callback):
        import torch
        negatives = ['a mug', 'a human hand', 'an empty table', 'product packaging', 'an unrelated object']
        if not CLASSES:raise ValueError('활성화된 카테고리가 없습니다.')
        labels = ['a photo of '+v for v in CLASSES.values()] + negatives
        with self.use('sig') as (model, proc), torch.inference_mode():
            for obj in items:
                self.check()
                if obj['reasons']:
                    continue
                crop = image.crop(obj['bbox'])
                if float(np.asarray(crop).std()) < 3:
                    obj.update(quality='rejected', reasons=['거의 단색인 crop']); continue
                data = proc(images=crop, text=labels, padding='max_length', return_tensors='pt').to('cuda')
                output = model(**data)
                logits = output.logits_per_image[0].float().cpu().numpy()
                order = np.argsort(logits)[::-1]
                top = int(order[0]); margin = float(logits[top]-logits[order[1]])
                obj['classification'] = {'top_logit': float(logits[top]), 'margin': margin,
                    'label': labels[top], 'calibrated': False}
                if obj.get('detector_prompt')=='trained_yolo' and obj.get('category') in CLASSES:
                    # v0.2.60: our board-trained YOLO decides the category; zero-shot SigLIP
                    # turned its 'usb' boxes into phone/wallet (job e4ffcbf2). Its label is
                    # kept as a note only, and the crop is never rejected as 'unrelated'.
                    obj['classification']['overridden_by']='trained_yolo'
                else:
                    if top >= len(CLASSES):
                        obj.update(quality='rejected', reasons=['비대상 crop: '+labels[top]]); continue
                    obj['category'] = list(CLASSES)[top]
                    if margin < .5:
                        obj.update(quality='review', reasons=['품목 판별 근거가 약함']); continue
                embedding = output.image_embeds[0].float().cpu().numpy()
                embedding /= max(float(np.linalg.norm(embedding)), 1e-8)
                obj.update(quality='accepted', _embedding=embedding.tolist(), _hash=pixel_hash(crop), embedding_dim=len(embedding))
                callback(obj, crop)

    def features(self, image, items, limit):
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        cancel = self.cancel
        class StopRequested(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return torch.full((input_ids.shape[0],), cancel.is_set(), device=input_ids.device, dtype=torch.bool)
        accepted = [o for o in items if o['quality']=='accepted']
        if not accepted: return
        with self.use('qwen') as (model, proc), torch.inference_mode():
            for n, obj in enumerate(accepted):
                self.check()
                if n >= limit:
                    obj['feature_status'] = 'limit_skipped'; continue
                x1,y1,x2,y2 = obj['bbox']; dx=(x2-x1)*.08; dy=(y2-y1)*.08
                context = clamp_box([x1-dx,y1-dy,x2+dx,y2+dy], image.size)
                obj['context_bbox'] = context
                crop = image.crop(context); crop.thumbnail((448,448))
                prompt = ('Describe only the central object. Return JSON only, with string fields body_color, pattern_colors, colors, shape, material, visible_text, distinctive_marks. '
                          'body_color is the main underlying surface color, excluding printed flowers, characters, white label, cap, and background. '
                          'body_color must be one of: blue, pink, red, green, yellow, orange, purple, white, black, gray, brown, beige, unknown. '
                          'Use unknown if no single main surface color is clear. pattern_colors describes only printed decorations. '
                          'Use short English phrases. Use unknown for uncertain or invisible properties, especially material. Never guess a brand. No explanation.')
                messages=[{'role':'user','content':[{'type':'image','image':crop},{'type':'text','text':prompt}]}]
                data=proc.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors='pt').to('cuda')
                started=time.time()
                output=model.generate(**data,max_new_tokens=192,do_sample=False,stopping_criteria=StoppingCriteriaList([StopRequested()]))
                self.check()
                raw=proc.batch_decode(output[:,data['input_ids'].shape[-1]:],skip_special_tokens=True)[0]
                obj['feature_raw']=raw; obj['feature_seconds']=time.time()-started
                try:
                    cleaned=re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip()).strip()
                    parsed=json.loads(cleaned)
                    keys=['body_color','pattern_colors','colors','shape','material','visible_text','distinctive_marks']
                    if not isinstance(parsed,dict) or any(not isinstance(parsed.get(k),str) for k in keys):
                        raise ValueError('JSON 스키마 불일치')
                    obj['features']={k:parsed[k][:250] for k in keys}
                    obj['feature_status']='parsed_unverified'
                except (ValueError,TypeError):
                    obj['features']={}; obj['feature_status']='invalid_json'
                self.notify('qwen','running',f'물체 #{obj["index"]+1} 특징 처리 · {obj["feature_status"]} · {obj["feature_seconds"]:.2f}초')

    @retry_gpu
    def query_embedding(self, image=None, text=None):
        import torch
        with self.use('sig') as (model, proc), torch.inference_mode():
            if image is not None:
                data=proc(images=image,return_tensors='pt').to('cuda')
                vector=model.get_image_features(**data)
            else:
                data=proc(text=[text],padding='max_length',return_tensors='pt').to('cuda')
                vector=model.get_text_features(**data)
            vector=vector[0].float().cpu().numpy()
            return (vector/max(float(np.linalg.norm(vector)),1e-8)).tolist()
