"""준비자세→새 검출→좌표/방향→접근→영상 닫기→확인 들기의 베타 연결."""
import json
import copy
import math
from pathlib import Path
import time
import uuid
import cv2
import numpy as np
from .config import DATA,MEDIA
from .coordinates import geometry,convert
from .robot_frame import transform,load as frame_config
from .kinematics import Model,NAMES
from .grasp_geometry import pink_tube
from .finger_edges import edges
from .grasp_alignment import measure as measure_alignment,open_jaw_clearance,draw_clearance,load_fixed_finger,measure_visible_side
from .approach_path import plan_path,pose as measured_pose,context as model_context,SIGN
from .local_grasp_correction import offset as local_grasp_offset, at_target
from .grasp_contact import verify_lift
from .robot_actions import actions,fresh,validate_goal,ALL,read_home
from .manual_control import manual
from .position_diagnostics import compare_positions,from_report
from .coarse_grasp import fixed_gap,correct_gap,object_alignment,anchor_plan
from .object_reference import build_reference
from .lift_tracking import LiftTracker
from .gap_motion import lateral_feedback_move
from .stage_motion import checked_stage_move
from .view_clearance import needs_view,view_heights,validate_view_path
from .following_compensation import move_with_compensation
from .grasp_reference import contact_reference
from .gripper_aperture import choose as choose_aperture,ticks as aperture_ticks,contact_ticks
from .return_path import plan_dropoff,DEFAULT_HANG_MM
from .partial_boundary import topview_clearance,side_free_mm
from .gap_observation import GapObserver,shared_clearance,ensure_fixed_clearance,fixed_passed
from .gap_learning import context_key,slope_state,mark_suspect,confirm_key,save_slope,offset_amount,apply_offset,learn_offset
from . import floor_descent
from .orientation_alignment import apply_alignment
from .workflow import load as workflow_settings
from .board_correction import corrected as board_corrected
from . import descent_shift
# v0.2.37: no fixed extra depth; wide items descend to the normal grasp height and
# then step down until the fingertips actually touch the board (FK board height is
# several mm off: user saw 'still short' at 2mm under the modelled board).
WIDE_FLAT_MM=60.;WIDE_DEEPER_MM=0.  # floor ladder constants live in floor_descent.py (v0.2.41)


def pick_target(objects,target_id):
    """Top-view object for a searched registered item (highest matching score)."""
    ranked=[]
    for o in objects:
        candidate=next((v for v in o.get('candidates',[]) if v['id']==target_id),None)
        if candidate:ranked.append((candidate['matching_score'],o))
    if not ranked:raise ValueError('검색된 등록 물품에 대응하는 탑뷰 후보가 없습니다.')
    best_score,best=max(ranked,key=lambda p:p[0])
    # v0.2.53 (flow-a12c91eb): 'sandisk_usb' went to another USB whose own best match
    # was axxen_usb (0.845 vs 0.731). Never grasp an object that clearly looks more
    # like a DIFFERENT registered item; ask for a better search instead.
    # Only a rival of the SAME category counts (a USB that looks more like another USB);
    # a phone/lip balm scoring higher on a USB crop is not a mix-up risk (v0.2.62).
    target_category=next(v.get('category') for v in best.get('candidates',[]) if v['id']==target_id)
    rival=max((v for v in best.get('candidates',[]) if v['id']!=target_id and v.get('category')==target_category),key=lambda v:v['matching_score'],default=None)
    if rival and rival['matching_score']-best_score>.05:
        raise ValueError('대상 불확실 · 가장 비슷한 탑뷰 물품(%s)이 %s(%.2f)보다 %s(%.2f)에 더 가깝습니다. 사진·설명을 보강하거나 등록 사진을 추가하세요.'%(
            best.get('category','?'),target_id,best_score,rival['id'],rival['matching_score']))
    return best


def make_plan(image,result,target_id=None,approach_height=45,grasp_height=5,*,simple_mode=False):
    """No hardware access: all geometry comes from this detection frame."""
    c,points,_=geometry(image)
    if c['mode']!='aruco' or not c['width_mm']:raise ValueError('실제 ArUco와 치수 설정이 필요합니다.')
    objects=[o for o in result['items'] if o.get('quality')=='accepted']
    if target_id:objects=[pick_target(objects,target_id)]
    if len(objects)!=1:raise ValueError('집을 대상을 사진·설명으로 하나 선택하세요.')
    obj=objects[0];bbox=list(map(int,obj['bbox']))
    color,shape=build_reference(image,bbox)
    x,y=shape['grasp_center_pixels'];center=[x+bbox[0],y+bbox[1]]
    if simple_mode:center=[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2]
    segment=np.asarray(shape['long_axis_segment'])+bbox[:2]
    board=convert(image,center)
    if not board['inside'] or board['temporary']:raise ValueError('대상이 실제 마커 영역 안에 없습니다.')
    ends=[convert(image,p)['mm'] for p in segment]
    a=transform(ends[0],20)['surface_mm'];b=transform(ends[1],20)['surface_mm']
    vector=np.asarray(b)-a;angle=float(math.atan2(vector[1],vector[0])%math.pi)
    # The tested baseline +90deg encoder rotation aligns jaws across a
    # forward-pointing tube. Rotate according to the detected long axis.
    angle=(angle+math.pi/2)%math.pi-math.pi/2
    # Measure the SHORT OBB edge itself, and project both endpoints to the
    # robot plane. Do not confuse image vertical with robot down or jaw opening.
    box=np.asarray(shape['box_pixels'])+bbox[:2]
    vectors=np.roll(box,-1,axis=0)-box
    short_index=int(np.argmin(np.linalg.norm(vectors,axis=1)))
    short_segment=[box[short_index],box[(short_index+1)%4]]
    short_robot=[transform(convert(image,p)['mm'],20)['surface_mm'] for p in short_segment]
    short_vector=np.asarray(short_robot[1])-short_robot[0]
    opening_yaw=float(math.atan2(short_vector[1],short_vector[0]))
    color['complete_outline']=True
    color['physical_size_mm']={'width':float(np.linalg.norm(short_vector)),'length':float(np.linalg.norm(vector)/.7)}
    aperture=choose_aperture(float(np.linalg.norm(short_vector)),grasp_height)
    strip_margin=max(3.,float(aperture['width_mm'] or (np.linalg.norm(short_vector)+12))-float(np.linalg.norm(short_vector)))
    color['neighbor_clearance']=topview_clearance(image,box,box[(short_index+1)%4]-box[short_index],float(np.linalg.norm(short_vector)),strip_margin)
    # Free space beyond each long edge; 'positive' = +short_vector (robot frame).
    side_space=side_free_mm(image,box,box[(short_index+1)%4]-box[short_index],float(np.linalg.norm(short_vector)))
    color['opening_percent']=aperture['percent']
    color['aperture_revision']=aperture['revision']
    reference=json.loads((DATA/'working_calibration.json').read_text(encoding='utf-8'))
    model=Model()
    if reference['model_sha256']!=model.hash or reference['robot_frame']!=frame_config():
        raise ValueError('임시 정합과 현재 모델/보관함 설정이 다릅니다.')
    reference=apply_alignment(reference)
    # User-reported top-view position correction (board_correction.json); the
    # detected board_mm is kept unchanged for re-fitting.
    target_mm,board_fix=board_corrected(board['mm'])
    measured=transform(target_mm,approach_height)
    grasp=transform(target_mm,20)['surface_mm'];grasp[2]+=grasp_height
    # Flat wide items (phone ~8mm thick): fingertips at 5mm overlapped only ~3mm of the
    # edge; user asked 5mm deeper (2026-11-11). Keep 1mm above the board surface.
    # User again (19:55): 'fit exactly' at 1mm and 3mm deeper is fine -> 7mm below the\r
    # setting (setting 5mm -> 2mm under the computed board plane; the plane/TCP model\r
    # sits slightly high in reality).\r
    if float(np.linalg.norm(short_vector))>=WIDE_FLAT_MM:grasp[2]-=WIDE_DEEPER_MM
    lift=list(measured['approach_mm'])
    roll=reference['reference_model_radians'][4]-math.pi/2+angle
    return {'detection_id':result['id'],'captured':result['captured'],'frame_id':result['frame_id'],
        'opening_selection':aperture,'neighbor_clearance':color['neighbor_clearance'],'side_space':side_space,'target_color':color,'target_id':target_id,'category':obj['category'],'bbox':bbox,'center_pixels':center,'board_mm':board['mm'],'board_target_mm':target_mm,'board_correction':board_fix,
        'axis_reliable':shape.get('axis_reliable',True),'geometry_method':shape.get('method'),
        'short_axis_width_mm':float(np.linalg.norm(short_vector)), 'short_axis_robot_radians':opening_yaw,'short_axis_pixels':[p.tolist() for p in short_segment],'long_axis_robot_radians':angle,'fixed_roll_radians':roll,'approach_xyz_mm':measured['approach_mm'],
        'grasp_xyz_mm':grasp,'verification_lift_xyz_mm':lift,'marker_corners_pixels':points.tolist(),
        'reference':reference,'temporary_calibration':not bool(model.position_calibration),'grasp_success':False,
        'note':'품목 제한 없는 선택 물품 외형 기반 집기 · 높이는 설정값이며 실제 파지 결과는 별도 확인'}


def joints_for(plan,xyz,s,gripper):
    reference=plan['reference'];model=Model(opening_axis_local=reference.get('opening_axis_local'));by={j['name']:j for j in s['joints']}
    raw=np.array([by[n]['raw_ticks'] for n in NAMES]);r=np.asarray(reference['reference_raw_ticks']);q0=np.asarray(reference['reference_model_radians']);sign=SIGN
    # Solve within BOTH the URDF and the actual calibrated encoder bounds.
    # Previously IK used only URDF limits, then rejected the selected solution.
    bounds=np.asarray([[by[n]['min_ticks'],by[n]['max_ticks']] for n in NAMES])
    mapped=q0[:,None]+(bounds-r[:,None])*sign[:,None]*2*np.pi/4096
    model.limits[:,0]=np.maximum(model.limits[:,0],mapped.min(axis=1))
    model.limits[:,1]=np.minimum(model.limits[:,1],mapped.max(axis=1))
    if np.any(model.limits[:,0]>=model.limits[:,1]):raise ValueError('실측 보정 범위와 모델 축 정합을 확인해야 합니다.')
    seed=q0+(raw-r)*sign*2*np.pi/4096
    solution=None
    for down_weight in ([15,5] if plan.get('relaxed') else [60]):
        candidate=model.inverse(xyz,seed=seed,tool_down=True,fixed_roll=plan['fixed_roll_radians'],
                                down_weight=down_weight,max_down_deg=plan.get('max_tilt_deg') or (10 if plan.get('relaxed') else 5))
        if candidate['reachable_in_model']:
            solution=candidate
            break
    if solution is None:
        raise ValueError('검출 위치/방향의 IK 해를 찾지 못했습니다.')
    values=np.rint(r+(np.asarray(solution['joint_radians'])-q0)*sign*4096/(2*np.pi)).astype(int)
    target={n:int(values[i]) for i,n in enumerate(NAMES)};target['gripper']=int(gripper);validate_goal(target,s)
    return target


