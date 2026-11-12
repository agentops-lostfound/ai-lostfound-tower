"""단일 직렬 소유자: 사용자 조그 전용. 컨테이너에서 stdin/stdout JSONL로 실행."""
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time


def emit(event, **data):
    print(json.dumps(dict(event=event, **data)), flush=True)


def off(name,position,target,tolerance):
    # shoulder_lift sags under load at full reach (+45..50 ticks measured
    # 2026-11-11, lateral moves near wrist_flex limit). Accept that sag
    # direction to 70; the caller's FK position checks decide the TCP.
    error=position-target
    if name=='shoulder_lift' and tolerance>=46 and 0<error<=70:return False
    return abs(error)>tolerance


def arrived_at_target(positions, active, names):
    tolerance=active.get('arrival_tolerance_ticks',46)
    if isinstance(tolerance,dict):
        displacement=active.get('arrival_displacement_ticks',{})
        for n in names:
            if off(n,positions[n],active['target'][n],46):return False
            if n in displacement:
                if abs((positions[n]-active['start'][n])-displacement[n])>tolerance[n]:return False
        return True
    return all(not off(n,positions[n],active['target'][n],tolerance if n!='gripper' else 46)
               for n in names if (tolerance<46 and n!='gripper') or abs(active['target'][n]-active['start'][n])>3)


def settled_at_target(positions,active,names,now):
    """After full interpolation, require all joints stable for 0.25 seconds.

    Three ticks peak-to-peak accommodates encoder jitter; this is a rest
    measurement, not a demanded sub-degree target accuracy.
    """
    if now-active['started']<active['duration']:return False
    if any(off(n,positions[n],active['target'][n],46) for n in names):
        active['settle_samples']=[];return False
    samples=active.setdefault('settle_samples',[])
    samples.append((now,dict(positions)))
    while len(samples)>1 and now-samples[1][0]>=.25:samples.pop(0)
    if now-samples[0][0]<.25:return False
    return all(max(row[n] for _,row in samples)-min(row[n] for _,row in samples)<=3 for n in names)


