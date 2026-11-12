from .version import VERSION, BUILD
import asyncio
import base64
import io
import json
import requests
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import ROOT, MEDIA, CLASSES, CATEGORY_CATALOG
from .engine import Engine
from .storage import public
from .manual_control import manual
from .robot_actions import actions
from .grasp_flow import GraspFlow

engine=Engine()
grasp_flow=GraspFlow(engine)

@asynccontextmanager
async def lifespan(app):
    engine.start()
    yield
    if actions.snapshot()['running']:
        await asyncio.to_thread(actions.stop)
        if actions.thread:await asyncio.to_thread(actions.thread.join,4)
    await asyncio.to_thread(manual.close)
    engine.close()

app=FastAPI(title='Field Vision Beta',version='0.1.0',lifespan=lifespan,docs_url=None,redoc_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])
app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')
app.mount('/media',StaticFiles(directory=MEDIA),name='media')

@app.middleware('http')
async def local_mutations(request:Request,call_next):
    if request.method in ('POST','PUT','DELETE'):
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'다른 웹사이트에서 보낸 변경 요청은 허용하지 않습니다.'},status_code=403)
        if int(request.headers.get('content-length','0'))>16*1024*1024:
            return JSONResponse({'detail':'입력 파일은 10MB 이하로 줄여주세요.'},status_code=413)
    return await call_next(request)

@app.exception_handler(ValueError)
async def bad_input(request,exc):
    return JSONResponse({'detail':str(exc)},status_code=400)

def image_input(data_url):
    try:
        raw=base64.b64decode(data_url.split(',',1)[-1],validate=True)
        if len(raw)>10*1024*1024: raise ValueError('이미지는 10MB 이하로 업로드하세요.')
        image=Image.open(io.BytesIO(raw))
        if image.width*image.height>16_000_000: raise ValueError('이미지 해상도는 1600만 화소 이하로 줄여주세요.')
        image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1920,1440))
        return image
    except (UnidentifiedImageError,TypeError,AttributeError,IndexError) as exc:
        raise ValueError('올바른 이미지 파일이 아닙니다.') from exc

@app.get('/')
def home(): return FileResponse(Path(__file__).parent/'static/beta.html')

@app.get('/manual')
def manual_page(): return FileResponse(Path(__file__).parent/'static/manual.html')

@app.get('/api/manual/state')
def manual_state(): return manual.snapshot()

@app.post('/api/manual/connect')
async def manual_connect():
    try:return await asyncio.to_thread(manual.start)
    except Exception as exc:raise ValueError(str(exc))

@app.post('/api/manual/disconnect')
async def manual_disconnect():
    if actions.snapshot()['running']:await asyncio.to_thread(actions.stop)
    return await asyncio.to_thread(manual.close)

@app.post('/api/manual/command')
async def manual_command(request:Request):
    data=await request.json();action=data.get('action')
    if action=='stop':return await asyncio.to_thread(actions.stop)
    if actions.snapshot()['running']:raise ValueError('자동 시퀀스 중에는 STOP만 허용합니다.')
    if action=='disconnect':raise ValueError('연결 종료 버튼을 사용하세요.')
    try:return await asyncio.to_thread(manual.send,action,action!='jog',
        joint=data.get('joint'),direction=data.get('direction'),speed=data.get('speed',5),token=data.get('token'),
        target=data.get('target'),expected=data.get('expected'),duration=data.get('duration',5),grip_contact=data.get('grip_contact',False),ratio=data.get('ratio',.2))
    except Exception as exc:raise ValueError(str(exc))