def model_roll(reference,raw_ticks):
    """wrist_roll encoder ticks -> model radians, using the single shared SIGN."""
    return reference['reference_model_radians'][4]+(raw_ticks-reference['reference_raw_ticks'][4])*SIGN[4]*2*math.pi/4096


def corrected_model_roll(reference,raw_ticks,image_error_deg):
    # Physical rule (trials 51bf9438, f4d4a1d6): +encoder ticks increase the ARM
    # image axis angle, so a positive image error needs fewer encoder ticks.
    return model_roll(reference,raw_ticks)-SIGN[4]*math.radians(image_error_deg)


def visual_rotation_target(plan,state,gripper,adjustment_deg,plane_z,held_goal,max_tilt_deg=10):
    """One closed-jaw rotation at the reached approach pose: wrist_roll only.

    Shoulder/elbow/wrist_flex keep their last COMMANDED ticks (held_goal). Re-solving
    IK here moved shoulder_lift by -37 ticks, which then sagged 35 ticks under load
    and dropped the TCP ~10mm (trial f4d4a1d6). The TCP sits ~8mm off the roll
    axis, so a <=45deg roll-only turn shifts it by up to ~6mm; descent IK re-solves
    the grasp position with the new roll afterwards.
    """
    reference=plan['reference'];model,q,r,q0=model_context(reference,state)
    start=model.forward(q)['position'];roll=next(j['raw_ticks'] for j in state['joints'] if j['name']=='wrist_roll')
    # Empirical wrist-camera polarity, trial 51bf9438: encoder +44deg
    # increased image axis 134deg -> 180deg. To reduce image error,
    # decrease encoder angle (see corrected_model_roll).
    goal={n:int(held_goal[n]) for n in NAMES[:4]}
    goal['wrist_roll']=int(round(roll-adjustment_deg*4096/360));goal['gripper']=int(gripper)
    validate_goal(goal,state)
    end=q0+(np.array([goal[n] for n in NAMES])-r)*SIGN*2*np.pi/4096
    # v0.2.45 B1: only plane+20 and the shared stage tilt stop. XY/height drift of the
    # roll-only path mixes in shoulder sag and is recorded as a warning (f1f0c3c7).
    worst_xy=worst_dz=0.
    for t in np.linspace(0,1,41):
        f=model.forward(q+(end-q)*t)
        worst_xy=max(worst_xy,float(np.linalg.norm(f['position'][:2]-start[:2])));worst_dz=max(worst_dz,float(abs(f['position'][2]-start[2])))
        if f['position'][2]<plane_z+20 or -f['tool_axis'][2]<math.cos(math.radians(max_tilt_deg)):
            raise ValueError('현재 높이에서 손목 회전 경로가 판+20mm 또는 기울기 %.0f° 조건을 만족하지 못했습니다.'%max_tilt_deg)
    info={'start_xyz_mm':start.tolist(),'adjustment_deg':float(adjustment_deg),'target':goal,'method':'closed_jaw_roll_only_at_current_approach',
          'max_tilt_deg':float(max_tilt_deg),'path_xy_drift_mm':worst_xy,'path_z_drift_mm':worst_dz}
    if worst_xy>8 or worst_dz>5:info['warning']='회전 경로 위치 변화 XY %.1fmm / 높이 %.1fmm (경고만)'%(worst_xy,worst_dz)
    return goal,info


