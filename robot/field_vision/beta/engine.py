import re
import copy
import json
import queue
import threading
import time
import traceback
import uuid
from collections import deque

from PIL import ImageDraw
import psutil

from .cameras import Camera
from .config import DATA, MEDIA, SETTINGS, DEFAULTS, CLASSES, MODEL_IDS, CATEGORY_CATALOG
from .models import Models, iou
from .storage import Store, public
from .matching import text_features, name_terms, query_category


class Engine:
    def __init__(self):
        DATA.mkdir(exist_ok=True); MEDIA.mkdir(exist_ok=True)
        self.lock=threading.RLock()
        self.logs=deque(maxlen=500);self.log_seq=0
        self.settings=copy.deepcopy(DEFAULTS)
        if SETTINGS.exists():
            self.settings.update(json.loads(SETTINGS.read_text(encoding='utf-8')))
        self.store=Store(DATA/'vision.sqlite3')
        self.stop=threading.Event();self.cancel=threading.Event()
        self.queue=queue.Queue(maxsize=2)
        self.generation=0
        self.jobs=deque(maxlen=30);self.active=None
        self.monitor=False;self.monitor_camera='arm';self.last_monitor=0
        self.models_state={k:{'status':'idle','message':'비상주 · 호출 대기'} for k in MODEL_IDS}
        from .models import trained_status
        self.models_state['yolo']=trained_status()
        self.models=Models(self.model_event,self.cancel)
        self.cameras={};self.latest={};self.confidences={};self.tracks={};self.track_seq=0;self.auto_count=0
        self.metrics={'ram_used_gib':0,'gpu_used_mib':None,'gpu_total_mib':6144,'gpu_utilization':None}
        self.worker=threading.Thread(target=self.run,daemon=True,name='single-gpu-worker')
        self.meter=threading.Thread(target=self.measure,daemon=True,name='system-meter')

    def start(self):
        for key, config in self.settings['cameras'].items():
            self.cameras[key]=Camera(key,config,self.log);self.cameras[key].start()
            self.cameras[key].overlay.show_candidates=self.settings.get('show_candidates',False)
        self.worker.start();self.meter.start()
        self.log('info','system','Vision Beta 준비 · OWL/Sig GPU 상주 · Qwen 전환 시 해제')

    def close(self):
        self.stop.set();self.cancel.set();self.monitor=False
        for camera in self.cameras.values(): camera.close()
        self.worker.join(timeout=15)

    def log(self, level, stage, message, **extra):
        with self.lock:
            self.log_seq+=1
            row={'seq':self.log_seq,'time':time.time(),'level':level,'stage':stage,'message':message,**extra}
            self.logs.append(row)
            with (DATA/'events.jsonl').open('a',encoding='utf-8') as out:
                out.write(json.dumps(row,ensure_ascii=False)+'\n')

    def model_event(self, key, status, message, **extra):
        with self.lock:
            self.models_state[key]={'status':status,'message':message,'since':time.time(),**extra}
        self.log('info',key,message,status=status)

    def measure(self):
        nvml=None
        try:
            import pynvml
            pynvml.nvmlInit();nvml=pynvml;handle=nvml.nvmlDeviceGetHandleByIndex(0)
        except Exception: pass
        while not self.stop.is_set():
            ram=psutil.virtual_memory()
            values={'ram_used_gib':round(ram.used/2**30,2),'ram_total_gib':round(ram.total/2**30,2),'cpu_percent':psutil.cpu_percent()}
            if nvml:
                try:
                    memory=nvml.nvmlDeviceGetMemoryInfo(handle)
                    values.update(gpu_used_mib=round(memory.used/2**20),gpu_total_mib=round(memory.total/2**20),gpu_utilization=nvml.nvmlDeviceGetUtilizationRates(handle).gpu)
                except Exception: pass
            with self.lock: self.metrics.update(values)
            self.stop.wait(1)

    def state(self):
        with self.lock:
            return {'version':'0.1.0-beta','time':time.time(),'monitor':self.monitor,'monitor_camera':self.monitor_camera,
                'settings':copy.deepcopy(self.settings),'models':copy.deepcopy(self.models_state),'metrics':dict(self.metrics),
                'active':public(copy.deepcopy(self.active)),'jobs':public(list(self.jobs)),
                'gpu_resident_enabled':self.models.resident_enabled,'queue_size':self.queue.qsize(),'cameras':{k:c.state() for k,c in self.cameras.items()},
                'latest':public(copy.deepcopy(self.latest)), 'confidences':copy.deepcopy(self.confidences), 'logs':list(self.logs)[-90:],
                'registry_count':len(self.store.items()),'auto_count':self.auto_count}

    def configure(self, values):
        if self.active or self.monitor or not self.queue.empty(): raise ValueError('감시·진행·대기 작업을 중단한 뒤 설정을 변경하세요.')
        delay=float(values.get('analysis_delay',self.settings.get('analysis_delay',5)))
        if not 0<=delay<=120: raise ValueError('자동 분석 대기 시간은 0~120초로 설정하세요.')
        interval=float(values.get('interval',self.settings['interval']))
        threshold=float(values.get('threshold',self.settings['threshold']))
        if not 2<=interval<=60 or not .02<=threshold<=.95: raise ValueError('검출 간격 2~60초, 임계값 0.02~0.95 범위를 사용하세요.')
        cameras=values.get('cameras',self.settings['cameras'])
        if set(cameras)!= {'top','arm'}: raise ValueError('top/arm 카메라 설정이 필요합니다.')
        for key, cfg in cameras.items():
            cfg['name']=DEFAULTS['cameras'][key]['name']
            cfg['source']=str(cfg.get('source','')).strip()
            if cfg['source'] and not cfg['source'].startswith(('http://','https://','device:','studio:')):
                raise ValueError('MJPEG 주소, studio:프로젝트ID/카메라ID 또는 device:0 형식이 필요합니다.')
            if cfg['source'].startswith('studio:'):
                try:
                    project_id,camera_id=cfg['source'][7:].split('/')
                    uuid.UUID(project_id);uuid.UUID(camera_id)
                except Exception: raise ValueError('Studio 카메라 ID 형식이 올바르지 않습니다.')
            if cfg['source'].startswith('device:'):
                if not cfg['source'][7:].isdigit(): raise ValueError('USB 장치 번호가 올바르지 않습니다.')
            for dimension in ('width','height'):
                if dimension in cfg and (type(cfg[dimension]) is not int or not 160<=cfg[dimension]<=3840):
                    raise ValueError('카메라 해상도는 160~3840 범위의 정수로 입력하세요.')
            if not cfg['source'].startswith('device:'):
                cfg.pop('device_path',None)
        roi=values.get('roi',self.settings['roi'])
        from .video_devices import resolve_device, BRIDGE_URL, BRIDGE_CONFIG
        usb_sources=[resolve_device(int(cfg['source'][7:]),cfg.get('device_path')) for cfg in cameras.values() if cfg.get('enabled') and cfg['source'].startswith('device:')]
        if len(usb_sources)!=len(set(usb_sources)):
            raise ValueError('같은 USB 웹캠을 탑뷰와 ARM에 동시에 직접 배정할 수 없습니다.')
        if roi is not None and (not isinstance(roi,list) or len(roi)!=4 or not all(isinstance(v,(int,float)) and 0<=v<=1 for v in roi) or roi[0]>=roi[2] or roi[1]>=roi[3]):
            raise ValueError('ROI는 0~1 범위 [x1,y1,x2,y2]이어야 합니다.')
        bridge_users=[cfg for cfg in cameras.values() if cfg.get('enabled') and cfg['source']==BRIDGE_URL]
        if bridge_users and BRIDGE_CONFIG.exists():
            bridge=json.loads(BRIDGE_CONFIG.read_text(encoding='utf-8-sig'))
            if resolve_device(bridge['index'],bridge.get('device_path')) in usb_sources:
                raise ValueError('ARM 브리지와 같은 USB 웹캠을 직접 연결로 동시에 사용할 수 없습니다.')
            updated=dict(bridge)
            for dimension in ('width','height'):
                if dimension in bridge_users[0]:
                    updated[dimension]=bridge_users[0][dimension]
            if updated!=bridge:
                temporary=BRIDGE_CONFIG.with_suffix('.tmp')
                temporary.write_text(json.dumps(updated),encoding='utf-8')
                temporary.replace(BRIDGE_CONFIG)
        self.settings.update(interval=interval,threshold=threshold,cameras=cameras,roi=roi,analysis_delay=delay,
            exclude_aruco=bool(values.get('exclude_aruco',self.settings.get('exclude_aruco',True))),
            auto_features=bool(values.get('auto_features',False)),feature_limit=min(8,max(1,int(values.get('feature_limit',4)))))
        SETTINGS.write_text(json.dumps(self.settings,ensure_ascii=False,indent=2),encoding='utf-8')
        changed=[key for key,cfg in cameras.items() if self.cameras[key].config!=cfg]
        # Release both old USB handles before a possible top/arm device swap.
        for key in changed: self.cameras[key].close()
        for key, cfg in cameras.items():
            if key in changed:
                self.cameras[key]=Camera(key,cfg,self.log);self.cameras[key].start()
            self.cameras[key].overlay.show_candidates=self.settings.get('show_candidates',False)
        self.tracks.clear()
        self.log('info','settings','카메라·검출 설정 저장 완료')

    def submit(self, kind, image=None, source='upload', frame_id=None, captured=None, **kwargs):
        if self.queue.full(): raise ValueError('대기열이 가득 찼습니다. 현재 작업이 끝난 뒤 다시 요청하세요.')
        key=uuid.uuid4().hex
        job={'id':key,'kind':kind,'source':source,'frame_id':frame_id,'captured':captured or time.time(),
             'created':time.time(),'status':'queued','message':'대기 중','generation':self.generation}
        try: self.queue.put_nowait((job,image,kwargs))
        except queue.Full: raise ValueError('대기열이 가득 찼습니다.')
        with self.lock: self.jobs.appendleft(job)
        self.log('info','queue',f'{kind} 작업 접수 · {source}',job_id=key)
        return public(job)

    def snapshot_job(self, camera, kind, with_features=True):
        if camera not in self.cameras: raise ValueError('카메라 ID가 올바르지 않습니다.')
        image, seq, captured=self.cameras[camera].snapshot()
        return self.submit(kind,image,source=camera,frame_id=seq,captured=captured,with_features=with_features)

    def set_monitor(self, enabled, camera):
        if camera not in self.cameras: raise ValueError('카메라 ID가 올바르지 않습니다.')
        if enabled: self.cameras[camera].snapshot()
        self.monitor=enabled;self.monitor_camera=camera;self.last_monitor=0
        self.log('info','monitor','자동 감시 시작' if enabled else '자동 감시 중지')

    def set_overlay(self, show_candidates):
        with self.lock:
            self.settings['show_candidates']=bool(show_candidates)
            for camera in self.cameras.values(): camera.overlay.show_candidates=bool(show_candidates)
            SETTINGS.write_text(json.dumps(self.settings,ensure_ascii=False,indent=2),encoding='utf-8')

    def request_cancel(self):
        with self.lock:
            self.monitor=False
            self.generation+=1
            self.cancel.set()
            for camera in self.cameras.values():
                with camera.overlay.lock: camera.overlay.tracks=[]
        while True:
            try:
                job,_,_=self.queue.get_nowait();job.update(status='cancelled',message='대기 중 취소');self.queue.task_done()
            except queue.Empty: break
        self.log('warning','system','중단 요청 · 진행 중 연산의 종료 지점에서 해제합니다.')

    def media_image(self, image, name):
        path=MEDIA/name;path.parent.mkdir(parents=True,exist_ok=True)
        image.convert('RGB').save(path,'JPEG',quality=88)
        return '/media/'+name.replace('\\','/')

    def remember_detection(self, image, items, source, frame_id, captured, key):
        annotated=image.copy();draw=ImageDraw.Draw(annotated)
        for obj in items:
            box=obj['bbox'];color='#55e5a9' if not obj.get('reasons') else '#ffbc69'
            draw.rectangle(box,outline=color,width=3)
            label=f'#{obj["index"]+1} {obj["category"]} {obj["score"]:.2f}'
            draw.rectangle((box[0],max(0,box[1]-20),min(image.width,box[0]+len(label)*7+8),max(20,box[1])),fill='#15231f')
            draw.text((box[0]+3,max(0,box[1]-18)),label,fill=color)
        file_key=f'previews/{source}_{int(key[-1],16)%4}' if key.startswith('monitor/') else key
        snap=self.media_image(annotated,f'{file_key}/boxes.jpg')
        result={'id':key,'created':time.time(),'captured':captured,'source':source,'frame_id':frame_id,
                'image_size':list(image.size),'snapshot':snap,'items':items,'status':'detected'}
        if source in self.cameras:
            with self.lock: self.latest[source]=public(result)
        return result

    def update_tracks(self, items, source):
        now=time.time();old=[t for t in self.tracks.get(source,[]) if now-t['seen']<20]
        used=set();current=[]
        for obj in items:
            if obj.get('reasons'): continue
            candidates=[t for t in old if t['id'] not in used and t['category']==obj['category'] and iou(t['bbox'],obj['bbox'])>.5]
            if candidates:
                track=max(candidates,key=lambda t:iou(t['bbox'],obj['bbox']));track['hits']+=1
            else:
                self.track_seq+=1;track={'id':self.track_seq,'category':obj['category'],'hits':1,'processed':0,'first_seen':now}
            track.update(bbox=obj['bbox'],seen=now);used.add(track['id']);current.append(track)
            obj['track_id']=track['id'];obj['stable_hits']=track['hits']
        self.tracks[source]=current
        delay=getattr(self,'settings',{}).get('analysis_delay',0)
        for track in current:
            track['remaining_seconds']=max(0,delay-(now-track['first_seen']))
        ready=[t for t in current if t['hits']>=2 and not t['processed'] and t['remaining_seconds']<=0]
        return ready

    def process(self, job, image, options):
        start=time.time();kind=job['kind']
        if kind=='search':
            text=options.get('text','')
            for row in sorted(CATEGORY_CATALOG.snapshot(),key=lambda r:len(r['name']),reverse=True):
                text=text.replace(row['name'],row['description'])
            # Only a small explicit vocabulary translation; no claim of general Korean translation.
            for a,b in {'하늘색':'light blue','분홍색':'pink','분홍':'pink','핑크':'pink','회색':'gray','은색':'silver','핸드폰':'mobile phone','휴대폰':'mobile phone','지갑':'wallet','핸드크림':'hand cream','립밤':'lip balm','파란':'blue','파랑':'blue','검정':'black','검은':'black','하얀':'white','흰색':'white','빨간':'red','빨강':'red','초록':'green'}.items(): text=text.replace(a,b)
            embedding=self.models.query_embedding(image=image,text=text)
            requested=text_features(options.get('text',''))
            if image is not None and requested.get('body_color')=='unknown':
                probe={'index':0,'bbox':[0,0,image.width,image.height],'quality':'accepted'}
                self.models.features(image,[probe],1)
                requested=probe.get('features',{})
            catalog=CATEGORY_CATALOG.snapshot()
            terms=name_terms(options.get('text',''),[r['id'] for r in catalog]+[r['name'] for r in catalog]+[r['description'] for r in catalog])
            category=options.get('category') or None;inferred=None
            if not category:
                inferred=query_category(options.get('text',''),catalog)
                if inferred and any(i['category']==inferred for i in self.store.items()):category=inferred
                else:inferred=None
            result=self.store.rank(embedding,category,features=requested,terms=terms)
            result['name_terms']=terms;result['inferred_category']=inferred
            result['query_features']=requested
            result.update(query=options.get('text','이미지 검색'),used_text=text if image is None else None)
            job['search_result']=result
            return
        items=copy.deepcopy(options.get('detections'))
        if items is None:
            detection_image=image
            marker_boxes=[]
            if job['source']=='top' and self.settings.get('exclude_aruco',True):
                from .markers import exclude_markers
                # v0.2.58: remember the last frame where all 4 markers were found; a frame
                # that misses one still masks it at the remembered place.
                cache=getattr(self,'marker_cache',None)
                fallback=cache[1] if cache and cache[0]==image.size else None
                detection_image,marker_boxes=exclude_markers(image,fallback)
                if getattr(marker_boxes,'found',len(marker_boxes))>=4:self.marker_cache=(image.size,[list(b) for b in marker_boxes])
                self.log('info','detection',f'ArUco 위치 마커 {len(marker_boxes)}개 · 물품 검출에서 제외',job_id=job['id'])
            # Crop only the fixed top-view feed. ARM/upload coordinates stay unchanged.
            region=self.settings['roi'] if job['source']=='top' else None
            if region:
                from .region import pixel_box
                x1,y1,x2,y2=pixel_box(image,region)
                items=self.models.detect(detection_image.crop((x1,y1,x2,y2)),self.settings['threshold'],trained=job['source']=='top')
                for obj in items+getattr(self.models,'preview_candidates',[]):
                    b=obj['bbox'];obj['bbox']=[b[0]+x1,b[1]+y1,b[2]+x1,b[3]+y1]
                    if 'center' in obj: obj['center']=[obj['center'][0]+x1,obj['center'][1]+y1]
            else:
                items=self.models.detect(detection_image,self.settings['threshold'],trained=job['source']=='top')
            if marker_boxes:
                from .markers import is_marker_box
                items=[o for o in items if not is_marker_box(o['bbox'],marker_boxes)]
                for index,obj in enumerate(items): obj['index']=index
                self.models.preview_candidates=[o for o in self.models.preview_candidates if not is_marker_box(o['bbox'],marker_boxes)]
            if job['source']=='top':
                from .scene_filter import suppress_parts, is_support_preview
                before=len(items)
                items=suppress_parts(items)
                from .scene_filter import suppress_supports,reject_attached_parts
                items=suppress_supports(items)
                items=reject_attached_parts(image,items)
                for index,obj in enumerate(items): obj['index']=index
                previews=self.models.preview_candidates
                self.models.preview_candidates=[o for o in previews if not is_support_preview(image,o)]
                removed=before-len(items)+len(previews)-len(self.models.preview_candidates)
                if removed: self.log('info','detection',f'본체 부분·받침대 표시 후보 {removed}개 제외',job_id=job['id'])
            with self.lock:
                self.confidences[job['source']]={'captured':job['captured'],'threshold':self.settings['threshold'],
                    'source':job['source'],'rows':[{'category':o['category'],'score':o['score'],
                    'bbox':o['bbox'],'prompt':o.get('detector_prompt',''),'accepted':True} for o in items]+
                    [{'category':o['category'],'score':o['score'],'bbox':o['bbox'],
                    'prompt':'','accepted':False} for o in getattr(self.models,'preview_candidates',[])]}
        self.models.check()
        if job['source'] in self.cameras:
            self.cameras[job['source']].overlay.set_detections(image,job['frame_id'],items,
                getattr(self.models,'preview_candidates',[]) if options.get('detections') is None else [])
        self.log('info','detection',f'박스 후보 {len(items)}개 · 빈 검출은 빈 장면 확정이 아닙니다.',job_id=job['id'])
        result=self.remember_detection(image,items,job['source'],job['frame_id'],job['captured'],job['id'])
        if kind=='monitor':
            ready=self.update_tracks(items,job['source'])
            if self.settings['auto_features']:
                for track in self.tracks.get(job['source'],[]):
                    if not track['processed'] and track['remaining_seconds']>0:
                        self.log('info','trigger',f'{track["category"]} 감지 · 자동 분석까지 약 {track["remaining_seconds"]:.0f}초 · 사라지면 취소')
            if self.settings['auto_features'] and ready and not self.queue.full():
                ready_ids={t['id'] for t in ready}
                pending=[copy.deepcopy(o) for o in items if o.get('track_id') in ready_ids]
                for index,obj in enumerate(pending): obj['index']=index
                try:
                    self.submit('analyze',image.copy(),source=job['source'],frame_id=job['frame_id'],captured=job['captured'],detections=pending,with_features=True,stable_intake=True,scene_count=len(items))
                    for t in ready: t['processed']=time.time()
                    self.auto_count+=1
                except ValueError:
                    self.log('warning','queue','자동 분석 대기열이 가득 찼습니다. 다음 감시에서 다시 확인합니다.')
            job['result']=public(result)
            return
        for obj in items:
            obj['crop']=self.media_image(image.crop(obj['bbox']),f'{job["id"]}/crop_{obj["index"]}.jpg')
        if kind=='analyze' and items:
            def embedded(obj,crop):
                obj.update(self.store.rank(obj['_embedding'],None,None))
                self.log('info','matching',f'#{obj["index"]+1} {obj["category"]} · 등록 후보 {len(obj["candidates"])}개 · 일치 미확정')
            self.models.embed_items(image,items,embedded)
            if job['source'] in self.cameras: self.cameras[job['source']].overlay.refine(job['frame_id'],items)
            self.models.check()
            if options.get('with_features',True): self.models.features(image,items,self.settings['feature_limit'])
            else:
                from .object_reference import quick_features
                for obj in items:obj['features']=quick_features(image,obj['bbox'])
            from .models import trained_alone
            alone=trained_alone()
            for obj in items:
                if obj.get('_embedding'):
                    features=obj.get('features') or {}
                    # v0.2.66: when the board YOLO learned every category its category is final.
                    final=alone and obj.get('detector_prompt')=='trained_yolo'
                    if not final and obj['category'] in {'wallet','lip_balm','phone'}:
                        visible=str(features.get('visible_text',''))
                        marks=str(features.get('distinctive_marks',''))
                        usb_cue=re.search(r'\bUSB\b',visible,re.I) or re.search(r'\bUSB (?:connector|plug)\b',marks,re.I)
                        usb=self.store.rank(obj['_embedding'],'usb',obj['_hash'],features=features)
                        other_score=max((c['similarity'] for c in obj.get('candidates',[])),default=-1)
                        reference=next((c for c in usb['candidates']
                                        if (usb_cue and c['similarity']>=.80)
                                        or (c['similarity']>=.90 and c['similarity']-other_score>=.05)),None)
                        if reference:
                            obj['category']='usb'
                            obj['category_correction']='등록 USB 사진과 유사'
                            self.log('info','matching',f'#{obj["index"]+1} USB로 분류 보완 · 참조 사진 {reference["similarity"]:.2f}')
                    obj.update(self.store.rank(obj['_embedding'],None,None,features=features))
                    # v0.2.62: the board YOLO knows only the categories it was trained on (now usb);
                    # a red lip balm came out 'usb' 0.82. When the registered photos clearly say
                    # another category, follow them.
                    if not final and obj.get('detector_prompt')=='trained_yolo' and obj.get('candidates'):
                        top=obj['candidates'][0]
                        same=max((c['matching_score'] for c in obj['candidates'] if c['category']==obj['category']),default=-1)
                        zero_shot_agrees=str((obj.get('classification') or {}).get('label',''))=='a photo of '+str(CLASSES.get(obj['category'],''))
                        need=.03 if not zero_shot_agrees else .05
                        if top['category']!=obj['category'] and (top['matching_score']>=.80 and top['matching_score']-same>=.08 or top['matching_score']>=.85 and top['matching_score']-same>=need):
                            self.log('info','matching',f'#{obj["index"]+1} 학습 검출 {obj["category"]} → 등록 사진 기준 {top["category"]} ({top["id"]} {top["matching_score"]:.2f})')
                            obj['category_correction']='학습 검출 %s → 등록 사진 %s'%(obj['category'],top['category']);obj['category']=top['category']
                    self.log('info','matching',f'#{obj["index"]+1} 사진·바탕색 결합 비교 완료 · 일치 미확정')
            if job['source'] in self.cameras: self.cameras[job['source']].overlay.refine(job['frame_id'],items)
        # Render final quality decisions, keeping bbox and crop tied to the same captured frame.
        if options.get('target_id'):
            target_id=options['target_id'];matches=[]
            for obj in items:
                if not obj.get('_embedding') or obj.get('quality')!='accepted': continue
                ranked=self.store.rank(obj['_embedding'],None,None,features=obj.get('features'),limit=10000)
                candidate=next((c for c in ranked['candidates'] if c['id']==target_id),None)
                if candidate: matches.append(dict(index=obj['index'],bbox=obj['bbox'],center=obj['center'],**candidate))
            matches.sort(key=lambda c:c['matching_score'],reverse=True)
            job['target_result']={'target_id':target_id,'status':'candidate' if matches else 'not_found',
                'captured':job['captured'],'frame_id':job['frame_id'],'coordinate_system':'full_frame_pixels',
                'best':matches[0] if matches else None,'candidates':matches,'robot_ready':False}
            if matches:
                from .coordinates import convert
                try: job['target_result']['board_coordinates']=convert(image,matches[0]['center'])
                except ValueError as exc: job['target_result']['board_coordinates']={'status':'unavailable','reason':str(exc),'robot_ready':False}
                self.cameras['top'].overlay.mark_target(job['frame_id'],matches[0]['index'],target_id)
            self.log('info','target',f'선택 물품 {target_id} · 위치 후보 {len(matches)}개 · 로봇 이동 없음')
        result=self.remember_detection(image,items,job['source'],job['frame_id'],job['captured'],job['id'])
        result.update(status='complete',seconds=time.time()-start,with_features=options.get('with_features',False))
        self.store.save_observation(result)
        if job['source']=='top':
            from .workflow import load as workflow_settings
            settings=workflow_settings()
            for index,obj in enumerate(items):
                if obj.get('quality')!='accepted' or not obj.get('_embedding'):continue
                track=next((t for t in self.tracks.get('top',[]) if t['id']==obj.get('track_id')),None)
                candidates=obj.get('candidates',[])
                best=candidates[0] if candidates else None
                item_id=track.get('item_id') if track else None
                if not item_id and best and best.get('matching_score',0)>=.85 and (len(candidates)<2 or best['matching_score']-candidates[1]['matching_score']>=.05):item_id=best['id']
                if not item_id and settings['auto_intake'] and options.get('stable_intake') and options.get('scene_count')==1:
                    item_id='AUTO_'+uuid.uuid4().hex[:16]
                    self.store.register(result['id'],index,item_id,obj['category'],json.dumps({'found_time':job['captured'],'found_place':settings['found_place']},ensure_ascii=False))
                    self.log('info','intake',f'자동 접수 완료 · {item_id} · {settings["found_place"]}')
                if track and item_id:track['item_id']=item_id
                if item_id:obj['inventory_id']=item_id
        job['result']=public(result)
        self.log('info','database',f'관측 저장 · {len(items)}개 후보 · {result["seconds"]:.2f}초 · 자동 접수 설정에 따라 등록')

    def run(self):
        while not self.stop.is_set():
            from_queue=True
            try:
                job,image,options=self.queue.get(timeout=.5)
            except queue.Empty:
                if not self.monitor or time.time()-self.last_monitor<self.settings['interval']: continue
                self.last_monitor=time.time();from_queue=False
                try: image,seq,captured=self.cameras[self.monitor_camera].snapshot()
                except ValueError: continue
                job={'id':'monitor/'+uuid.uuid4().hex,'kind':'monitor','source':self.monitor_camera,'frame_id':seq,
                    'captured':captured,'created':time.time(),'status':'queued'};options={}
            with self.lock:
                if from_queue and job.get('generation',self.generation)!=self.generation:
                    job.update(status='cancelled',message='실행 전 취소')
                    self.queue.task_done()
                    continue
                self.cancel.clear()
                job.update(status='running',started=time.time(),message='처리 중')
                self.active=job
            try:
                self.process(job,image,options)
                job.update(status='complete',message='완료',finished=time.time())
            except InterruptedError as exc:
                job.update(status='cancelled',message=str(exc),finished=time.time())
                self.log('warning','cancel',str(exc))
            except Exception as exc:
                job.update(status='failed',message=str(exc)[:350],finished=time.time())
                self.log('error','worker',str(exc)[:500],job_id=job['id'])
                with (DATA/'errors.log').open('a',encoding='utf-8') as out: out.write(traceback.format_exc()+'\n')
                # Prevent repeated model failures from spinning an automatic loop.
                if job['kind']=='monitor': self.monitor=False
            finally:
                with self.lock: self.active=None
                if from_queue: self.queue.task_done()