def main():
    config=json.loads(sys.stdin.readline())
    path=Path(config['port']).resolve(strict=True)
    if not str(path).startswith('/dev/tty'): raise ValueError('직렬 장치 경로 오류')
    for process in Path('/proc').glob('[0-9]*'):
        if process.name==str(os.getpid()):continue
        try:
            for fd in (process/'fd').iterdir():
                try:
                    if fd.resolve()==path:raise RuntimeError('다른 프로세스가 장치를 사용 중입니다. Studio 제어를 종료하세요.')
                except (FileNotFoundError,PermissionError):pass
        except (FileNotFoundError,PermissionError):pass
    from scservo_sdk import PortHandler,PacketHandler
    port=PortHandler(str(path));packet=PacketHandler(0)
    commands=queue.Queue(maxsize=40);urgent=threading.Event();eof=threading.Event()
    names=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper']
    calibration=config['calibration'];rows={};active=None;latched=False;last_state=0
    velocity=0.;last_tick=time.monotonic();writes=0;revoked=set();motion=None;grip_force=None

    def read(name,address=56):
        ident=calibration[name]['id']
        fn=packet.read2ByteTxRx if address in [56,42,48,60,69] else packet.read1ByteTxRx
        for attempt in range(3):
            value,comm,error=fn(port,ident,address)
            if not comm and not error:return value
            if error:break
            time.sleep(.003)
        if comm or error:raise RuntimeError(f'{name} 읽기 실패 ({comm},{error})')
        return value

    def write(name,address,value):
        nonlocal writes
        fn=packet.write2ByteTxRx if address in [42,48] else packet.write1ByteTxRx
        # Writing the same value again is idempotent. A missing status reply
        # (COMM_RX_TIMEOUT -6) or corrupt reply (-7) was intermittently fatal
        # (wrist_roll during an 80% gripper opening). Retry only bus errors, not
        # servo error flags, like read() already does.
        for attempt in range(3):
            comm,error=fn(port,calibration[name]['id'],address,int(value))
            if not comm and not error:break
            if error or comm not in (-6,-7):break
            emit('notice',message=f'{name} 쓰기 응답 없음({comm}) · 같은 값 재전송 {attempt+1}/2')
            time.sleep(.003)
        if comm or error:raise RuntimeError(f'{name} 쓰기 실패 ({comm},{error})')
        writes+=1

    def observe():
        for name in names:
            p=read(name);torque=read(name,40);cal=calibration[name]
            lo,hi=cal['range_min'],cal['range_max']
            normalized=(p-lo)/(hi-lo)*(100 if name=='gripper' else 200)-(0 if name=='gripper' else 100)
            rows[name]={'name':name,'id':cal['id'],'raw_ticks':p,'normalized':normalized,
                'min_ticks':lo,'max_ticks':hi,'torque_enabled':bool(torque),'in_range':lo<=p<=hi}

    def halt(latch=False):
        nonlocal active,velocity,latched,motion
        jog=active if active and active.get('kind')!='move' else None
        move=active if active and active.get('kind')=='move' else None
        active=None;velocity=0.
        if motion and motion['status']=='running':motion['status']='stopped'
        if latch:latched=True
        failures=[]
        for name in names:
            if rows.get(name,{}).get('torque_enabled'):
                # v0.2.46: re-commanding feedback ratchets loaded joints down by their
                # gravity sag (10-35 ticks) on every stop. Only a joint still far from its
                # goal (actually moving) is pulled back to where it is now.
                try:
                    p=read(name)
                    if jog and jog['joint']==name:
                        # hold where the jogged joint is now, keeping its press-time sag lead
                        # (writing raw feedback would let it sag again by that amount)
                        cal=calibration[name];write(name,42,round(max(cal['range_min'],min(cal['range_max'],p-jog.get('offset',0.)))))
                    elif move and name in move.get('sag',{}) and abs(move['target'][name]-move['start'][name])>3:
                        cal=calibration[name];write(name,42,round(max(cal['range_min'],min(cal['range_max'],p+move['sag'][name]))))
                    elif abs(read(name,42)-p)>46:write(name,42,p)
                except Exception as exc:failures.append(str(exc))
        if failures:emit('error',message='위치 유지 확인 실패: '+' / '.join(failures))

    def receive():
        try:
            for line in sys.stdin:
                try:
                    cmd=json.loads(line)
                    cmd['_received']=time.monotonic()
                    if cmd.get('action') in ['stop','disconnect']:urgent.set()
                    commands.put(cmd,timeout=.1)
                except Exception:urgent.set()
        finally:eof.set();urgent.set()

    try:
        if not port.openPort():raise RuntimeError('포트 열기 실패')
        port.ser.exclusive=True
        if not port.setBaudRate(1000000):raise RuntimeError('통신 속도 설정 실패')
        import fcntl,termios
        fcntl.ioctl(port.ser.fileno(),termios.TIOCEXCL)
        port.setPacketTimeoutMillis(30)
        observe()
        emit('ready',joints=list(rows.values()),writes=writes)
        threading.Thread(target=receive,daemon=True).start()
        running=True
        while running and not eof.is_set():
            now=time.monotonic();dt=min(.08,max(.001,now-last_tick));last_tick=now
            if urgent.is_set():
                halt(True);urgent.clear()
            for _ in range(15):
                try:cmd=commands.get_nowait()
                except queue.Empty:break
                action=cmd.get('action');ident=cmd.get('request_id')
                try:
                    if action in ['stop','halt','disconnect']:
                        if cmd.get('token'):revoked.add(cmd['token'])
                        if active and active.get('token'):revoked.add(active['token'])
                        halt(action!='halt')
                        if action=='disconnect':running=False
                    elif action=='resume':
                        observe();latched=False
                    elif action in ['enable','disable']:
                        name=cmd.get('joint')
                        if name!='all' and name not in names:
                            raise ValueError('관절 이름 오류')
                        if name=='all' and active:
                            raise ValueError('동작을 먼저 멈추세요.')
                        selected=names if name=='all' else [name]
                        if action=='enable' and latched:
                            raise ValueError('정지 해제를 먼저 누르세요.')
                        halt()
                        if action=='enable':
                            positions={joint:read(joint) for joint in selected}
                            outside=[joint for joint,p in positions.items()
                                     if not calibration[joint]['range_min']<=p<=calibration[joint]['range_max']]
                            if outside:
                                raise ValueError('저장 범위 밖 관절: '+', '.join(outside))
                            for joint,p in positions.items():
                                if urgent.is_set():raise ValueError('정지 요청으로 토크 켜기 중단')
                                if not rows[joint]['torque_enabled']:
                                    write(joint,42,p)
                                    write(joint,40,1)
                        else:
                            for joint in selected:write(joint,40,0)
                        observe()
                    elif action=='jog':
                        token=cmd.get('token')
                        if not isinstance(token,str) or not 1<=len(token)<=80:raise ValueError('조그 입력 식별자가 없습니다.')
                        if token in revoked:continue
                        if time.monotonic()-cmd['_received']>.4:raise ValueError('오래된 조그 입력은 실행하지 않습니다.')
                        if latched:raise ValueError('정지 상태입니다. 정지 해제를 누르세요.')
                        name=cmd.get('joint');direction=cmd.get('direction');speed=float(cmd.get('speed',5))
                        if name not in names or direction not in [-1,1] or not math.isfinite(speed) or not 1<=speed<=15:
                            raise ValueError('조그 입력 범위 오류')
                        if not rows[name]['torque_enabled']:raise ValueError('해당 관절의 토크 켜기를 먼저 누르세요.')
                        if active and active.get('kind')=='move':raise ValueError('다축 이동 중입니다. 먼저 정지하세요.')
                        if active and (active['joint']!=name or active['direction']!=direction):
                            raise ValueError('한 번에 같은 방향의 관절 하나만 조작하세요.')
                        # Start from the servo's held goal, not the sagged feedback (no drop on press).
                        if not active:
                            held=float(read(name,42))
                            # static gravity sag already present at press time (shoulder_lift
                            # extended: >46 ticks) is not tracking error
                            active={'joint':name,'direction':direction,'goal':held,'offset':float(read(name))-held,'token':token,'lag_notice':False}
                        active.update(expires=cmd['_received']+.45,speed=speed)
                    elif action=='move':
                        if latched or active:raise ValueError('정지 해제 및 현재 동작 종료가 필요합니다.')
                        token=cmd.get('token');goal=cmd.get('target');expected=cmd.get('expected');duration=float(cmd.get('duration',5))
                        if not isinstance(token,str) or not 1<=len(token)<=80 or token in revoked:raise ValueError('이동 식별자 오류')
                        if not isinstance(goal,dict) or set(goal)!=set(names) or not isinstance(expected,dict) or set(expected)!=set(names):raise ValueError('6축 목표와 시작 위치가 필요합니다.')
                        if not math.isfinite(duration) or not 1<=duration<=20:raise ValueError('이동 시간은 1~20초입니다.')   # v0.2.68: small corrective moves 1s; peak speed still checked below
                        tolerance=cmd.get('arrival_tolerance_ticks',46)
                        arrival_mode=cmd.get('arrival_mode','target')
                        if arrival_mode not in ('target','settled'):raise ValueError('도착 판정 모드 오류')
                        if arrival_mode=='settled' and (cmd.get('grip_contact') or cmd.get('timed_close')):raise ValueError('정지 판정은 팔 위치 보정 전용입니다.')
                        displacement=cmd.get('arrival_displacement_ticks',{})
                        if isinstance(tolerance,dict):
                            if set(tolerance)!=set(names) or any(type(v)!=int or not 2<=v<=46 for v in tolerance.values()):raise ValueError('관절별 도착 오차는 2~46틱입니다.')
                            if not isinstance(displacement,dict) or any(n not in names or type(v)!=int for n,v in displacement.items()):raise ValueError('상대 이동량 오류')
                        elif type(tolerance)!=int or not 8<=tolerance<=46:raise ValueError('도착 허용 오차는 8~46틱입니다.')
                        observe();start={n:rows[n]['raw_ticks'] for n in names}
                        if cmd.get('gripper_only'):
                            goal=dict(start,gripper=goal['gripper'])
                        for n in names:
                            if type(goal[n]) not in (int,float) or not math.isfinite(goal[n]) or int(goal[n])!=goal[n]:raise ValueError('목표 ticks 정수 오류')
                            if type(expected[n]) not in (int,float) or not math.isfinite(expected[n]) or abs(start[n]-expected[n])>20:raise ValueError('시작 자세가 바뀌었습니다.')
                            if not calibration[n]['range_min']<=goal[n]<=calibration[n]['range_max']:raise ValueError(n+' 목표가 저장 범위 밖입니다.')
                            delta=abs(goal[n]-start[n])
                            if delta>3 and not rows[n]['torque_enabled']:raise ValueError(n+' 토크가 꺼져 있습니다.')
                            if delta*1.875/duration>135*4096/360:raise ValueError('3초 이동의 최대 속도 135도/초를 넘습니다. 경유 자세가 필요합니다.')
                        if cmd.get('grip_contact') and (goal['gripper']>=start['gripper'] or any(abs(goal[n]-start[n])>3 for n in names[:5])):
                            raise ValueError('접촉 후보 감지는 팔을 고정한 집게 닫기에만 사용합니다.')
                        if cmd.get('timed_close'):
                            if not cmd.get('grip_contact'):raise ValueError('시간 닫기는 팔 고정 집게 모드 전용')
                            if read('gripper',48)!=200:raise ValueError('추가 닫기 토크 제한은 200이어야 합니다.')
                            close_seconds=float(cmd.get('timed_close_seconds',1.5))
                            if not .3<=close_seconds<=5:raise ValueError('추가 닫기 시간은 0.3~5초입니다.')
                        # v0.2.50: interpolate arm joints from the servo's HELD goal. Starting from
                        # the sagged feedback first commanded the arm down by its gravity sag at every
                        # move start/stop (user: "멈출 때마다 처짐만큼 내려감").
                        held={n:start[n] for n in names}
                        for n in names[:5]:
                            if abs(goal[n]-start[n])>3:
                                h=read(n,42)
                                if abs(h-start[n])<=150:held[n]=h
                        sag={n:held[n]-start[n] for n in names}
                        motion={'token':token,'status':'running','target':goal,'started':time.time(),'contact_candidate':False,'arrival_tolerance_ticks':tolerance,'start_sag_ticks':{n:v for n,v in sag.items() if v}}
                        active={'kind':'move','token':token,'start':start,'target':goal,'duration':duration,'started':now,
                            'expires':cmd['_received']+.8,'goals':dict(held),'held':held,'sag':sag,'stable_since':None,'arrival_mode':arrival_mode,'arrival_tolerance_ticks':tolerance,'arrival_displacement_ticks':displacement,
                            'timed_close':bool(cmd.get('timed_close',False)),'timed_close_seconds':float(cmd.get('timed_close_seconds',1.5)),'grip_contact':bool(cmd.get('grip_contact',False)),'grip_last':start['gripper'],'grip_moved_at':now}
                    elif action=='move_heartbeat':
                        if active and active.get('kind')=='move' and active['token']==cmd.get('token'):
                            active['expires']=cmd['_received']+.8
                    elif action=='grip_force':
                        if active:raise ValueError('이동이 끝난 뒤 집게 힘 상한을 변경하세요.')
                        current=read('gripper',48);ratio=float(cmd.get('ratio',.2))
                        if not math.isfinite(ratio) or not .1<=ratio<=.5 or not 20<=current<=1000:raise ValueError('집게 힘 상한 값 확인 필요')
                        requested=(cmd.get('target') or {}).get('gripper')
                        if requested is not None:
                            if type(requested)!=int or not 20<=requested<=400:raise ValueError('집게 토크 상한은 20~400입니다.')
                            limit=requested
                        else:limit=max(20,round(current*ratio))
                        write('gripper',48,limit)
                        actual=read('gripper',48)
                        if actual!=limit:raise RuntimeError('집게 힘 상한 재조회 불일치')
                        grip_force={'previous_register':current,'limit_register':actual,'ratio_of_previous':actual/current,
                            'note':'집게 SRAM 토크 상한 · 실제 접촉력 N 측정값 아님'}
                        emit('notice',message=f'집게 토크 상한 {current} → {actual} · 다른 관절 변경 없음')
                    elif action=='grip_sample':
                        if ident:
                            load=read('gripper',60);current=read('gripper',69)
                            telemetry={'position_ticks':read('gripper'),'load_raw':load,'load_magnitude':load&1023,
                                'current_raw':current,'current_magnitude':current&32767,'torque_limit_register':read('gripper',48),
                                'temperature_c':read('gripper',63),'calibrated_contact_force':False}
                            emit('ack',request_id=ident,ok=True,telemetry=telemetry)
                            continue
                    elif action=='grip_contact_stop':
                        if not active or active.get('kind')!='move' or not active.get('grip_contact') or cmd.get('token')!=active['token']:
                            raise ValueError('현재 집게 닫기 동작과 접촉 식별자가 일치하지 않습니다.')
                        position=read('gripper')
                        write('gripper',42,position)
                        motion.update(status='contact_candidate',contact_candidate=True,contact_source='external_contact_guard',gripper_ticks=position)
                        active=None
                        emit('notice',message='영상·피드백 접촉 후보 · 현재 위치에서 추가 닫기 중단')
                    elif action=='snapshot':observe()
                    else:raise ValueError('지원하지 않는 명령')
                    if ident:
                        if action!='jog':observe()
                        emit('ack',request_id=ident,ok=True,joints=list(rows.values()),active=active,latched=latched,motion=motion,grip_force=grip_force)
                except Exception as exc:
                    halt(True)
                    emit('error',message=str(exc))
                    if ident:emit('ack',request_id=ident,ok=False,message=str(exc))
            if not running:break
            if active:
                if time.monotonic()>active['expires']:
                    halt(True);emit('error',message='버튼 유지 신호 만료 · 조그 정지')
                elif active.get('kind')=='move':
                    elapsed=now-active['started'];u=min(1.,elapsed/active['duration']);blend=10*u**3-15*u**4+6*u**5
                    positions={n:read(n) for n in names}
                    if active.get('timed_close'):
                        if read('gripper',63)>=55:raise RuntimeError('집게 온도 상한')
                        if elapsed>=active.get('timed_close_seconds',1.5):
                            write('gripper',42,positions['gripper'])
                            motion.update(status='complete',contact_source='timed_close_unverified',gripper_ticks=positions['gripper'])
                            active=None
                            continue
                    contact=False
                    for n in names:
                        if abs(active['target'][n]-active['start'][n])<=3:continue
                        base=active.get('held',active['start'])[n]
                        goal=round(base+blend*(active['target'][n]-base))
                        error=active['goals'][n]-positions[n]-active.get('sag',{}).get(n,0)
                        if n=='gripper' and active.get('timed_close'):
                            # Stop at a rigid contact too, even with no initial travel.
                            # Keep torque enabled and hold measured position.
                            if abs(positions[n]-active['grip_last'])>=3:
                                active['grip_last']=positions[n];active['grip_moved_at']=now
                            if error<-5 and now-active['grip_moved_at']>=2:
                                contact=True
                                motion['contact_source']='timed_close_stall_unverified'
                                break
                            # No 8-tick clamp in this timed, torque-limited phase.
                        elif n=='gripper' and active['grip_contact']:
                            if abs(positions[n]-active['grip_last'])>=3:active['grip_last']=positions[n];active['grip_moved_at']=now
                            traveled=abs(positions[n]-active['start'][n])
                            if error<-10 and now-active['grip_moved_at']>.8 and traveled<20:
                                halt(True);motion['status']='failed';emit('error',message='집게가 닫히기 시작하지 않음 · 접촉 성공으로 처리하지 않음');break
                            if error<-5 and now-active['grip_moved_at']>.35 and traveled>=20:contact=True;break
                            # Soft objects must not be squeezed until a motor stalls.
                            # Bound the unachieved closing command to ~0.7 encoder degrees.
                            goal=max(goal,positions[n]-8)
                        elif abs(error)>90:raise RuntimeError(n+' 다축 추종 오차 90틱(약 7.9도) 초과')
                        write(n,42,goal);active['goals'][n]=goal
                    if active is None:pass
                    elif contact:
                        write('gripper',42,positions['gripper'])
                        motion.update(status='contact_candidate',contact_candidate=True,gripper_ticks=positions['gripper']);active=None
                        emit('notice',message='집게 정체 감지 · 접촉 후보에서 닫기 정지 (성공 확정 아님)')
                    elif u>=1:
                        # Final approach can require finer arm arrival without
                        # changing speed, torque, contact closing, or following guards.
                        motion['arrival_error_ticks']={n:positions[n]-active['target'][n] for n in names}
                        settled=active.get('arrival_mode')=='settled'
                        arrived=settled_at_target(positions,active,names,now) if settled else arrived_at_target(positions,active,names)
                        if settled and arrived:motion['status']='complete';active=None
                        elif arrived:
                            if active['stable_since'] is None:active['stable_since']=now
                            if now-active['stable_since']>.25:motion['status']='complete';active=None
                        elif active:active['stable_since']=None
                        if active and elapsed>active['duration']+5:
                            halt(True);motion['status']='failed';emit('error',message='다축 목표 도착 확인 시간 초과 · 위치 유지 정지')
                else:
                    name=active['joint'];cal=calibration[name];p=read(name)
                    lag=abs(p-active['goal']-active.get('offset',0.))
                    # v0.2.46: under gravity a loaded joint lags its ramping goal; 46 ticks was
                    # fatal for normal jogging. Hold the goal while the joint catches up and stop
                    # only on a real blockage (90 ticks, same as the multi-axis guard).
                    # v0.2.49: shoulder_lift at full reach needs a larger position error before the
                    # servo (low P gain) produces enough torque to lift; a 46-tick lead stalled it
                    # (user had to help by hand). Lead the goal up to 150 ticks; fatal only when the
                    # joint is pushed back beyond that (210).
                    if lag>210:raise RuntimeError(name+' 조그 추종 오차 210틱(약 18도) 초과 · 막힘 또는 과부하')
                    if lag>150:
                        # no `continue`: the loop must still emit state and sleep
                        velocity=0.
                        if not active['lag_notice']:active['lag_notice']=True;emit('notice',message=name+' 추종 지연 · 따라올 때까지 목표 유지')
                    else:
                        target_velocity=active['direction']*active['speed']*4096/360
                        acceleration=30*4096/360
                        velocity+=max(-acceleration*dt,min(acceleration*dt,target_velocity-velocity))
                        goal=max(cal['range_min'],min(cal['range_max'],active['goal']+velocity*dt))
                        write(name,42,round(goal));active['goal']=goal
                        if goal in (cal['range_min'],cal['range_max']):
                            halt();emit('notice',message='저장된 관절 범위 끝 · 정지')
            if now-last_state>=.2:
                observe();emit('state',joints=list(rows.values()),active=active,latched=latched,motion=motion,grip_force=grip_force,writes=writes,time=time.time())
                last_state=now
            time.sleep(.015)
    finally:
        try:halt(True)
        finally:port.closePort()
        emit('closed',message='연결 종료 · 켜져 있던 토크는 위치 유지를 위해 유지')


if __name__=='__main__':
    try:main()
    except Exception as exc:emit('fatal',message=str(exc));sys.exit(1)