class GraspFlow:
    def __init__(self,engine):
        self.engine=engine;self.latest_plan=None;self.position_diagnostic=None
        reports=sorted((DATA/'grasp_trials').glob('*/report.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        if reports:
            try:
                previous=json.loads(reports[0].read_text(encoding='utf-8'))
                self.position_diagnostic=previous.get('position_diagnostic') or from_report(previous)
            except (ValueError,KeyError,TypeError,OSError):pass


    def _transfer_to_dropoff(self,actions,reference,plane,workflow,record,lift_goal,grip,half,opening_selection,photo,save):
        """v0.2.46: rise to the transfer height, travel above the taught drop pose, descend
        straight down, open, rise straight back up, HOME. Everything is planned before
        the first move; an infeasible plan keeps holding the object in place.
        """
        drop=workflow['dropoff_pose']['ticks']
        state=actions.check();model,_,r,q0=model_context(reference,state)
        bounds={j['name']:(j['min_ticks'],j['max_ticks']) for j in state['joints']}
        home=read_home()['raw_ticks']
        for ticks in [drop,home]:validate_goal(dict({n:int(ticks[n]) for n in NAMES},gripper=grip),state)
        try:
            plan=plan_dropoff(model,r,q0,{n:int(lift_goal[n]) for n in NAMES},drop,home,plane,
                              record.get('hang_mm',DEFAULT_HANG_MM),workflow['transfer_height_mm'],bounds)
        except ValueError as exc:
            record['dropoff_plan']={'ok':False,'reason':str(exc)};save()
            actions.log('return_pending','놓기 이송 계획 불가 · 물품 유지 · '+str(exc));return
        moves=plan.pop('moves');record['dropoff_plan']=plan;save()
        actions.log('dropoff','놓기 계획 · 이송 높이 %.0fmm · 중간점 %d개'%(plan['transfer_z_mm']-plane,plan['travel_points']),plan=plan)
        def arm(ticks,jaw):return dict({n:int(ticks[n]) for n in NAMES},gripper=jaw)
        if not plan['lift'].get('skipped'):actions.move(arm(moves['lifted'],grip),'이송 높이까지 %.0fmm 수직 상승 · 물품 유지'%plan['lift']['lift_mm'])
        for i,ticks in enumerate(moves['travel']):actions.move(arm(ticks,grip),'이송 중간점 %d/%d'%(i+1,len(moves['travel'])))
        actions.move(arm(moves['above'],grip),'놓기 위치 위로 이동 · 물품 유지')
        if not plan['above_drop'].get('skipped'):actions.move(arm(moves['drop'],grip),'놓기 위치로 %.0fmm 수직 하강'%plan['above_drop']['lift_mm'])
        current=actions.check();release={j['name']:j['raw_ticks'] for j in current['joints']};release['gripper']=half
        actions.move(release,'놓기 위치에서 집게 %d%% 개방'%opening_selection['percent'],gripper_only=True)
        time.sleep(.5);photo('after-release')
        if not plan['above_drop'].get('skipped'):actions.move(arm(moves['above'],half),'놓은 뒤 수직 상승')
        actions.move(arm(moves['home'],half),'놓기 완료 · HOME 복귀')
        record['result']='놓기 완료 · HOME 복귀';record['returned']=True;save()
        actions.log('complete',record['result'])

    def start(self,search_job_id=None,approach_height=45,grasp_height=5,*,measure_only=False,relaxed=False,simple_mode=True):
        if actions.snapshot()['running']:raise ValueError('기존 시퀀스를 STOP하고 종료를 기다리세요.')
        if not 30<=approach_height<=100 or not 5<=grasp_height<=30:raise ValueError('접근 높이 30~100mm, 집기 높이 5~30mm 범위입니다.')
        s=fresh();home=read_home()
        if not home:raise ValueError('HOME 준비자세를 먼저 저장하세요.')
        target=dict(home['raw_ticks']);validate_goal(target,s)
        self.engine.set_monitor(False,'top')
        target_id=None
        if search_job_id:
            job=next((j for j in self.engine.jobs if j['id']==search_job_id and j['kind']=='search' and j['status']=='complete'),None)
            if not job or not job.get('search_result',{}).get('candidates'):raise ValueError('완료된 글·사진 검색 결과가 필요합니다.')
            selected=job['search_result']['candidates'][0]
            target_id=selected['id']
        if s['latched']:manual.send('resume')
        return actions.launch('grasp',lambda:self.run(target_id,approach_height,grasp_height,measure_only,relaxed,simple_mode))

    def run(self,target_id,approach_height,grasp_height,measure_only=False,relaxed=False,simple_mode=True):
        workflow=workflow_settings()
        relaxed=relaxed or simple_mode
        run_id=actions.snapshot()['run_id'];folder=DATA/'grasp_trials'/('flow-'+run_id);folder.mkdir(parents=True)
        record={'id':run_id,'started':time.time(),'target_id':target_id,'success':False,'events':[],'simple_mode':simple_mode}
        def save():
            temp=folder/'report.tmp';temp.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(folder/'report.json')
        def photo(label,key='arm'):
            image,seq,captured=self.engine.cameras[key].snapshot();image.save(folder/(label+'.jpg'));record['events'].append({'phase':label,'camera':key,'frame_id':seq,'captured':captured});save();return image
        plan=None;gap_session={}
        from . import arm_roi
        def arm_box():
            # v0.2.69: ARM detector box (tracked per frame) limits every target outline.
            ref=(plan or {}).get('target_color');ff=ref.get('fixed_finger') if isinstance(ref,dict) else None
            inner=float(np.asarray(ff['contour'])[:,0].max()) if ff else None
            try:return arm_roi.ensure(self.engine,actions.cancel,target_id,inner,lambda d:(record.setdefault('arm_roi',[]).append(d),save()))
            except Exception as exc:
                record.setdefault('arm_roi',[]).append({'arm_roi':'error','error':str(exc)});save();return None
        try:
            arm_roi.activate(self.engine.cameras['arm'])
            deadline=time.monotonic()+120
            while self.engine.active or not self.engine.queue.empty():
                if actions.cancel.is_set():raise ValueError('STOP으로 시작 대기 취소')
                if time.monotonic()>deadline:raise ValueError('진행 분석 종료 대기 시간 초과')
                actions.cancel.wait(.2)
            s=actions.check();home=read_home();target=dict(home['raw_ticks'])
            actions.home_move(target)
            # Capture only after the prepared pose is reached; do not reuse latest.
            actions.log('detecting','준비자세 도착 후 새 프레임으로 검출·특징 분석')
            image,seq,captured=self.engine.cameras['top'].snapshot();image.save(folder/'detection-source.jpg')
            job=self.engine.submit('analyze',image.copy(),source='top',frame_id=seq,captured=captured,with_features=False)
            deadline=time.monotonic()+120
            while job['status'] not in ['complete','failed','cancelled']:
                # submit returns a public snapshot, not the worker's mutable job.
                # Re-read the matching live record instead of waiting on that copy.
                with self.engine.lock:
                    current=next((j for j in self.engine.jobs if j['id']==job['id']),None)
                    if current is None:raise ValueError('해당 분석 작업 기록을 찾지 못했습니다.')
                    job=copy.deepcopy(current)
                if job['status'] in ['complete','failed','cancelled']:break
                # Loading a large local model can pause Python readers briefly.
                # No robot command is sent during this stationary analysis wait.
                # Require fresh feedback again before ANY subsequent movement.
                if actions.cancel.is_set():raise ValueError('STOP으로 분석 대기 취소')
                state=manual.snapshot()
                if not state['connected'] or state['latched']:raise ValueError('분석 중 장비 연결 종료 또는 정지 잠금')
                if time.monotonic()>deadline:raise ValueError('검출·특징 분석 시간 초과')
                actions.cancel.wait(.15)
            if job['status']!='complete':raise ValueError('새 분석 실패: '+job.get('message',''))
            feedback_deadline=time.monotonic()+8
            while True:
                if actions.cancel.is_set():raise ValueError('STOP으로 취소됨')
                state=manual.snapshot()
                if not state['connected'] or state['latched']:raise ValueError('분석 후 장비 연결 종료 또는 정지 잠금')
                if state['age'] is not None and state['age']<=.8:break
                if time.monotonic()>feedback_deadline:raise ValueError('분석 후 최신 관절 피드백 복구 시간 초과')
                actions.cancel.wait(.1)
            plan=make_plan(image,job['result'],target_id,approach_height,grasp_height,simple_mode=simple_mode)
            plan['relaxed']=relaxed
            self.latest_plan={k:v for k,v in plan.items() if k!='reference'};record['plan']=self.latest_plan;save()
            actions.log('planning','새 검출 좌표·긴 축으로 접근/하강 목표 계산',plan=self.latest_plan)
            s=actions.check();jaw=next(j for j in s['joints'] if j['name']=='gripper')
            opening_selection=plan['opening_selection']
            if opening_selection['verified'] and opening_selection['gripper_limits']!=[jaw['min_ticks'],jaw['max_ticks']]:
                raise ValueError('그리퍼 틱 범위가 개방 폭 실측 때와 다릅니다. 다시 측정하세요.')
            half=aperture_ticks(opening_selection['percent'],jaw['min_ticks'],jaw['max_ticks'])
            actions.log('opening_selection','선택 개방률 %d%% · %s'%(opening_selection['percent'],('실측 폭 확인'+(' · '+opening_selection['warning'] if opening_selection.get('warning') else '')) if opening_selection['verified'] else opening_selection['warning']),opening=opening_selection)
            # Resolve all stage targets before the first approach command.
            current_grip=next(j['raw_ticks'] for j in s['joints'] if j['name']=='gripper')
            goals=[None,None,None]
            # Marker geometry must still match before moving into the bin.
            deadline=time.monotonic()+3;last_seq=None
            while True:
                actions.check()
                now,seq,_=self.engine.cameras['top'].snapshot()
                if seq==last_seq:
                    if time.monotonic()>deadline:raise ValueError('이동 전 마커 재확인 시간 초과')
                    actions.cancel.wait(.1);continue
                last_seq=seq
                try:
                    _,corners,_=geometry(now)
                    break
                except ValueError as exc:
                    if not str(exc).startswith('기준 마커 부족:'):raise
                    if time.monotonic()>deadline:raise ValueError('이동 전 3초 재확인 실패 · '+str(exc)) from exc
                    actions.log('markers','이동 전 마커 재확인 · '+str(exc))
                    actions.cancel.wait(.15)
            if np.max(np.abs(corners-np.asarray(plan['marker_corners_pixels'])))>8:raise ValueError('보관함/카메라가 움직였습니다. 새 검출이 필요합니다.')
            reference=plan['reference']
            s=actions.check()
            # A verified common TCP model supersedes legacy per-location offsets.
            common_profile=Model().position_calibration
            correction=None if simple_mode or common_profile else at_target(plan)
            record['position_calibration']={'mode':'common_tcp' if common_profile else 'legacy_provisional',
                                            'profile_id':common_profile['id'] if common_profile else None}
            roll_window=None
            if correction:
                for key in ['approach_xyz_mm','grasp_xyz_mm','verification_lift_xyz_mm']:
                    plan[key]=(np.asarray(plan[key])+correction['robot_delta_mm']).tolist()
                roll_window=(correction['anchor_roll_ticks'],correction['roll_tolerance_ticks'])
                record['local_grasp_correction']=correction
            elif not reference.get('orientation_alignment') and not simple_mode and not common_profile and np.linalg.norm(np.asarray(plan['board_mm'])-[234.4,101.0])<=25:
                # The central wrist view showed a quarter-turn mismatch with
                # the opening-axis calibration fitted at the right-hand pose.
                reference=dict(reference,opening_axis_local=[1,0,0])
                plan['reference']=reference
                plan['opening_axis_calibration']='central_observed'
                roll_window=(3074,200)
            plane=transform(plan['board_mm'],20)['surface_mm'][2]
            gap_key=context_key(self.engine.cameras['arm'].state(),s)
            frame_size=self.engine.cameras['arm'].state().get('frame_size') or [640,480]
            slope_info=slope_state(gap_key,approach_height,frame_size);learned_slope=slope_info['slope']
            record['visual_gap_slope_state']=slope_info
            if slope_info['reconfirm']:
                actions.log('gap_reconfirm','좌표 기준(관절 방향·벌림축·기준 자세) 변경 · 학습 기울기 크기 사용, 하강 전 영상으로 방향 재확인')
            # Put the fixed finger on the freer side (wrist 0/180 deg branch).
            # Pre-offset moves the closed jaw along opening_axis*sign(slope), and the
            # fixed finger lands on that side, so choose the signed opening axis.
            # Only intervene when a side is actually tight; with room on both sides
            # keep the previous seed-nearest branch so proven small-object runs keep
            # the same wrist roll.
            base_tilt=10 if relaxed else 5
            def choose_route(tilt):
                side=plan.get('side_space');route=None
                tight=bool(side) and min(side['positive_mm'],side['negative_mm'])<30
                if tight and learned_slope is not None and plan.get('axis_reliable',True):
                    unit=np.array([math.cos(plan['short_axis_robot_radians']),math.sin(plan['short_axis_robot_radians']),0.])
                    order=sorted([(side['positive_mm'],1),(side['negative_mm'],-1)],key=lambda p:-p[0])
                    last_error=None
                    for rank,(free,sign) in enumerate(order):
                        desired=unit*sign*np.sign(learned_slope)
                        try:
                            route=plan_path(reference,s,plan['approach_xyz_mm'],plane,opening_yaw=math.atan2(desired[1],desired[0]),
                                            opening_direction=desired,roll_window=roll_window,relaxed=relaxed,max_tilt_deg=tilt)
                        except ValueError as exc:
                            last_error=exc;continue
                        record['fixed_side']={'side':'positive' if sign>0 else 'negative','free_mm':free,
                                              'other_free_mm':order[1-rank][0],'fallback':rank>0,**side}
                        actions.log('fixed_side','고정 손가락 쪽 선택 · 빈 공간 %.0fmm (반대쪽 %.0fmm)%s'%(free,order[1-rank][0],' · 넓은 쪽 경로 불가로 반대쪽' if rank else ''))
                        break
                    if route is None:raise last_error
                else:
                    route=plan_path(reference,s,plan['approach_xyz_mm'],plane,opening_yaw=plan['short_axis_robot_radians'] if plan.get('axis_reliable',True) else None,roll_window=roll_window,relaxed=relaxed,max_tilt_deg=tilt)
                return route
            try:route=choose_route(base_tilt);tilt=base_tilt
            except ValueError as exc:
                if 'IK' not in str(exc) and '접근 자세를 계산할 수 없습니다' not in str(exc):raise
                # Far board cells (~29cm, wrist_flex at its limit) need ~11 deg tilt at
                # approach height. Retry once with up to 15 deg, only when vertical fails.
                try:
                    route=choose_route(15);tilt=15
                    record['far_tilt']={'max_tilt_deg':tilt,'reach_mm':float(math.hypot(*plan['approach_xyz_mm'][:2]))}
                    actions.log('far_tilt','먼 위치 · 수직 접근 불가로 집게 기울기 최대 15° 허용')
                except ValueError as far_exc:
                    # The closed-jaw CENTRE may be out of reach while the offset target
                    # (fixed finger toward the robot) is reachable (flow-84812dda: phone
                    # centre 282mm). Decide reach at the offset targets below.
                    route=None;center_error=far_exc;tilt=base_tilt
                    record['center_unreachable']={'reach_mm':float(math.hypot(*plan['approach_xyz_mm'][:2]))}
            plan['max_tilt_deg']=tilt
            # Following-compensation path check: 10 deg normally, 18 for far tilted cells.
            # Wrist at its mechanical stop (3286, probed) cannot hold vertical under sag.
            wrist_at_stop=route is not None and route['waypoints'][-1]['target']['wrist_flex']>=next(j['max_ticks'] for j in s['joints'] if j['name']=='wrist_flex')-10
            stage_tilt=18 if (record.get('far_tilt') or wrist_at_stop) else 10
            # The signed tool axis is now fixed; offset planning keeps that same branch.
            offset=offset_amount(plan['short_axis_width_mm'],learned_slope,workflow,gap_key)
            calibration_stop=bool(workflow.get('calibration_stop'))
            if calibration_stop:
                # Position calibration: send the CLOSED-jaw centre to the object centre
                # (no pre-offset) so the user can report centre-to-centre error.
                offset=dict(offset,signed_mm=0.,calibration_stop=True)
            if route is None and not offset['signed_mm']:raise center_error
            if offset['signed_mm']:
                if route is not None:
                    direction=np.asarray(route['waypoints'][-1]['opening_axis']);direction[2]=0;direction/=np.linalg.norm(direction)
                else:
                    # No centre route: start with the short-axis direction whose offset
                    # target is closer to the robot base; the loop also tries the other.
                    u=np.array([math.cos(plan['short_axis_robot_radians']),math.sin(plan['short_axis_robot_radians']),0.])
                    base_xy=np.asarray(plan['approach_xyz_mm'][:2],float)
                    reach=lambda v:np.linalg.norm(base_xy+v[:2]*offset['signed_mm'])
                    direction=u if reach(u)<=reach(-u) else -u
                    actions.log('far_tilt','물체 중심은 팔이 닿지 않음 · 사전 오프셋 위치(로봇 쪽)로 직접 계획')
                # The pre-offset can push a far cell out of reach (flow-83366abb: phone at
                # 278mm + ~30mm outward). Try the same side with 15 deg tilt, then the
                # other fixed-finger side (wrist 180 deg, offset toward the robot).
                keys=['approach_xyz_mm','grasp_xyz_mm','verification_lift_xyz_mm']
                unshifted={k:list(plan[k]) for k in keys};last_error=None
                attempts=[(direction,tilt,False)]+([(direction,15,False)] if tilt<15 else [])
                attempts+=[(-direction,tilt,True)]+([(-direction,15,True)] if tilt<15 else [])
                for dvec,t,flipped in attempts:
                    plan.update({k:list(v) for k,v in unshifted.items()})
                    apply_offset(plan,dvec,offset)
                    try:
                        route=plan_path(reference,s,plan['approach_xyz_mm'],plane,opening_yaw=math.atan2(dvec[1],dvec[0]),
                                        opening_direction=dvec,roll_window=roll_window,relaxed=relaxed,max_tilt_deg=t)
                    except ValueError as exc:
                        last_error=exc;continue
                    if t>tilt:
                        tilt=plan['max_tilt_deg']=t;stage_tilt=18
                        record['far_tilt']={'max_tilt_deg':t,'reach_mm':float(math.hypot(*plan['approach_xyz_mm'][:2])),'after_offset':True}
                        actions.log('far_tilt','사전 오프셋 위치가 멀어 집게 기울기 최대 15° 허용')
                    if flipped:
                        record['offset_side_flipped']=True
                        if record.get('fixed_side'):record['fixed_side']=dict(record['fixed_side'],side={'positive':'negative','negative':'positive'}.get(record['fixed_side']['side']),flipped_for_reach=True)
                        actions.log('fixed_side','사전 오프셋 위치에 팔이 닿지 않아 고정 손가락을 반대쪽으로 변경')
                    break
                else:raise last_error
            else:plan['preoffset']=dict(offset,direction=route['waypoints'][-1]['opening_axis'])
            # v0.2.45 B9: descent/lift IK pre-check before ANY motion (was only in the
            # correction branch, so a far cell could fail IK after the approach moves).
            predicted=copy.deepcopy(s)
            for joint in predicted['joints']:
                joint['raw_ticks']=route['waypoints'][-1]['target'][joint['name']]
            check_plan=dict(plan)
            roll=route['waypoints'][-1]['target']['wrist_roll']
            check_plan['fixed_roll_radians']=model_roll(reference,roll)
            for key,label in [('grasp_xyz_mm','하강'),('verification_lift_xyz_mm','검증 상승')]:
                try:joints_for(check_plan,plan[key],predicted,half)
                except ValueError as exc:
                    raise ValueError('%s IK 사전 확인 실패 · 목표 %s · 기울기 %.0f° · 이동 전 중단 (%s)'%(label,[round(float(v),1) for v in plan[key]],plan['max_tilt_deg'],exc))
            record['ik_precheck']={'grasp':True,'lift':True,'max_tilt_deg':plan['max_tilt_deg'],'stage_tilt_deg':stage_tilt}
            self.latest_plan={k:v for k,v in plan.items() if k!='reference'}
            record['plan']=self.latest_plan
            record['approach_route']=route;save()
            actions.log('path','현재 관절 FK → 목표 IK → 경로 높이·방향 사전 검사 완료',route=route)
            for index,waypoint in enumerate(route['waypoints']):
                validate_goal(waypoint['target'],actions.check())
                final=index==len(route['waypoints'])-1
                try:
                    if final:
                        checked_stage_move(actions,reference,waypoint['target'],f'계산 경로 접근 {index+1}/{len(route["waypoints"])}',
                            waypoint['xyz_mm'],plane,log=lambda data:(record.setdefault('stage_following',[]).append(data),save(),actions.log('stage_following','마지막 접근 · 정지/추종/FK 확인',result=data)),max_tilt_deg=stage_tilt)
                    else:
                        actions.move(waypoint['target'],f'계산 경로 접근 {index+1}/{len(route["waypoints"])}',arrival_tolerance_ticks=46,target_height_mm=waypoint['xyz_mm'][2])
                finally:
                    if final:
                        feedback=manual.snapshot()
                        if feedback.get('connected') and feedback.get('age') is not None and feedback['age']<.8:
                            actual=measured_pose(reference,feedback)
                            errors={j['name']:j['raw_ticks']-waypoint['target'][j['name']] for j in feedback['joints']}
                            diagnostic=compare_positions(plan['approach_xyz_mm'],waypoint['xyz_mm'],actual['xyz_mm'],joint_errors=errors)
                            diagnostic.update(trial_id=record['id'],captured=time.time())
                            self.position_diagnostic=record['position_diagnostic']=diagnostic;save()
                            actions.log('position','위치 오차 분리 · IK %.1fmm / 관절 추종 %.1fmm / 실물 정합 미확인'%(diagnostic['ik_error']['distance_mm'],diagnostic['following_error']['distance_mm']),diagnostic=diagnostic)
                actions.log('pose','실제 관절 피드백의 집게 위치·방향',pose=measured_pose(reference,actions.check()))
            actual_pose=measured_pose(reference,actions.check())
            if not plan.get('axis_reliable',True):
                axis=actual_pose['opening_axis']
                plan['short_axis_robot_radians']=math.atan2(axis[1],axis[0])
            desired=np.array([math.cos(plan['short_axis_robot_radians']),math.sin(plan['short_axis_robot_radians']),0])
            short_error=float(np.degrees(np.arccos(np.clip(abs(np.asarray(actual_pose['opening_axis'])@desired),0,1))))
            record['arrival_orientation']={**actual_pose,'short_axis_error_deg':short_error};save()
            actions.log('orientation','到着'.replace('到着','도착')+' 방향 동시 검사 · 하향축/짧은축',pose=record['arrival_orientation'])
            if actual_pose['down_error_deg']>stage_tilt or short_error>15:
                # v0.2.36: tolerance checks warn; ARM rotation/gap measurements decide.
                record.setdefault('warnings',[]).append({'stage':'arrival_orientation','down_error_deg':actual_pose['down_error_deg'],'short_axis_error_deg':short_error})
                actions.log('warning','도착 방향 오차(하향 %.1f° / 짧은축 %.1f°) · 영상 회전 보정으로 계속'%(actual_pose['down_error_deg'],short_error))
            s=actions.check();goals=[None,None,None]
            actual_roll=next(j['raw_ticks'] for j in s['joints'] if j['name']=='wrist_roll')
            travel_plan=dict(plan)
            travel_plan['fixed_roll_radians']=model_roll(reference,actual_roll)
            photo('approach-before-opening')
            if calibration_stop:
                point={'trial':record['id'],'time':time.time(),'target_id':target_id,'category':plan.get('category'),
                       'board_mm':list(map(float,plan['board_mm'])),'board_target_mm':list(map(float,plan.get('board_target_mm') or plan['board_mm'])),'board_correction':plan.get('board_correction'),'far_tilt':bool(record.get('far_tilt')),'center_pixels':list(map(float,plan['center_pixels'])),
                       'planned_robot_xyz_mm':list(map(float,plan['approach_xyz_mm'])),
                       'commanded_fk_xyz_mm':list(map(float,route['waypoints'][-1]['xyz_mm'])),
                       'feedback_fk_xyz_mm':list(map(float,actual_pose['xyz_mm'])),
                       'opening_axis':list(map(float,actual_pose['opening_axis'])),
                       'short_axis_robot_radians':float(plan['short_axis_robot_radians']),
                       'long_axis_robot_radians':float(plan['long_axis_robot_radians']),
                       'user_offset_topview_mm':None,
                       'note':'닫힌 집게 중심을 물체 중심으로 보냄(사전 오프셋 0). 사용자: 탑뷰 화면 기준 집게 중심의 정답 대비 위치를 입력.'}
                path=DATA/'position_calibration_points.json'
                try:points=json.loads(path.read_text(encoding='utf-8'))
                except (OSError,ValueError):points=[]
                points.append(point);path.write_text(json.dumps(points,ensure_ascii=False,indent=2),encoding='utf-8')
                record['calibration_point']=point;record['result']='위치 보정 기록 · 접근 완료 후 정지(집게 닫힘, 사전 오프셋 없음)';save()
                actions.log('calibration','위치 보정 기록 · 접근 완료 후 정지 · 탑뷰 기준 집게 중심 오차를 알려 주세요',point=point)
                return
            # ARM target acquisition happens only at the object, before opening.
            actions.log('arm_check','접근 완료 · 집게 열기 전 ARM 영상에서 대상 외형 확인')
            fixed_profile=load_fixed_finger(DATA/'arm_fixed_finger.json',self.engine.cameras['arm'].state())
            plan['target_color']['fixed_finger']=fixed_profile
            plan['contact_reference']=contact_reference(fixed_profile)
            record['contact_reference']=plan['contact_reference']
            self.latest_plan['contact_reference']=plan['contact_reference']
            # Large objects only: an expected pixel width is a hint, not a
            # calibrated image scale. Look at the actual fixed-side edge first.
            arm_box()
            probe_image,probe_seq,probe_ts=self.engine.cameras['arm'].snapshot()
            located=None
            try:
                from .object_reference import _located_shape
                located=_located_shape(probe_image,plan['target_color'])
            except ValueError:pass
            edge_x=None if located is None else float(np.asarray(located['box_pixels'])[:,0].min())
            view=needs_view(plan['short_axis_width_mm'],learned_slope,probe_image.width,edge_x,located is not None)
            record['view_clearance']=view;save()
            if view['needed']:
                original_goal=dict(route['waypoints'][-1]['target'])
                last_reason=None;view_acquired=False
                for height in view_heights(approach_height):
                    try:
                        state=actions.check();vm,vq,vr,vq0=model_context(reference,state)
                        vtarget=list(plan['approach_xyz_mm']);vtarget[2]=plane+height
                        vplan=dict(plan,fixed_roll_radians=model_roll(reference,original_goal['wrist_roll']))
                        vgoal=joints_for(vplan,vtarget,state,current_grip)
                        vend=vq0+(np.array([vgoal[n] for n in NAMES])-vr)*SIGN*2*np.pi/4096
                        validate_view_path(vm,vq,vend,plane,plan['approach_xyz_mm'][2],max_tilt_deg=stage_tilt)
                    except ValueError as exc:
                        last_reason=str(exc);continue
                    # Physical errors are not caught/retried as alternate heights.
                    checked_stage_move(actions,reference,vgoal,'조건부 시야 확보 상승',vtarget,plane,max_tilt_deg=stage_tilt)
                    arm_box();im,_,_=self.engine.cameras['arm'].snapshot()
                    try:
                        acquired=pink_tube(im,partial=True,color=plan['target_color'])
                        view_acquired=True;record['view_clearance'].update(height_mm=height,high_view=acquired)
                    except ValueError as exc:last_reason=str(exc)
                    # Always return to the original nominal approach before
                    # opening. Its boundary is re-acquired in the loop below.
                    checked_stage_move(actions,reference,original_goal,'시야 확인 후 원래 접근 높이 복귀',plan['approach_xyz_mm'],plane,max_tilt_deg=stage_tilt)
                    if view_acquired:break
                if not view_acquired:raise ValueError('조건부 시야 확보 실패 · '+str(last_reason))
                save()
            arm_box()
            arm_deadline=time.monotonic()+2;arm_last_seq=None
            while True:
                actions.check()
                arm_image,arm_seq,arm_captured=self.engine.cameras['arm'].snapshot()
                if arm_seq==arm_last_seq:
                    if time.monotonic()>arm_deadline:raise ValueError('집게 열기 전 ARM 새 프레임 수신 시간 초과')
                    actions.cancel.wait(.1);continue
                arm_last_seq=arm_seq
                try:
                    if time.time()-arm_captured>1:raise ValueError('집게 열기 전 ARM 영상이 오래되었습니다.')
                    arm_shape=pink_tube(arm_image,camera='접근 후 ARM 영상',partial=True,color=plan['target_color'])
                    break
                except ValueError:
                    if time.monotonic()>arm_deadline:raise
                    actions.cancel.wait(.15)
            record['arm_before_open']={'frame_id':arm_seq,'captured':arm_captured,'shape':arm_shape}
            save()
            actions.log('arm_check','집게 개방 전 · 대상/집게 방향 판단 및 필요 회전')
            load_fixed_finger(DATA/'arm_fixed_finger.json',self.engine.cameras['arm'].state())
            alignment_grip=next(j['raw_ticks'] for j in actions.check()['joints'] if j['name']=='gripper')
            # Evaluate after arrival; do not blindly execute top-view roll.
            def alignment_frame():
                previous=self.engine.cameras['arm'].snapshot()[1]
                deadline=time.monotonic()+2
                last_failure=None
                while time.monotonic()<deadline:
                    actions.check()
                    im,seq,captured=self.engine.cameras['arm'].snapshot()
                    if seq!=previous and time.time()-captured<1:
                        previous=seq
                        try:
                            result=object_alignment(pink_tube(im,partial=True,color=plan['target_color'])) if simple_mode else measure_alignment(im,color=plan['target_color'])
                        except ValueError as exc:
                            last_failure=(im,seq,str(exc))
                            actions.cancel.wait(.1)
                            continue
                        record.setdefault('alignment_checks',[]).append({'captured':captured,'frame_id':seq,**result});save()
                        actions.log('alignment','実測'.replace('実測','실측')+' 집게/대상 방향 비교',alignment=result)
                        return result
                    actions.cancel.wait(.1)
                if last_failure:
                    im,seq,reason=last_failure
                    im.save(folder/'alignment-failed.png')
                    raise ValueError(f'ARM 방향 재확인 실패 · 프레임 {seq} · {reason}')
                raise ValueError('ARM 방향 확인 새 프레임 시간 초과')
            alignment=alignment_frame()
            active_plan=dict(travel_plan)
            # Last COMMANDED arm ticks. Re-commanding feedback ticks bakes the
            # gravity sag of shoulder_lift into the target and lowers the TCP again.
            held_goal=dict(route['waypoints'][-1]['target'])
            if not alignment['aligned']:
                # Rotate closed jaws at the already reached approach height.
                # A mandatory 100mm rise can be unreachable even when this pose
                # and the required wrist correction are reachable.
                for step in range(4):
                    if alignment['aligned']:break
                    previous_error=abs(alignment['error_deg']);previous_source=alignment.get('axis_source','object_axis')
                    roll_adjustment=float(np.clip(alignment['error_deg'],-45,45))
                    actual=actions.check()
                    rotation_goal,rotation_info=visual_rotation_target(plan,actual,alignment_grip,roll_adjustment,plane,held_goal,max_tilt_deg=stage_tilt)
                    held_goal=dict(rotation_goal)
                    record.setdefault('visual_rotations',[]).append(rotation_info);save()
                    actions.log('rotation','ARM 방향 오차 %.1f° · 현재 접근 높이에서 %.1f° 보정'%(alignment['error_deg'],roll_adjustment),rotation=rotation_info)
                    actions.move(rotation_goal,'집게 개방 전 · 현재 접근 높이 유지하며 손목 방향 보정',arrival_tolerance_ticks=46)
                    feedback=actions.check();pose_after=measured_pose(reference,feedback)
                    roll_error=next(abs(j['raw_ticks']-rotation_goal['wrist_roll']) for j in feedback['joints'] if j['name']=='wrist_roll')
                    moved=float(np.linalg.norm(np.asarray(pose_after['xyz_mm'])-rotation_info['start_xyz_mm']))
                    if roll_error>60:raise ValueError('회전 후 손목 각도 추종 오차 %d틱 · 방향 확인 필요'%roll_error)
                    if rotation_info.get('warning'):actions.log('warning',rotation_info['warning'])
                    if roll_error>24 or moved>8 or pose_after['down_error_deg']>stage_tilt:
                        actions.log('warning','회전 후 추종 오차(손목 %d틱/위치 %.1fmm/하향 %.1f°) · 영상 재확인으로 계속'%(roll_error,moved,pose_after['down_error_deg']))
                    alignment=alignment_frame()
                    # v0.2.41 (audit B17): compare improvement only on the SAME criterion
                    # (box axis 12 deg vs fixed-side edge 8 deg). A switched criterion
                    # restarts the comparison on the next step.
                    same_source=alignment.get('axis_source','object_axis')==previous_source
                    if not same_source:
                        actions.log('rotation','방향 판단 기준 변경(%s→%s) · 개선 비교 다시 시작'%(previous_source,alignment.get('axis_source','object_axis')))
                    if same_source and not alignment['aligned'] and abs(alignment['error_deg'])>=previous_error-2:
                        raise ValueError('회전 후 영상 정렬이 개선되지 않았습니다. 회전 부호/외형 추적 확인 필요')
                if not alignment['aligned']:raise ValueError('영상 방향 보정 미완료')
            # All subsequent goals preserve the verified actual wrist roll.
            actual=actions.check();roll_raw=next(j['raw_ticks'] for j in actual['joints'] if j['name']=='wrist_roll')
            plan['fixed_roll_radians']=model_roll(reference,roll_raw)
            # Only open AFTER orientation has been measured and corrected.
            manual.send('grip_force',target={'gripper':200},ratio=.2)
            actual=actions.check()
            opening={n:int(held_goal[n]) for n in NAMES}
            opening['gripper']=half
            camera=self.engine.cameras['arm']
            fixed_finger=load_fixed_finger(DATA/'arm_fixed_finger.json',camera.state())
            # Capture the complete envelope before the moving finger opens.
            pre_image,pre_seq,pre_ts=camera.snapshot()
            if time.time()-pre_ts>1:raise ValueError('개방 전 최신 ARM 외형 프레임 필요')
            observer=GapObserver(pre_image,plan['target_color'],fixed_finger,workflow)
            pre_image.save(folder/'before-open-reference.png')
            record['before_open_envelope']=observer.box.tolist();save()
            actions.move(opening,'방향 확인 후 집게 %d%% 개방'%opening_selection['percent'])
            gap_seq=camera.snapshot()[1]
            # The same fixed-side response is reused across apertures. Limit the
            # allowable fixed-side clearance by the measured remaining jaw space.
            workflow=dict(workflow)
            if opening_selection['verified']:
                available=opening_selection['width_mm']-plan['short_axis_width_mm']
                side_margin=opening_selection['margin_mm']/2
                # v0.2.45 C3: the lower bound no longer depends on a learned slope
                # (without one it stayed at the 6px default while learned runs used 3px+shrink).
                shrink=descent_shift.load();record['descent_gap_shift_px']=shrink
                workflow['gap_low_px']=min(workflow['gap_low_px'],3.)+shrink
                min_band=20. if opening_selection.get('percent',50)>=70 else 10.
                workflow['gap_high_px']=max(workflow['gap_low_px']+min_band,workflow['gap_high_px'])
                record['gap_band']={'low_px':workflow['gap_low_px'],'high_px':workflow['gap_high_px'],'min_band_px':min_band,
                                    'opening_percent':opening_selection.get('percent'),'slack_mm':float(available-side_margin),
                                    'aperture_width_mm':float(opening_selection['width_mm']),'high_source':'setting'}
                if learned_slope is not None:
                    scale=abs(learned_slope)
                    # User 2026-11-11: once the fixed finger is clear of the edge, just descend.
                    # Raising the lower bound to the side margin (~14px) forced small lateral
                    # moves at full reach (gap 3.3px -> 3.2mm move -> shoulder sag stop).
                    # Gap seen at approach height shrinks on descent (learned, descent_shift.py),
                    # so require 3px at GRASP height = 3px + learned shrink at approach height.
                    # v0.2.43 (flow-23834736, phone 72mm at 80%): the upper bound is computed
                    # from the 50% aperture (82mm) while the jaw actually opens 80%, so the
                    # band was only 10px (18.6..28.6) and a 30.5px start forced sub-mm moves
                    # into the servo dead zone. At >=70% opening the moving finger has far
                    # more room than 'available' says: keep at least a 20px band.
                    workflow['gap_high_px']=max(workflow['gap_low_px']+min_band,min(workflow['gap_high_px'],max(workflow['gap_low_px'],(available-side_margin)*scale)))
                    record['gap_band'].update(high_px=workflow['gap_high_px'],high_source='measured_slack_x_slope',slope_px_per_mm=float(scale))
            observer.settings=workflow
            record['moving_finger_context']={'opening_percent':opening_selection['percent'],'aperture_revision':opening_selection['revision'],'exclusion_method':'fresh_visible_silhouette_per_frame'}
            gap_session={}
            def read_gap():
                nonlocal gap_seq
                arm_box()
                deadline=time.monotonic()+2;ready_after=time.time();fresh=False
                while time.monotonic()<deadline:
                    actions.check();im,seq,ts=camera.snapshot()
                    if seq!=gap_seq and ts>=ready_after and time.time()-ts<1:
                        gap_seq=seq
                        im.save(folder/'gap-measurement-last.png')
                        try:value=observer.measure(im,fresh=fresh)
                        except ValueError as exc:
                            # v0.2.41 (audit B6): weak edge -> re-acquire once on a new
                            # frame; a second failure still stops before descent.
                            if fresh or '간격 근거 부족' not in str(exc):raise
                            fresh=True;deadline=time.monotonic()+2
                            record.setdefault('gap_evidence_retry',[]).append(str(exc));save()
                            actions.log('visual_gap','간격 근거 부족 · 새 프레임으로 외형 다시 검출');continue
                        record['last_shared_gap']=value
                        return value
                    actions.cancel.wait(.08)
                raise ValueError('영상 간격 보정에 필요한 최신 프레임 부족')
            state=actions.check();model,_,r,q0=model_context(reference,state)
            held_q=lambda goal:q0+(np.array([goal[n] for n in NAMES])-r)*SIGN*2*np.pi/4096
            axis=model.forward(held_q(held_goal))['opening_axis'];direction=np.array([axis[0],axis[1],0.])
            if np.linalg.norm(direction)<.5:raise ValueError('집게 벌림축이 수평이 아니어서 좌우 보정 방향을 정할 수 없습니다.')
            direction/=np.linalg.norm(direction)
            # Initial command anchor is immutable, including when final clearance
            # asks for another correction. Feedback never changes this envelope.
            gap_origin=model.forward(held_q(held_goal))['position'].copy()
            record['visual_gap_learned_slope']=learned_slope
            def lateral_move(mm):
                state=actions.check();model,q,r,q0=model_context(reference,state)
                before_feedback=model.forward(q)['position']
                start=held_q(held_goal);commanded=model.forward(start)['position']
                total=float(gap_session.get('command_mm',0))+mm
                if abs(total)>workflow['correction_mm']+1e-6:raise ValueError('영상 보정 명령 한도 초과')
                xyz=gap_origin+direction*total
                grip=next(j['raw_ticks'] for j in state['joints'] if j['name']=='gripper')
                lateral_plan=dict(plan,fixed_roll_radians=model_roll(reference,held_goal['wrist_roll']))
                target=joints_for(lateral_plan,xyz.tolist(),state,grip)
                end=held_q(target)
                for t in np.linspace(0,1,61):
                    f=model.forward(start+(end-start)*t)
                    # Only a board strike is a reason not to move; ARM image decides the rest.
                    if f['position'][2]<plane+15:raise ValueError('영상 좌우 보정 경로가 판에 너무 가까움 · 이동 안 함')
                def move_same_target(attempt):
                    def move_goal(goal,compensated):
                        actions.move(goal,'고정 손가락 간격 · %.1fmm 이동%s'%(mm,' 추종 보정1회' if compensated else ''),
                                     arrival_tolerance_ticks=46,arrival_mode='settled',target_height_mm=float(xyz[2]))
                    def validate_compensation(goal,feedback):
                        validate_goal(goal,feedback)
                        # Feed-forward command deliberately offsets steady bias.
                        # Check the predicted response with the measured bias,
                        # and separately bound raw-command excursion.
                        fm,fq,fr,fq0=model_context(reference,feedback)
                        cq=held_q(goal)
                        bias=fq-end
                        for origin_q,destination in [(fq,cq+bias),(end,cq)]:
                            for t in np.linspace(0,1,101):
                                f=fm.forward(origin_q+(destination-origin_q)*t,with_points=False)
                                dz=f['position'][2]-gap_origin[2]
                                if origin_q is end:
                                    # Raw command: a 45-tick shoulder sag compensation at full
                                    # reach lifts the NOMINAL path ~20mm (flow-a5b6faf4). Rising
                                    # is safe; keep the downward bound and the floor.
                                    bad=dz>25 or dz<-12
                                else:
                                    bad=abs(dz)>max(4,abs(fm.forward(fq,with_points=False)['position'][2]-gap_origin[2])+.2)
                                tilt_bad=-f['tool_axis'][2]<math.cos(math.radians(stage_tilt))
                                if bad or f['position'][2]<plane+20 or tilt_bad:
                                    raise ValueError('추종 보정 명령의 높이/방향 경로 검사 실패 · 하강 중단 (%s 높이차 %.1fmm%s)'%(
                                        '명령' if origin_q is end else '예측',dz,' · 기울기 초과' if tilt_bad else ''))
                    move_with_compensation(target,move_goal,actions.check,validate_compensation,
                        lambda data:(record.setdefault('following_compensation',[]).append(data),save(),actions.log('following_compensation','원래 목표 유지 · 관절 오차 1회 보정',compensation=data)))
                    held_goal.update({n:target[n] for n in NAMES})
                initial=[True]
                def read_xyz():
                    if initial[0]:initial[0]=False;return before_feedback
                    return measured_pose(reference,actions.check())['xyz_mm']
                def feedback_log(data):
                    record.setdefault('lateral_feedback',[]).append(dict(data,total_command_mm=total,target=target));save()
                    actions.log('lateral_feedback','정지 후 실제 TCP 이동량 확인',feedback=data)
                return lateral_feedback_move(move_same_target,read_xyz,direction,mm,feedback_log,max_attempts=1,expected_z=float(xyz[2]))
            def gap_log(message,result):
                record.setdefault('visual_gap_adjustments',[]).append({'message':message,**result});save()
                actions.log('visual_gap',message+' · %.1fpx / 허용 %.1f~%.1fpx'%(result['gap_px'],result['low_px'],result['high_px']),gap=result)
            slope_saved=[False];learning_blocked=[]
            def persist_slope(session,success=False):
                if save_slope(session,gap_key,approach_height,frame_size,record['id'],success=success):slope_saved[0]=True
            def run_gap():
                try:
                    try:
                        result=correct_gap(read_gap,lateral_move,gap_log,workflow,
                                           learned_slope=gap_session.get('slope_px_per_mm',learned_slope),
                                           session=gap_session,on_progress=persist_slope)
                    except ValueError:
                        # v0.2.41 (audit C1): a reversed image response flags the stored
                        # slope; two in a row discard it (else v0.2.40 reused it forever).
                        if gap_session.get('reversed') is not None and learned_slope is not None and not slope_saved[0]:
                            record['slope_suspect']=mark_suspect('flow %s: 반대 반응 %.2fpx/mm'%(record['id'],gap_session['reversed']));save()
                        raise
                    record['visual_gap_result']=result
                    if result.get('unconfirmed_reversal'):
                        # v0.2.42 (Codex): band reached right after ONE reversed response.
                        # Position is accepted (image band); the learned direction is not:
                        # flag the slope, do not save it, do not learn an offset this run.
                        learning_blocked.append('반대 반응 1회 후 허용 범위 도달')
                        if learned_slope is not None:
                            record['slope_suspect']=mark_suspect('flow %s: 반대 반응 1회 후 범위 도달 %.2fpx/mm'%(record['id'],gap_session.get('reversed',0)));save()
                    else:
                        persist_slope(gap_session,success=True)
                    anchor=model.forward(held_q(held_goal))['position'].tolist()
                    if 'before_visual_anchor' not in record:
                        record['before_visual_anchor']={key:list(plan[key]) for key in ['approach_xyz_mm','grasp_xyz_mm','verification_lift_xyz_mm']}
                    anchor_plan(plan,anchor)
                    self.latest_plan={k:v for k,v in plan.items() if k!='reference'};record['plan']=self.latest_plan
                    return result
                finally:
                    record['visual_gap_session']=copy.deepcopy(gap_session);save()
            run_gap()
            last_gap_image=None
            def check_clearance():
                nonlocal last_gap_image
                result=None
                for _ in range(2):
                    gap=read_gap()
                    im,seq,ts=camera.snapshot();last_gap_image=im
                    try:aux=open_jaw_clearance(im,plan['target_color'],fixed_finger=fixed_finger)
                    except ValueError as exc:aux={'clear':False,'fingers':[],'reason':str(exc)}
                    result=shared_clearance(aux,gap)
                    record['descent_clearance']=result;save()
                    if not fixed_passed(result):return result
                return result
            clearance=ensure_fixed_clearance(check_clearance,run_gap)
            if last_gap_image is not None:
                last_gap_image.save(folder/'opening-clearance-raw.png')
                overlay=last_gap_image.copy()
                from PIL import ImageDraw
                draw=ImageDraw.Draw(overlay);draw.polygon([tuple(p) for p in observer.box],outline='#ffb84d',width=2)
                # The gap is read against this fitted fixed-side edge, not the upright box.
                edge_line=(observer.boundary or {}).get('points')
                if edge_line:draw.line([tuple(edge_line[0]),tuple(edge_line[1])],fill='#ffff00',width=4)
                draw.polygon([tuple(p) for p in fixed_finger['contour']],outline='#63cfff',width=2)
                draw.text((8,8),'fixed gap %.1f px / %.1f..%.1f'%(clearance['fixed_gap']['gap_px'],clearance['fixed_gap']['low_px'],clearance['fixed_gap']['high_px']),fill='white')
                overlay.save(folder/'opening-clearance-overlay.png')
            if not clearance['clear']:
                # Fixed passage has already been proven by ensure_fixed_clearance.
                actions.log('clearance_warning','고정 손가락 통과 · 보조 손가락 판정만 경고',clearance=clearance)
            if slope_info['reconfirm']:
                # v0.2.42 (Codex review of v0.2.41): ONLY a measured response confirms
                # the direction - an effective (>=1.5mm real travel) move whose gap
                # change has the learned sign. A single frame's gap value (the old
                # '>= -30px' rule) says nothing about direction. If the band was reached
                # without such a move, this run may descend (the band is image-verified)
                # but stays 'reconfirm': no new key, no offset learning.
                adjustments=record.get('visual_gap_adjustments',[])
                matched=[a for a in adjustments if a.get('slope_px_per_mm') is not None and abs(a.get('step_mm') or 0)>=1.5
                         and np.sign(a['slope_px_per_mm'])==np.sign(learned_slope)]
                confirmed=bool(matched) and not learning_blocked
                record['slope_reconfirm']={'matching_moves':len(matched),'confirmed':confirmed};save()
                if confirmed:
                    if not slope_saved[0]:confirm_key(gap_key)
                    actions.log('gap_reconfirm','유효 이동으로 간격 방향 재확인 · 새 기준으로 저장',reconfirm=record['slope_reconfirm'])
                else:
                    learning_blocked.append('좌표 기준 변경 후 방향 미확인')
                    actions.log('gap_reconfirm','이동 없이 허용 범위 · 이번 위치는 사용, 방향은 재확인 대기 유지(학습 안 함)',reconfirm=record['slope_reconfirm'])
            slope=gap_session.get('slope_px_per_mm',learned_slope)
            total_command=plan['preoffset']['signed_mm']+gap_session.get('command_mm',0)
            record['approach_offset_observation']={'width_mm':plan['short_axis_width_mm'],'preoffset_mm':plan['preoffset']['signed_mm'],
                'visual_command_mm':gap_session.get('command_mm',0),'total_command_mm':total_command,'slope_px_per_mm':slope,'opening_percent':opening_selection['percent'],'aperture_revision':opening_selection['revision'],
                'accepted':not learning_blocked,'learning_blocked':list(learning_blocked)}
            if not learning_blocked:
                learn_offset(plan['short_axis_width_mm'],total_command,slope,gap_key,record['id'],opening_percent=opening_selection['percent'],aperture_revision=opening_selection['revision'])
            save()
            if measure_only:
                record['measure_only']=True;record['result']='간격 측정 종료 · 하강 전 접근 높이 유지';save()
                actions.log('measurement',record['result'],clearance=clearance)
                return
            actual=actions.check()
            if correction:local_grasp_offset(plan,actual)
            actual_gap=next(j['raw_ticks'] for j in actual['joints'] if j['name']=='gripper')
            # v0.2.53 (user): watch the fixed-finger gap DURING descent. Stop at 1-2 intermediate
            # heights; if the remaining (learned) shrink would make the finger overlap the
            # object, shift sideways at that height, then continue.
            def descent_watch():
                z_top=float(plan['approach_xyz_mm'][2]);z_bot=float(plan['grasp_xyz_mm'][2])
                span=z_top-z_bot
                if span<12:return
                shrink=float(descent_shift.load() or 0.)
                fractions=[2/3,1/3] if span>=25 else [1/2]
                checks=record.setdefault('descent_checks',[])
                for fraction in fractions:
                    z=z_bot+span*fraction
                    st=actions.check();grip=next(j['raw_ticks'] for j in st['joints'] if j['name']=='gripper')
                    xyz=[plan['grasp_xyz_mm'][0],plan['grasp_xyz_mm'][1],z]
                    checked_stage_move(actions,reference,joints_for(plan,xyz,st,grip),'하강 중간 정지 · 판 위 %.0fmm 간격 확인'%(z-plane),xyz,plane,
                        descent=True,log=lambda data:(record.setdefault('stage_following',[]).append(data),save()),max_tilt_deg=stage_tilt)
                    entry={'z_mm':z,'height_above_plane_mm':z-plane,'remaining_fraction':fraction,'learned_shrink_px':shrink}
                    try:
                        arm_box()
                        im,seq,_=self.engine.cameras['arm'].snapshot();im.save(folder/('descent-check-%d.png'%len(checks)))
                        gap=fixed_gap(im,plan['target_color'],fixed_finger,dict(workflow,gap_low_px=0.,gap_high_px=999.))
                    except ValueError as exc:
                        entry['error']=str(exc);checks.append(entry);save()
                        actions.log('descent_check','하강 중 간격 측정 불가 · 계속 하강 (%s)'%exc);continue
                    predicted=gap['gap_px']-shrink*fraction
                    entry.update(gap_px=gap['gap_px'],predicted_final_px=predicted,frame_id=seq,extrapolated=bool(gap.get('extrapolated_edge')))
                    if predicted>=3.:
                        entry['action']='continue';checks.append(entry);save()
                        actions.log('descent_check','하강 중 간격 %.1fpx · 예상 최종 %.1fpx · 계속'%(gap['gap_px'],predicted));continue
                    slope=gap_session.get('slope_px_per_mm',learned_slope)
                    if not slope:
                        entry['action']='stop_no_slope';checks.append(entry);save()
                        raise ValueError('하강 중 겹침 예상(예상 최종 %.1fpx) · px/mm 기울기 없음 → 보정 불가, 하강 중단'%predicted)
                    mm=(8.-predicted)/slope
                    used=float(gap_session.get('command_mm',0))+sum(c.get('lateral_mm',0) for c in checks)
                    if abs(used+mm)>workflow['correction_mm']+1e-6:
                        entry.update(action='stop_limit',lateral_mm=0.);checks.append(entry);save()
                        raise ValueError('하강 중 겹침 예상 · 보정 총량 한도 %.0fmm 초과 → 하강 중단'%workflow['correction_mm'])
                    st=actions.check();m2,q2,r2,q02=model_context(reference,st)
                    here=np.asarray([plan['grasp_xyz_mm'][0],plan['grasp_xyz_mm'][1],z])+direction*mm
                    goal=joints_for(plan,here.tolist(),st,grip)
                    end=q02+(np.array([goal[n] for n in NAMES])-r2)*SIGN*2*np.pi/4096
                    if any(m2.forward(q2+(end-q2)*t,with_points=False)['position'][2]<plane+5 for t in np.linspace(0,1,31)):
                        raise ValueError('하강 중 옆 보정 경로가 판에 너무 가까움 · 하강 중단')
                    actions.move(goal,'하강 중 겹침 예상 · %.1fmm 옆 보정'%mm,arrival_tolerance_ticks=46,arrival_mode='settled',target_height_mm=float(z))
                    plan['grasp_xyz_mm']=[float(here[0]),float(here[1]),z_bot]
                    entry.update(action='lateral',lateral_mm=float(mm),slope_px_per_mm=float(slope))
                    try:
                        im,seq,_=self.engine.cameras['arm'].snapshot()
                        after=fixed_gap(im,plan['target_color'],fixed_finger,dict(workflow,gap_low_px=0.,gap_high_px=999.))
                        entry['gap_after_px']=after['gap_px']
                    except ValueError as exc:entry['gap_after_error']=str(exc)
                    checks.append(entry);save()
                    actions.log('descent_check','하강 중 겹침 예상 %.1fpx → %.1fmm 옆 보정 후 계속'%(predicted,mm))
            descent_watch()
            actual=actions.check();actual_gap=next(j['raw_ticks'] for j in actual['joints'] if j['name']=='gripper')
            goals[1]=joints_for(plan,plan['grasp_xyz_mm'],actual,actual_gap)
            checked_stage_move(actions,reference,goals[1],'검출 물품의 설정 높이까지 하강',plan['grasp_xyz_mm'],plane,
                descent=True,log=lambda data:(record.setdefault('stage_following',[]).append(data),save(),actions.log('stage_following','하강 · 정지/추종/FK 확인',result=data)),max_tilt_deg=stage_tilt)
            photo('before-close')
            # Re-measure the fixed-finger gap at grasp height (the ARM camera's real job):
            # learn the approach->grasp shrink, and never close with the finger on the object.
            wide_flat=plan.get('short_axis_width_mm',0)>=WIDE_FLAT_MM
            def grasp_gap_check(stage,learn,after_seq=None):
                try:
                    arm_box()
                    low_im,low_seq,_=self.engine.cameras['arm'].snapshot()
                    if after_seq is not None:
                        # Re-measure on a NEW frame (v0.2.42 floor-gap retry).
                        deadline=time.monotonic()+2
                        while low_seq==after_seq and time.monotonic()<deadline:
                            actions.cancel.wait(.08);low_im,low_seq,_=self.engine.cameras['arm'].snapshot()
                    record[stage+'_frame']=low_seq
                    low_gap=fixed_gap(low_im,plan['target_color'],fixed_finger,dict(workflow,gap_low_px=0.,gap_high_px=999.))
                    approach_gap=(record.get('last_shared_gap') or {}).get('gap_px')
                    record[stage]={'gap_px':low_gap['gap_px'],'minimum_row_gap_px':low_gap['minimum_row_gap_px'],'approach_gap_px':approach_gap}
                    if learn and approach_gap is not None:record[stage]['learned_shift_px']=descent_shift.update(approach_gap,low_gap['gap_px'],record['id'])
                    save()
                    actions.log('grasp_gap','%s 고정 손가락 간격 %.1fpx (접근 높이 %s)'%('바닥 하강 후' if stage=='floor_gap' else '하강 후',low_gap['gap_px'],'%.1fpx'%approach_gap if approach_gap is not None else '-'),gap=record[stage])
                    return low_gap
                except ValueError as exc:
                    record[stage]={'error':str(exc)};save();return None
            # At grasp height the finger sits beside the edge, so ~0px is the IDEAL result
            # (flow 19:52: -0.5px, user: 'fit exactly'). Refuse only a clear overlap.
            # Wide items learn the shrink from the FINAL (floor) gap instead (audit B23).
            low_gap=grasp_gap_check('grasp_height_gap',learn=not wide_flat)
            if low_gap is not None and low_gap['gap_px']<-8:
                raise ValueError('하강 후 고정 손가락이 물체 경계 안쪽(%.1fpx) · 닫지 않음 · 감소량 학습됨, 다시 시도하세요'%low_gap['gap_px'])
            if wide_flat:
                # User 2026-11-11: flat wide items need the fingertips on the board.
                # v0.2.41 (audit B18-B20, Fable+Codex): decide 'low enough', not
                # 'touched' (FK cannot tell dead zone / friction / board apart). Fixed
                # 2mm ladder below the PLANNED grasp height, absolute command floor,
                # IK failure is its own state, always release a press. See floor_descent.py.
                gx,gy=plan['grasp_xyz_mm'][:2]
                def floor_goal(z):
                    st=actions.check();grip=next(j['raw_ticks'] for j in st['joints'] if j['name']=='gripper')
                    return joints_for(plan,[gx,gy,z],st,grip)
                def floor_move(goal,z,label):
                    actions.move(goal,label,arrival_tolerance_ticks=46,target_height_mm=z)
                    return measured_pose(reference,actions.check())['xyz_mm'][2]
                floor=floor_descent.descend(float(plan['grasp_xyz_mm'][2]),float(plane),floor_goal,floor_move,
                                            lambda:measured_pose(reference,actions.check())['xyz_mm'][2])
                record['floor_contact']=floor;save()
                names={'target':'판 +1mm 도달','contact':'접촉 후보','floor_limit':'하한 도달','ik_limit':'역기구학 한계','below_floor':'판 아래 피드백'}
                actions.log('floor_contact','바닥 하강 %s · 도달 판%+.1fmm · %d단계%s'%(names.get(floor['status'],floor['status']),floor['reached_z']-plane,len(floor['steps']),
                            ' · 정체 재시도' if floor.get('retry') else ''),floor=floor)
                def lift_and_stop(reason):
                    # Never close here: lift back to the approach height, then stop.
                    try:
                        st=actions.check();grip=next(j['raw_ticks'] for j in st['joints'] if j['name']=='gripper')
                        actions.move(joints_for(plan,plan['approach_xyz_mm'],st,grip),'바닥 하강 실패 · 닫지 않고 접근 높이로 상승',arrival_tolerance_ticks=46)
                    except ValueError as exc:
                        record['floor_lift_error']=str(exc);save()
                    raise ValueError(reason+' · 닫지 않고 상승 후 정지')
                # v0.2.42 (Codex): too low / unverified release is a FAILURE, not 'low enough'.
                action,reason=floor_descent.verdict(floor,gap_checked=False)
                if action=='stop':lift_and_stop(reason)
                # Audit B23: the overlap check must also hold AFTER the extra descent.
                # v0.2.42 (Codex): 'not measured' is not 'no overlap' -> one retry on a
                # new frame, then stop instead of closing.
                floor_gap=grasp_gap_check('floor_gap',learn=True)
                if floor_gap is None:
                    floor_gap=grasp_gap_check('floor_gap_retry',learn=True,after_seq=record.get('floor_gap_frame'))
                action,reason=floor_descent.verdict(floor,floor_gap)
                record['floor_verdict']={'action':action,'reason':reason};save()
                if action=='stop':lift_and_stop(reason)
                if action=='warn_close':
                    # User 2026-11-11 (v0.2.41): closing HIGH is not dangerous -> warn and close.
                    actions.log('warning',reason,floor=floor)
                # v0.2.76: any wide item (>=60mm, not a specific category) - bring the fixed
                # finger close to the side before closing, so the moving finger does not have
                # to push the item across the board. See snug_fit.py.
                from . import snug_fit
                snug=record.setdefault('snug_fit',[]);gap_now=(floor_gap or {}).get('gap_px')
                slope=gap_session.get('slope_px_per_mm',learned_slope)
                cz=float(floor['steps'][-1]['commanded_z']) if floor.get('steps') else float(plan['grasp_xyz_mm'][2])
                measured=False
                for _ in range(snug_fit.MAX_STEPS):
                    used=float(gap_session.get('command_mm',0))+sum(c.get('lateral_mm',0) for c in record.get('descent_checks',[]))+sum(e.get('mm',0) for e in snug)
                    if snug and snug[-1].get('mm'):
                        floor_slope=snug_fit.measured_slope(snug[-1]['gap_px'],snug[-1].get('gap_after_px'),snug[-1]['mm'])
                        if floor_slope is not None:slope,measured=floor_slope,True
                    mm=snug_fit.step_mm(gap_now,slope,used,workflow['correction_mm'],measured=measured)
                    if mm is None:break
                    here=np.asarray([gx,gy,cz])+direction*mm
                    st=actions.check();grip=next(j['raw_ticks'] for j in st['joints'] if j['name']=='gripper')
                    up=joints_for(plan,[float(here[0]),float(here[1]),cz+snug_fit.LIFT_MM],st,grip)
                    m2,q2,r2,q02=model_context(reference,st);end=q02+(np.array([up[n] for n in NAMES])-r2)*SIGN*2*np.pi/4096
                    # v0.2.77 (flow-79bca983): at the floor the feedback already read plane-2.3mm,
                    # so 'below plane-1' rejected the path at its START. The move lifts 1mm;
                    # only refuse a path that goes LOWER than where the finger already is.
                    path_z=[m2.forward(q2+(end-q2)*t,with_points=False)['position'][2] for t in np.linspace(0,1,31)]
                    if min(path_z)<snug_fit.path_floor(path_z[0],plane):
                        snug.append({'gap_px':gap_now,'mm':0.,'skipped':'경로가 현재 높이보다 아래','min_z':float(min(path_z)),'start_z':float(path_z[0])});save();break
                    actions.move(up,'큰 물품 · 고정 손가락을 옆면에 붙이기 %.1fmm'%mm,arrival_tolerance_ticks=46,arrival_mode='settled',target_height_mm=cz+snug_fit.LIFT_MM)
                    st=actions.check()
                    actions.move(joints_for(plan,[float(here[0]),float(here[1]),cz],st,grip),'큰 물품 · 붙인 위치에서 바닥 높이로',arrival_tolerance_ticks=46,target_height_mm=cz)
                    gx,gy=float(here[0]),float(here[1]);plan['grasp_xyz_mm']=[gx,gy,float(plan['grasp_xyz_mm'][2])]
                    after=grasp_gap_check('snug_gap',learn=False)
                    entry={'gap_px':gap_now,'mm':mm,'slope_px_per_mm':float(slope),'slope_source':'floor_measured' if measured else 'approach_learned','gap_after_px':(after or {}).get('gap_px')}
                    snug.append(entry);save()
                    actions.log('snug_fit','큰 물품 밀착 · 간격 %.1fpx → %s'%(gap_now,'%.1fpx'%after['gap_px'] if after else '측정 실패'),snug=entry)
                    if after is None:break
                    if after['gap_px']<-8:lift_and_stop('밀착 후 고정 손가락이 물체 경계 안쪽(%.1fpx)'%after['gap_px'])
                    gap_now=after['gap_px']
            actions.log('closing','실시간 흰 집게 경계와 물체 양쪽 간격으로 닫기 · 부하 단독 정지 판정 사용 안 함')
            s=actions.check();goal={j['name']:j['raw_ticks'] for j in s['joints']};goal['gripper']=s['joints'][-1]['min_ticks']
            hits=0;last_seq=-1;last_sample=0
            # v0.2.51 (flow-4aa5a6ab): the visual contact guard fired at the very first frames
            # (gripper 2068, zero travel) and stopped closing ~33mm short of a 49mm tube.
            # Only accept it after the jaw has closed at least half the way to where the
            # measured aperture table says this width is touched.
            close_start=next(j['raw_ticks'] for j in s['joints'] if j['name']=='gripper')
            expected_contact=contact_ticks(plan['short_axis_width_mm'])
            min_travel=max(20,.5*(close_start-expected_contact)) if expected_contact is not None else 20
            record['close_expectation']={'start_ticks':close_start,'expected_contact_ticks':expected_contact,'min_travel_ticks':float(min_travel)}
            def watch(state):
                nonlocal hits,last_seq,last_sample
                if time.monotonic()-last_sample<.1:return False
                last_sample=time.monotonic();im,seq,captured=self.engine.cameras['arm'].snapshot()
                if seq==last_seq:return False
                last_seq=seq;result=edges(im,color=plan['target_color']);telemetry=manual.send('grip_sample')['telemetry']
                travel=close_start-next(j['raw_ticks'] for j in state['joints'] if j['name']=='gripper')
                record['events'].append({'phase':'closing','captured':captured,'frame_id':seq,'vision':result,'telemetry':telemetry,'travel_ticks':travel});save()
                hits=hits+1 if result.get('bilateral_contact_candidate') and travel>=min_travel else 0
                if telemetry['temperature_c']>=55:raise ValueError('집게 온도 상한')
                if hits>=3:return True
                return False
            closed=actions.move(goal,'영상 간격을 보며 닫기',minimum=10,grip_contact=True,watch=watch)
            record['close_state']=closed
            visual_confirmed=(closed.get('motion') or {}).get('contact_source')=='external_contact_guard'
            record['visual_contact_confirmed']=visual_confirmed
            record['assumed_grasp_for_trial']=not visual_confirmed
            if not visual_confirmed:
                actions.log('assumed_grasp','시험 모드 · 영상 접촉 미확인이나 집힘을 가정하여 접근 높이로 상승 · 성공 미확정')
            save()
            # Both visual contact and unverified stall receive the same extra close.
            close_seconds=float(workflow.get('extra_close_seconds',1.5))
            actions.log('extra_close','첫 닫기 정지 후 토크 200으로 최대 %.1f초 추가 닫기 후 위치 유지'%close_seconds)
            extra_state=actions.check()
            extra_goal={j['name']:j['raw_ticks'] for j in extra_state['joints']}
            extra_goal['gripper']=next(j['min_ticks'] for j in extra_state['joints'] if j['name']=='gripper')
            manual.send('grip_force',target={'gripper':200},ratio=.2)
            extra_started=time.monotonic()
            closed=actions.move(extra_goal,'토크 200 · 최대 %.1f초 추가 닫기 후 유지'%close_seconds,minimum=3,grip_contact=True,timed_close=True,timed_close_seconds=close_seconds)
            record['extra_close']={'requested_seconds':close_seconds,'stall_seconds':2,'torque_limit':200,'elapsed_seconds':time.monotonic()-extra_started,
                'state':closed,'note':'로봇 측 최대 %.1f초 종료(2초 무이동 정지 시 먼저 종료) · 실제 성공 미확정'%close_seconds}
            before=photo('closed-after-extra');save()
            before,tracking_seq,tracking_ts=self.engine.cameras['arm'].snapshot()
            tracker=LiftTracker(before,plan['target_color'],tracking_seq,tracking_ts)
            start_z=measured_pose(reference,actions.check())['xyz_mm'][2]
            # v0.2.45: how far the held object hangs below the TCP (closed at the floor).
            record['hang_mm']=float(max(0.,start_z-plane))
            last_tracking=0
            def observe_lift(state):
                nonlocal last_tracking
                if time.monotonic()-last_tracking>=.2:
                    im,seq,ts=self.engine.cameras['arm'].snapshot()
                    if time.time()-ts<1:tracker.sample(im,seq,ts)
                    last_tracking=time.monotonic()
                return False
            # Preserve contact position, never the fully-closed goal.
            grip=next(j['raw_ticks'] for j in closed['joints'] if j['name']=='gripper')
            lift=joints_for(plan,plan['verification_lift_xyz_mm'],actions.check(),grip)
            actions.move(lift,'집게 닫힘 유지 · 하강 전 접근 높이로 복귀',watch=observe_lift)
            photo('verification-lift')
            final_z=measured_pose(reference,actions.check())['xyz_mm'][2]
            record['lift_evidence']=tracker.result(final_z-start_z)
            evidence=record['lift_evidence']
            record['result']=evidence['reason']+' · 집게 유지'
            actions.log('grasp_result',record['result'],evidence=evidence)
            if workflow['finish_mode']=='return':
                if evidence['status']=='not_held_likely' or (evidence['status']!='held_likely' and not workflow['return_on_unconfirmed']):
                    actions.log('return_pending','파지 근거 부족 · 추가 이동 없이 유지. 미확정 진행은 동작 설정에서 선택할 수 있습니다.')
                elif not workflow.get('dropoff_pose'):
                    actions.log('return_pending','놓기 위치 미등록 · 수동 제어로 놓기 자세를 맞춘 뒤 설정에서 저장하세요.')
                else:
                    self._transfer_to_dropoff(actions,reference,plane,workflow,record,lift,grip,half,opening_selection,photo,save)
        except Exception as exc:record['error']=str(exc);raise
        finally:
            arm_roi.deactivate()
            if plan and plan.get('preoffset'):
                record.setdefault('approach_offset_observation',{
                    'width_mm':plan['short_axis_width_mm'],'preoffset_mm':plan['preoffset']['signed_mm'],
                    'visual_command_mm':gap_session.get('command_mm',0),
                    'total_command_mm':plan['preoffset']['signed_mm']+gap_session.get('command_mm',0),
                    'accepted':False})
            record['finished']=time.time();save()