@app.post('/api/manual/snapshot')
async def manual_snapshot(request:Request):
    import time,uuid
    data=await request.json()
    state=await asyncio.to_thread(manual.send,'snapshot')
    if state['active']:raise ValueError('이동 버튼을 놓고 자세를 저장하세요.')
    path=manual.directory/('pose-'+uuid.uuid4().hex[:10]);path.mkdir()
    from .coordinates import load as board_config
    from .robot_frame import load as frame_config
    result={'label':str(data.get('label',''))[:200],'captured':time.time(),'state':state,
        'board_config':board_config(),'robot_frame':frame_config(),'images':{}}
    for key,camera in engine.cameras.items():
        try:
            image,seq,captured=camera.snapshot();image.save(path/(key+'.jpg'))
            result['images'][key]={'frame_id':seq,'captured':captured,'file':key+'.jpg'}
        except ValueError:pass
    (path/'pose.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'ok':True,'saved':str(path),'label':result['label']}

@app.get('/api/grasp/geometry')
def grasp_geometry():
    from .grasp_geometry import pink_tube
    image,seq,captured=engine.cameras['arm'].snapshot()
    return dict(pink_tube(image),frame_id=seq,captured=captured,
        note='분홍색 핸드크림의 시험용 후보 · 집게 좌우 벌림을 ARM 영상 가로 방향으로 보는 가정')

@app.get('/api/prototype/state')
def prototype_state():
    return {'action':actions.snapshot(),'home':actions.home_status(),'plan':grasp_flow.latest_plan,
        'position_diagnostic':grasp_flow.position_diagnostic,
        'manual':manual.snapshot(),'scope':'USB·핸드크림·립밤 집기 시험 · 실제 들림은 실물 확인'}


@app.get('/api/prototype/tcp')
async def tcp_state():
    from .tcp_calibration import status
    return await asyncio.to_thread(status)


@app.post('/api/prototype/tcp')
async def tcp_update(request:Request):
    from .tcp_calibration import update
    data=await request.json()
    if not isinstance(data,dict):raise ValueError('보정 요청 형식 오류')
    return await asyncio.to_thread(update,data.get('operation'),data.get('board_mm'),data.get('height_mm',0),data.get('sample_id'))


@app.get('/api/prototype/tcp/reference')
async def tcp_reference_state(point:str='center',height_mm:float=50):
    from .tcp_reference import reference_info,snapshot
    import time
    def read():
        image,_,captured=engine.cameras['top'].snapshot()
        if time.time()-captured>1:raise ValueError('탑뷰 최신 프레임이 필요합니다.')
        return {'target':reference_info(image,point,height_mm),'last_move':snapshot()}
    return await asyncio.to_thread(read)


@app.get('/api/prototype/tcp/reference.jpg')
async def tcp_reference_image(point:str='center',height_mm:float=50):
    from .tcp_reference import reference_info,overlay
    def render():
        image,_,_=engine.cameras['top'].snapshot()
        image=overlay(image,reference_info(image,point,height_mm));out=io.BytesIO();image.save(out,format='JPEG')
        return Response(out.getvalue(),media_type='image/jpeg',headers={'Cache-Control':'no-store'})
    return await asyncio.to_thread(render)


@app.post('/api/prototype/tcp/reference')
async def tcp_reference_action(request:Request):
    from .tcp_reference import start,record_observation
    data=await request.json()
    if not isinstance(data,dict):raise ValueError('요청 형식 오류')
    if data.get('operation')=='move':
        return await asyncio.to_thread(start,engine,data.get('point','center'),data.get('height_mm',50))
    if data.get('operation') in ('observe','observe_verify'):
        return await asyncio.to_thread(record_observation,engine,data.get('required_board_motion_mm'),data.get('actual_height_mm'),verification=data['operation']=='observe_verify',move_id=data.get('move_id'))
    raise ValueError('기준점 이동 또는 실물 관측 등록을 선택하세요.')

@app.post('/api/prototype/stop')
async def prototype_stop():return await asyncio.to_thread(actions.stop)

@app.post('/api/prototype/home/save')
async def prototype_home_save():return await asyncio.to_thread(actions.save_home)

@app.post('/api/prototype/home/go')
async def prototype_home_go():return await asyncio.to_thread(actions.go_home)

@app.post('/api/prototype/gripper/open')
async def prototype_gripper_open():
    return await asyncio.to_thread(actions.open_gripper)


@app.post('/api/prototype/gripper/register')
def register_fixed_gripper():
    import json
    from .grasp_alignment import camera_profile, visible_fingers
    from .robot_actions import fresh
    from .config import DATA
    state=fresh()
    if actions.snapshot()['running'] or state['active']:
        raise ValueError('동작 종료 후 등록하세요.')
    joints={joint['name']:joint for joint in state['joints']}
    jaw=joints['gripper']
    if abs(jaw['raw_ticks']-round((jaw['min_ticks']+jaw['max_ticks'])/2))>30:
        raise ValueError('집게만 50% 열기 버튼을 누른 뒤 등록하세요.')
    camera=engine.cameras['arm']
    image,seq,captured=camera.snapshot()
    left=[c for c,box in visible_fingers(image,registration=True) if box[0]<image.width*.15 and box[0]+box[2]<image.width*.45]
    if len(left)!=1:
        raise ValueError('왼쪽 고정 손가락이 뚜렷하지 않습니다. 물건과 배경을 치우고 다시 등록하세요.')
    profile=camera_profile(camera.state())
    if profile['frame_size']!=list(image.size):
        raise ValueError('ARM 영상 설정이 변경됐습니다. 다시 등록하세요.')
    record={'method':'white_finger_green_background','camera':profile,'frame_size':list(image.size),'contour':left[0].reshape(-1,2).tolist(),
            'source_frame':'arm_fixed_finger_home.png','captured':captured,'frame_id':seq}
    image.save(DATA/'arm_fixed_finger_home.png')
    path=DATA/'arm_fixed_finger.json'
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record,indent=2),encoding='utf-8')
    temporary.replace(path)
    return {'ok':True}


