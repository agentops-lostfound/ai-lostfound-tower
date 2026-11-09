"""OpenCV keyboard robot panel. Simulation by default; explicit hold startup optional."""
import argparse
import time
from pathlib import Path
import threading
import json
import os

import cv2
import numpy as np

from robot.panel_core import Panel,KEYS,JOINTS,SPEEDS,import_recorded_poses
from robot.panel_transport import Simulation,Studio
from robot.panel_lock import PanelLock


class CameraPreview:
    def __init__(self,url):
        self.frame=None;self.closed=False
        def receive():
            cap=cv2.VideoCapture(url)
            try:
                while not self.closed:
                    ok,frame=cap.read()
                    if not ok:break
                    self.frame=frame
            finally:cap.release()
        threading.Thread(target=receive,daemon=True).start()


def render(panel,backend,editing='',camera=None,scale=0.8125):
    image=np.full((800,1280,3),(24,23,20),dtype=np.uint8)
    def text(value,x,y,color=(220,220,220),size=0.55):
        cv2.putText(image,str(value),(x,y),cv2.FONT_HERSHEY_SIMPLEX,size,color,1,cv2.LINE_AA)
    text('SO-101 | KEYBOARD CONTROL',25,38,size=0.85)
    text('LIVE / STUDIO' if backend.live else 'SIMULATION - NO ROBOT',810,38,(70,180,255),0.65)
    color=(75,75,250) if panel.stopped else (90,220,130)
    text('SOFTWARE STOP LATCHED' if panel.stopped else ('MOVING ONE STAGE' if panel.moving else 'HOLD / TARGET PREVIEW'),25,80,color,0.7)
    text('Normalized values, NOT degrees | Gripper motion locked',25,115,(160,170,180))
    text('JOINT',45,160);text('MEASURED',320,160);text('TARGET',485,160)
    for i,name in enumerate(JOINTS):
        y=205+i*52
        if i==panel.selected:cv2.rectangle(image,(22,y-30),(640,y+12),(60,65,50),-1)
        text(f'{i+1}  {name}',35,y)
        text('--' if panel.current is None else f'{panel.current[KEYS[i]]:8.3f}',320,y)
        text('--' if panel.target is None else f'{panel.target[KEYS[i]]:8.3f}',485,y,(100,220,240))
    text(f'SPEED {panel.speed}: <= {SPEEDS[panel.speed]:.2f} normalized/command, <=8Hz',25,550)
    text('Not a physical speed or collision guarantee',25,580,(130,170,220))
    text('POSES: '+', '.join(panel.poses),25,620)
    text(panel.message[:110],25,662,(100,210,255))
    if editing:text('INPUT: '+editing+'  [Enter apply / Space stop]',25,705,(130,240,200),0.7)
    else:text('SPACE STOP | R repair | Enter review/confirm | ESC quit',25,705,(130,240,200))
    text('Physical emergency stop/power access must remain available.',25,758,(100,150,255))
    if camera is not None and camera.frame is not None:
        frame=camera.frame;h,w=frame.shape[:2];ratio=min(580/w,330/h)
        resized=cv2.resize(frame,(int(w*ratio),int(h*ratio)))
        image[100:100+resized.shape[0],675:675+resized.shape[1]]=resized
    else:
        text('Optional wrist preview: --camera-url URL',685,135,(140,150,160))
    help_lines=['1..6 select joint | +/- adjust target only','T enter exact selected-joint target',
                'Z/X/C speed levels 1/2/3','S save measured pose by name | L load pose',
                'H preview home | N next preset | B reverse order',
                'V append CSV | A toggle 1Hz CSV logging',
                'No automatic full-route replay; confirm each stage.',
                'Repair resets target, does NOT home/recalibrate.',
                'Other Studio clients must not control simultaneously.']
    for i,line in enumerate(help_lines):text(line,675,460+i*27,size=0.48)
    if scale!=1:
        image=cv2.resize(image,(round(1280*scale),round(800*scale)),interpolation=cv2.INTER_CUBIC)
    return image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Requires patched Studio; attaches existing hold runtime only')
    parser.add_argument('--connect-studio',action='store_true',help='Explicitly start configured Studio environment in hold if no session exists')
    parser.add_argument('--studio',default='http://localhost:7860')
    parser.add_argument('--project-id',default='7840975d-960f-4ede-bcca-bd24e4caf24e')
    parser.add_argument('--follower-id',default='bc50f050-d0a5-4430-af97-0486cdaec3a2')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--import-recorded',type=Path,help='Explicitly import saved pose snapshots')
    parser.add_argument('--camera-url',help='Optional MJPEG preview; never changes camera settings')
    parser.add_argument('--render-only',type=Path,help='Save simulation screenshot and exit; no window/hardware')
    parser.add_argument('--scale',type=float,default=0.8125,help='UI scale: 0.8125=1040x650, 1=1280x800')
    args=parser.parse_args()
    if not 0.5<=args.scale<=3:parser.error('--scale must be between 0.5 and 3')
    if args.live and args.render_only:parser.error('--render-only is simulation only')
    folder=args.output_dir or Path('outputs/robot_panel_live' if args.live else 'outputs/robot_panel_sim')
    # A common lock per mode also protects invocations with different output directories.
    lock=PanelLock(Path(__file__).resolve().parents[1]/'outputs'/('robot_panel_live' if args.live else 'robot_panel_sim')/'panel.lock')
    panel=Panel(folder)
    if args.import_recorded:import_recorded_poses(panel,args.import_recorded)
    try:
        backend=Studio(args.studio,args.project_id,args.follower_id,connect=args.connect_studio) if args.live else Simulation()
    except Exception:
        lock.close();raise
    camera=CameraPreview(args.camera_url) if args.camera_url and not args.render_only else None
    editing='';text_input='';auto_csv=False;last_csv=0;last_step=0;last_status=0
    title='SO101 - LIVE' if args.live else 'SO101 - SIMULATION'
    try:
        if args.render_only:
            panel.observe(backend.snapshot());args.render_only.parent.mkdir(parents=True,exist_ok=True)
            if not cv2.imwrite(str(args.render_only),render(panel,backend,scale=args.scale)):raise OSError('Cannot save preview')
            return
        cv2.namedWindow(title,cv2.WINDOW_NORMAL)
        cv2.resizeWindow(title,round(1280*args.scale),round(800*args.scale))
        while True:
            now=time.monotonic()
            values=backend.snapshot()
            if values is not None:panel.observe(values)
            if now-last_status>=1:
                status={'pid':os.getpid(),'live':backend.live,'fresh':backend.fresh(),
                        'error':backend.error,'measured':values,'moving':panel.moving,
                        'stopped':panel.stopped,'recorded_at_unix':time.time(),
                        'failure':getattr(backend,'failure',None)}
                temp=folder/'connection_status.tmp'
                temp.write_text(json.dumps(status,indent=2),encoding='utf-8')
                temp.replace(folder/'connection_status.json');last_status=now
            if backend.live and (backend.error or not backend.fresh() or backend.mode!='hold'):
                if not panel.stopped:
                    panel.stop(backend.error or ('External control mode changed' if backend.mode!='hold' else 'Stale observations'))
                    try:backend.stop()
                    except Exception:pass
                panel.message=backend.error or ('External mode changed; repair required' if backend.mode!='hold' else 'Waiting for fresh observations / patched Studio')
            try:
                if panel.moving and now-last_step>=0.125 and backend.ready():
                    point=panel.next_step()
                    if panel.stopped:backend.stop()
                    if point is not None:
                        backend.step(point,panel.current);panel.commanded=dict(point);last_step=now
                if auto_csv and values is not None and backend.fresh() and now-last_csv>=1:
                    panel.export_csv();last_csv=now
            except Exception as exc:
                panel.stop(str(exc))
                try:backend.stop()
                except Exception:pass
            cv2.imshow(title,render(panel,backend,editing+': '+text_input if editing else '',camera,args.scale))
            key=cv2.waitKeyEx(20)
            if key==-1:
                if cv2.getWindowProperty(title,cv2.WND_PROP_VISIBLE)<1:break
                continue
            if key==27:break
            try:
                if key==32:
                    panel.stop();editing='';text_input='';backend.stop();continue
                if editing:
                    if key in (10,13):
                        if editing=='target':panel.edit(panel.selected,float(text_input))
                        elif editing=='save':
                            if not backend.fresh():raise ValueError('Stale observation')
                            panel.save(text_input)
                        elif editing=='load':panel.load(text_input)
                        editing='';text_input=''
                    elif key in (8,127):text_input=text_input[:-1]
                    elif 33<=key<=126 and len(text_input)<40:text_input+=chr(key)
                    continue
                ch=chr(key).lower() if 0<=key<128 else ''
                if ch in '123456' and ch:panel.selected=int(ch)-1
                elif ch in ('z','x','c'):panel.speed={'z':1,'x':2,'c':3}[ch];panel.confirm_pending=False
                elif ch in ('+','=','-'):panel.edit(panel.selected,panel.target[KEYS[panel.selected]]+(1 if ch!='-' else -1))
                elif ch in ('t','s','l'):
                    if panel.moving:raise ValueError('Stop before editing')
                    editing={'t':'target','s':'save','l':'load'}[ch];text_input=''
                elif ch=='r':
                    if backend.live and (backend.error or not backend.fresh()):
                        backend.close()
                        panel.stop('Reconnecting; wait for numbers, then press R again')
                        backend=Studio(args.studio,args.project_id,args.follower_id,connect=args.connect_studio)
                        continue
                    if not backend.fresh():raise ValueError('Fresh observations required')
                    backend.repair();panel.repair()
                elif ch=='h':panel.load('home')
                elif ch=='n':
                    name=panel.sequence[panel.sequence_index%len(panel.sequence)]
                    panel.load(name);panel.sequence_index+=1
                elif ch=='b':panel.sequence.reverse();panel.sequence_index=0;panel.message='Preset order reversed; N previews next'
                elif ch=='v':
                    if not backend.fresh():raise ValueError('Stale observation')
                    panel.export_csv()
                elif ch=='a':auto_csv=not auto_csv;panel.message='CSV logging '+str(auto_csv)
                elif key in (10,13):
                    if not backend.ready():raise ValueError('Backend not ready; patch/hold/fresh observation required')
                    panel.confirm()
            except Exception as exc:panel.message=str(exc)
    finally:
        panel.stop('Panel closed')
        if camera:camera.closed=True
        try:backend.close()
        finally:cv2.destroyAllWindows();lock.close()


if __name__=='__main__':main()