@app.post('/api/prototype/start')
async def prototype_start(request:Request):
    data=await request.json()
    from .workflow import load as workflow_settings
    defaults=workflow_settings()
    engine.set_monitor(False,'top')
    return await asyncio.to_thread(grasp_flow.start,data.get('search_job_id'),
        float(data.get('approach_height_mm',defaults['approach_height_mm'])),float(data.get('grasp_height_mm',defaults['grasp_height_mm'])),measure_only=data.get('measure_only') is True,relaxed=data.get('relaxed') is True,simple_mode=data.get('simple_mode',True) is True)

@app.get('/api/workflow')
def workflow_state():
    from .workflow import load
    from .config import DATA
    reports=sorted((DATA/'grasp_trials').glob('*/report.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:12]
    recent=[]
    for path in reports:
        try:
            report=json.loads(path.read_text(encoding='utf-8'))
            recent.append({k:report.get(k) for k in ['id','started','finished','result','error','lift_evidence','returned']})
        except (OSError,ValueError):pass
    with engine.lock:inventory=public(__import__('copy').deepcopy(engine.tracks.get('top',[])))
    return {'settings':load(),'inventory':inventory,'recent':recent}

@app.post('/api/workflow')
async def workflow_update(request:Request):
    from .workflow import save,teach
    from .robot_actions import fresh
    values=await request.json()
    with actions.lock:
        if actions.snapshot()['running'] or manual.snapshot().get('active'):raise ValueError('현재 동작을 마친 뒤 설정을 저장하세요.')
        if values.get('operation')=='check':
            from .return_path import dry_check
            from .robot_actions import read_home
            from .workflow import load as workflow_load
            settings=workflow_load();home=read_home()
            if not home:raise ValueError('준비자세(HOME)를 먼저 저장하세요.')
            return {'ok':True,'check':dry_check(fresh(),(settings.get('dropoff_pose') or {}).get('ticks'),home['raw_ticks'],settings['transfer_height_mm'])}
        if values.get('operation') in ['dropoff','clear']:
            result=teach(values['operation'],fresh() if values['operation']=='dropoff' else {})
        else:result=save(values)
    return {'ok':True,'settings':result}

@app.get('/api/prototype/arm.jpg')
def prototype_arm():
    from PIL import ImageDraw
    from .finger_edges import edges,overlay
    from .cameras import jpeg
    from .config import DATA
    from .grasp_alignment import load_fixed_finger
    camera=engine.cameras['arm']
    image,seq,captured=camera.snapshot()
    display=overlay(image,edges(image,color=(grasp_flow.latest_plan or {}).get('target_color','pink')))
    # v0.2.72: this panel used the raw frame, so the ARM detector / TARGET box (v0.2.69)
    # never showed here. Draw the same tracked boxes as the camera view.
    display=camera.overlay.draw(display)
    # v0.2.79: for a wide target show the edge the grasp actually uses (nearest to the
    # fixed finger, v0.2.78) in red; the yellow finger_edges outline is display-only.
    ref=(grasp_flow.latest_plan or {}).get('target_color')
    if isinstance(ref,dict):
        from .object_reference import large_item
        if large_item(ref):
            from .partial_boundary import nearest_edge
            import numpy as np
            try:
                near=nearest_edge(np.asarray(image.convert('RGB')),ref)
                d=ImageDraw.Draw(display,'RGBA');(px,py),(qx,qy)=near['points']
                d.line([(px,py),(qx,qy)],fill=(255,40,40,255) if near['usable_for_gap'] else (255,40,40,110),width=4)
                d.text((8,24),'GRASP EDGE (nearest) %.0f deg %s'%(near['angle_deg'],'OK' if near['usable_for_gap'] else 'weak'),fill=(255,60,60,255))
            except ValueError:pass
    try:
        registration=load_fixed_finger(DATA/'arm_fixed_finger.json',camera.state())
    except ValueError:
        pass
    else:
        if registration['frame_size']==list(image.size):
            outline=[tuple(point) for point in registration['contour']]
            draw=ImageDraw.Draw(display,'RGBA')
            draw.polygon(outline,fill=(35,215,255,85))
            draw.line(outline+[outline[0]],fill=(35,215,255,255),width=2)
            from .grasp_reference import contact_reference
            contact=contact_reference(registration)
            y1,y2=contact['image_rows'];x,y=contact['image_point']
            draw.line([(x,y1),(x,y2)],fill=(255,190,40,255),width=4)
            draw.ellipse((x-5,y-5,x+5,y+5),fill=(255,190,40,255))
            draw.text((8,8),'CONTACT: provisional fixed strip',fill=(255,190,40,255))
    return Response(jpeg(display),media_type='image/jpeg',headers={'Cache-Control':'no-store'})

@app.get('/api/prototype/edges')
def prototype_edges():
    from .finger_edges import edges
    image,seq,captured=engine.cameras['arm'].snapshot()
    return dict(edges(image,color=(grasp_flow.latest_plan or {}).get('target_color','pink')),frame_id=seq,captured=captured)

@app.get('/api/health')
def health():
    from .approach_path import SIGN
    return {'ok':True,'version':VERSION,'build':BUILD,'worker_alive':engine.worker.is_alive(),'joint_sign':SIGN.tolist(),'planner_revision':'fast-first-valid-v1','gpu_resident_enabled':engine.models.resident_enabled}

@app.get('/api/state')
def state(): return engine.state()

@app.get('/api/events')
async def events(request:Request):
    async def stream():
        while not await request.is_disconnected():
            yield 'data: '+json.dumps(engine.state(),ensure_ascii=False)+'\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.get('/api/cameras/{key}/stream')
async def camera_stream(key:str,request:Request):
    if key not in engine.cameras: raise HTTPException(404,'카메라 없음')
    async def stream():
        last=-1
        while not await request.is_disconnected():
            camera=engine.cameras[key]
            with camera.lock: seq,data=camera.seq,camera.display_jpeg or camera.jpeg
            region=engine.settings.get('roi') if key=='top' else None
            signature=(seq,tuple(region) if region else None)
            if data and signature!=last:
                last=signature
                # The boxes are already painted in full-frame coordinates.
                # Crop the composed image so their positions remain aligned.
                if region:
                    from .region import pixel_box
                    from .cameras import jpeg
                    def render_region(raw, roi):
                        with Image.open(io.BytesIO(raw)) as image:
                            return jpeg(image.crop(pixel_box(image,roi)))
                    data=await asyncio.to_thread(render_region,data,region)
                yield b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n'
            await asyncio.sleep(.07)
    return StreamingResponse(stream(),media_type='multipart/x-mixed-replace; boundary=frame',headers={'Cache-Control':'no-store'})

@app.get('/api/cameras/{key}/frame.jpg')
def camera_frame(key:str):
    if key not in engine.cameras:raise HTTPException(404,'카메라 없음')
    camera=engine.cameras[key]
    import time
    with camera.lock:
        if camera.jpeg is None or time.time()-camera.last>4:raise ValueError('최신 카메라 프레임이 없습니다.')
        data=camera.display_jpeg or camera.jpeg
    region=engine.settings.get('roi') if key=='top' else None
    if region:
        from .region import pixel_box
        from .cameras import jpeg
        with Image.open(io.BytesIO(data)) as image:data=jpeg(image.crop(pixel_box(image,region)))
    return Response(data,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

@app.get('/api/cameras/{key}/crop/{track_id}.jpg')
def live_crop(key:str,track_id:str):
    if key not in engine.cameras: raise HTTPException(404,'카메라 없음')
    data=engine.cameras[key].crop(track_id)
    if data is None: return Response(status_code=204)
    return Response(data,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

@app.post('/api/overlay')
async def overlay_options(request:Request):
    data=await request.json();engine.set_overlay(data.get('show_candidates',False))
    return {'ok':True}

@app.get('/api/video-devices')
def list_video_devices():
    from .video_devices import video_devices, BRIDGE_CONFIG
    import json
    devices=video_devices()
    bridge=json.loads(BRIDGE_CONFIG.read_text(encoding='utf-8-sig')) if BRIDGE_CONFIG.exists() else {}
    if bridge.get('device_path'):
        bridge['index']=next((d['index'] for d in devices if d['path']==bridge['device_path']),None)
    return {'devices':devices,'bridge':bridge}


@app.post('/api/settings')
async def settings(request:Request):
    if actions.snapshot()['running']:raise ValueError('로봇 시퀀스를 STOP한 뒤 설정을 변경하세요.')
    values=await request.json()
    await asyncio.to_thread(engine.configure,values)
    return {'ok':True}

@app.get('/api/region/frame.jpg')
def region_frame(crop:bool=False):
    from .region import pixel_box
    from .cameras import jpeg
    image,_,_=engine.cameras['top'].snapshot()
    if crop and engine.settings.get('roi'):
        image=image.crop(pixel_box(image,engine.settings['roi']))
    return Response(jpeg(image),media_type='image/jpeg',headers={'Cache-Control':'no-store'})

@app.post('/api/region')
async def region_settings(request:Request):
    if actions.snapshot()['running']:raise ValueError('로봇 시퀀스를 STOP한 뒤 영역을 변경하세요.')
    from .region import DEFAULT_REGION, find_region
    data=await request.json()
    mode=data.get('mode')
    if mode=='auto':
        image,_,_=engine.cameras['top'].snapshot()
        roi=await asyncio.to_thread(find_region,image)
    elif mode=='default': roi=list(DEFAULT_REGION)
    elif mode=='clear': roi=None
    elif mode=='manual': roi=data.get('roi')
    else: raise ValueError('영역 설정 방식을 확인하세요.')
    if mode=='manual' and roi is None: raise ValueError('영상에서 영역을 드래그하세요.')
    values=dict(engine.settings,roi=roi)
    await asyncio.to_thread(engine.configure,values)
    return {'ok':True,'roi':roi}

@app.post('/api/monitor')
async def monitor(request:Request):
    if actions.snapshot()['running']:raise ValueError('로봇 시퀀스 중에는 자동 감시를 시작하지 않습니다.')
    data=await request.json();engine.set_monitor(bool(data.get('enabled')),data.get('camera','arm'))
    return {'ok':True}

@app.post('/api/cancel')
def cancel():
    engine.request_cancel()
    if actions.snapshot()['running']:actions.stop()
    return {'ok':True}

@app.post('/api/analyze')
async def analyze(request:Request):
    if actions.snapshot()['running']:raise ValueError('로봇 시퀀스의 전용 분석이 진행 중입니다.')
    data=await request.json();kind=data.get('kind','analyze')
    if kind not in ('analyze','detect'): raise ValueError('분석 작업 종류가 올바르지 않습니다.')
    if data.get('data_url'):
        return engine.submit(kind,image_input(data['data_url']),source='upload',with_features=bool(data.get('with_features',True)))
    return engine.snapshot_job(data.get('camera','arm'),kind,bool(data.get('with_features',True)))

@app.post('/api/sample')
async def sample(request:Request):
    data=await request.json()
    path=Path(__file__).parent/'assets/demo_wallet.jpg'
    if not path.exists(): raise ValueError('현재 PC에 시험용 지갑 사진이 없습니다. 사진을 업로드하세요.')
    image=Image.open(path).convert('RGB')
    return engine.submit('analyze',image,source='sample',with_features=bool(data.get('with_features',True)))

@app.get('/api/observations')
def observations(): return engine.store.observations()

@app.post('/api/observations/reset')
def reset_observations():
    engine.request_cancel()
    if engine.active:
        raise ValueError('감시를 중단했습니다. 현재 분석이 끝나면 초기화를 다시 눌러주세요.')
    with engine.lock:
        count=engine.store.clear_observations()
        engine.latest.clear();engine.confidences.clear();engine.jobs.clear();engine.tracks.clear()
    engine.log('info','history',f'최근 관측 {count}건 초기화 · 등록 물품 유지 · 이전 기록은 archives에 보관')
    return {'ok':True,'cleared':count,'archived':True}

@app.get('/api/registry')
def registry(): return engine.store.items()

@app.post('/api/registry')
async def registry_update(request:Request):
    data=await request.json();op=data.get('operation');store=engine.store
    if op=='update':result=store.update_item(str(data.get('id','')),data.get('name'),data.get('notes'),data.get('category'))
    elif op=='merge':result=store.merge_item(str(data.get('id','')),str(data.get('target','')).strip())
    elif op=='delete_reference':result=store.delete_reference(str(data.get('ref_id','')))
    elif op=='delete':result=store.delete_item(str(data.get('id','')))
    else:raise ValueError('지원하지 않는 등록 물품 작업')
    engine.log('info','registry','등록 물품 %s · %s'%({'update':'수정','merge':'ID 변경/합치기','delete_reference':'참조 사진 삭제','delete':'삭제'}[op],json.dumps(result,ensure_ascii=False)))
    return result

@app.get('/api/coordinates')
def coordinate_config():
    from .coordinates import load, geometry
    config=load()
    try:
        image,_,captured=engine.cameras['top'].snapshot()
        _,points,ids=geometry(image,config)
        status={'ready':True,'corners_pixels':points.tolist(),'detected_ids':ids,'captured':captured}
    except ValueError as exc: status={'ready':False,'reason':str(exc)}
    return {'config':config,'status':status,'robot_ready':False}

@app.get('/api/robot/status')
async def robot_status():
    from .robot_link import status
    try: return await asyncio.to_thread(status)
    except (requests.RequestException,ValueError) as exc: raise ValueError(str(exc))

@app.post('/api/robot/probe')
async def robot_probe():
    from .robot_link import status
    try: return await asyncio.to_thread(status,True)
    except Exception as exc: raise ValueError(str(exc))

@app.get('/api/robot/frame')
def robot_frame_config():
    from .robot_frame import load
    return {'calibration':load(),'robot_ready':False}

@app.post('/api/robot/frame')
async def robot_frame_save(request:Request):
    if actions.snapshot()['running']:raise ValueError('로봇 시퀀스를 STOP한 뒤 보정하세요.')
    from .robot_frame import save
    if engine.active or engine.monitor: raise ValueError('감시·분석을 중단한 뒤 보정하세요.')
    data=await request.json()
    return {'calibration':save(data.get('points')),'robot_ready':False}

@app.post('/api/robot/preview')
async def robot_target_preview(request:Request):
    from .robot_frame import transform
    data=await request.json()
    return transform(data.get('point'),float(data.get('approach_mm',80)))

@app.get('/api/robot/model')
def robot_model():
    from .kinematics import Model,NAMES
    model=Model();zero=model.forward([0]*5)
    return {'joint_names':NAMES,'joint_limits_radians':model.limits.tolist(),'model_sha256':model.hash,
        'zero_points_mm':zero['points'],'zero_tcp_mm':zero['position'].tolist(),
        'hardware_alignment':'unverified','motion_available':False}

@app.post('/api/robot/model/fk')
async def robot_model_fk(request:Request):
    from .kinematics import Model
    import numpy as np
    data=await request.json();model=Model();q=np.radians(data.get('joint_degrees',[]))
    if q.shape!=(5,) or not np.isfinite(q).all() or np.any(q<model.limits[:,0]) or np.any(q>model.limits[:,1]):
        raise ValueError('모델 관절각 5개를 허용 범위 안에서 입력하세요.')
    result=model.forward(q)
    return {'points_mm':result['points'],'position_mm':result['position'].tolist(),'motion_sent':False}

@app.post('/api/robot/model/ik')
async def robot_model_ik(request:Request):
    from .kinematics import preview
    data=await request.json()
    return await asyncio.to_thread(preview,data.get('point'),float(data.get('approach_mm',80)),bool(data.get('tool_down',False)))

@app.post('/api/coordinates')
async def coordinate_save(request:Request):
    if actions.snapshot()['running']:raise ValueError('로봇 시퀀스를 STOP한 뒤 좌표를 변경하세요.')
    from .coordinates import save
    if engine.active or engine.monitor: raise ValueError('감시·분석을 중단한 뒤 좌표 기준을 변경하세요.')
    config=save(await request.json())
    return {'ok':True,'config':config}

@app.post('/api/coordinates/point')
async def coordinate_point(request:Request):
    from .coordinates import convert
    data=await request.json();image,_,captured=engine.cameras['top'].snapshot()
    return dict(convert(image,data.get('point')),captured=captured)

@app.post('/api/target/locate')
async def locate_target(request:Request):
    data=await request.json();target_id=str(data.get('target_id',''))
    if target_id not in {i['id'] for i in engine.store.items()}:
        raise ValueError('등록 물품을 선택하세요.')
    if engine.active or engine.monitor or not engine.queue.empty():
        raise ValueError('감시와 진행 작업을 중단한 뒤 대상 찾기를 실행하세요.')
    image,seq,captured=engine.cameras['top'].snapshot()
    return engine.submit('analyze',image,source='top',frame_id=seq,captured=captured,
        target_id=target_id,with_features=True)

@app.post('/api/register')
async def register(request:Request):
    data=await request.json()
    result=engine.store.register(str(data.get('observation_id','')),int(data.get('index',-1)),
        str(data.get('item_id','')).strip(),str(data.get('name',''))[:100],str(data.get('notes',''))[:500],category=data.get('category'))
    engine.log('info','registry',f'관리자 등록 · {result["id"]} · '+('참조 사진 추가' if result['added_reference'] else '동일 참조 중복 제외'))
    return result

@app.post('/api/search')
async def search(request:Request):
    data=await request.json();category=data.get('category') or None
    if category and category not in CLASSES and category not in {i['category'] for i in engine.store.items()}: raise ValueError('검색 품목이 올바르지 않습니다.')
    if not engine.store.items(): raise ValueError('먼저 분석 결과에서 물품을 등록하세요.')
    image=image_input(data['data_url']) if data.get('data_url') else None
    text=str(data.get('text','')).strip()[:300]
    if image is None and not text: raise ValueError('검색 문장 또는 물건 사진이 필요합니다.')
    return engine.submit('search',image,source='search',text=text,category=category)


@app.get('/api/categories')
def categories():
    rows=CATEGORY_CATALOG.snapshot();ids={r['id'] for r in rows}
    for item in engine.store.items():
        if item['category'] not in ids:
            ids.add(item['category']);rows.append(dict(id=item['category'],name=item['category'],enabled=False,archived=True))
    return {'items':rows,'active_count':len(CLASSES)}


@app.get('/api/gripper-aperture')
def aperture_status():
    from .gripper_aperture import load,PERCENTS
    state=manual.snapshot();jaw=next((j for j in state.get('joints',[]) if j['name']=='gripper'),None)
    return {'profile':load(),'percents':PERCENTS,'connected':state.get('connected',False),
            'gripper_limits':[jaw['min_ticks'],jaw['max_ticks']] if jaw else None,'running':actions.snapshot()['running']}


@app.post('/api/gripper-aperture')
async def aperture_save(request:Request):
    from .gripper_aperture import save
    data=await request.json()
    if actions.snapshot()['running'] or manual.snapshot().get('active'):raise ValueError('로봇 동작 종료 후 측정값을 저장하세요.')
    jaw=next((j for j in manual.snapshot().get('joints',[]) if j['name']=='gripper'),None)
    if jaw:data['gripper_limits']=[jaw['min_ticks'],jaw['max_ticks']]
    save(data)
    return aperture_status()


@app.post('/api/gripper-aperture/open')
async def aperture_open(request:Request):
    from .gripper_aperture import ticks,PERCENTS
    from .robot_actions import fresh
    data=await request.json();percent=data.get('percent')
    if type(percent)!=int or percent not in PERCENTS:raise ValueError('표의 개방률을 선택하세요.')
    if actions.snapshot()['running']:raise ValueError('기존 동작을 종료하세요.')
    state=fresh()
    if state.get('latched') or state.get('active'):raise ValueError('정지 잠금을 해제하고 동작 종료 후 사용하세요.')
    def run():
        s=actions.check();jaw=next(j for j in s['joints'] if j['name']=='gripper')
        goal={j['name']:j['raw_ticks'] for j in s['joints']};goal['gripper']=ticks(percent,jaw['min_ticks'],jaw['max_ticks'])
        actions.move(goal,'개방 폭 실측 · 집게만%d%%'%percent,gripper_only=True)
    return actions.launch('aperture_measure',run)


@app.post('/api/categories')
async def category_update(request:Request):
    data=await request.json()
    if actions.snapshot()['running'] or manual.snapshot().get('active') or engine.active or engine.monitor or not engine.queue.empty():
        raise ValueError('감시·분석·로봇 작업을 종료한 뒤 카테고리를 변경하세요.')
    CATEGORY_CATALOG.change(data.get('operation','save'),data.get('item'),data.get('id'))
    engine.log('info','categories','카테고리 저장 완료 · 활성 %d개'%len(CLASSES))
    return categories()

# v0.2.54: top-view detector dataset (auto-labelled capture -> synthesis -> YOLO training)
from .detector_dataset import Capture as _DatasetCapture, EMPTY as _DATASET_EMPTY
dataset_capture=_DatasetCapture(engine)
dataset_training={'process':None,'log':None,'started':None}

def _dataset_classes():
    return [r['id'] for r in CATEGORY_CATALOG.snapshot() if r['enabled']]

def _training_state():
    p=dataset_training['process'];log=dataset_training['log']
    tail=''
    if log and Path(log).exists():
        tail=Path(log).read_text(encoding='utf-8',errors='replace')[-1500:]
    running=bool(p and p.poll() is None)
    return {'running':running,'returncode':None if p is None or running else p.returncode,'started':dataset_training['started'],'log_tail':tail}

@app.get('/api/dataset')
def dataset_state():
    from .detector_dataset import ROOT as DROOT
    summary=DROOT/'yolo'/'summary.json'
    meta=Path(__file__).resolve().parent.parent/'models'/'detector'/'meta.json'
    return {'capture':dataset_capture.status(),'classes':_dataset_classes(),'empty_id':_DATASET_EMPTY,
            'built':json.loads(summary.read_text(encoding='utf-8')) if summary.exists() else None,
            'training':_training_state(),'model':json.loads(meta.read_text(encoding='utf-8')) if meta.exists() else None}

@app.post('/api/dataset')
async def dataset_update(request:Request):
    data=await request.json();op=data.get('operation')
    if op=='start':
        class_id=data.get('class_id')
        if class_id!=_DATASET_EMPTY and class_id not in _dataset_classes():raise ValueError('수집할 카테고리를 선택하세요.')
        if actions.snapshot()['running']:raise ValueError('로봇 작업 중에는 수집할 수 없습니다.')
        return dataset_capture.start(class_id)
    if op=='stop':return dataset_capture.stop()
    if op=='build':
        if dataset_capture.status()['running']:raise ValueError('수집을 먼저 정지하세요.')
        from .detector_dataset import build
        return await asyncio.to_thread(build,_dataset_classes(),int(data.get('synthetic',1500)))
    if op=='train':
        import subprocess,sys,time as _t
        if _training_state()['running']:raise ValueError('이미 학습 중입니다.')
        from .detector_dataset import ROOT as DROOT
        DROOT.mkdir(parents=True,exist_ok=True);log=DROOT/'train.log'
        handle=open(log,'w',encoding='utf-8')
        dataset_training.update(process=subprocess.Popen([sys.executable,'-m','beta.detector_train',str(int(data.get('epochs',60)))],
            cwd=str(Path(__file__).resolve().parent.parent),stdout=handle,stderr=subprocess.STDOUT),log=str(log),started=_t.time())
        return _training_state()
    raise ValueError('지원하지 않는 데이터셋 작업')

@app.get('/api/dataset/preview.jpg')
def dataset_preview():
    from .detector_dataset import preview
    from .cameras import jpeg
    last=dataset_capture.status().get('last')
    if not last:raise HTTPException(404,'저장된 수집 사진 없음')
    return Response(jpeg(preview(last['path'],last['boxes'])),media_type='image/jpeg',headers={'Cache-Control':'no-store'})

@app.get('/api/export')
def export():
    payload={'version':'0.1.0-beta','registry':engine.store.items(),'observations':engine.store.observations(1000),
        'note':'개인 로컬 자료. 후보 점수는 확률/확정 개체 일치가 아닙니다.'}
    return Response(json.dumps(payload,ensure_ascii=False,indent=2),media_type='application/json',
        headers={'Content-Disposition':'attachment; filename="vision-beta-export.json"'})
