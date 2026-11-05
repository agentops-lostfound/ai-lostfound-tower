"""SO-101 button teaching panel. Simulation default; live requires explicit --live.

Live mode uses a dedicated so101-control/LeRobot worker in WSL.
No automatic motions, calibration, runtime restart, or collision validation.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shutil
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from robot.panel_core import Panel, KEYS, JOINTS, SPEEDS, import_recorded_poses
from robot.panel_transport import Simulation, Studio
from robot.panel_lock import PanelLock
from robot.vendor_backend import VendorBackend, STAGE_SECONDS


DEFAULT_PROJECT = '7840975d-960f-4ede-bcca-bd24e4caf24e'
DEFAULT_FOLLOWER = 'bc50f050-d0a5-4430-af97-0486cdaec3a2'
CUSTOM_POSES = tuple(f'pose_{i}' for i in range(1, 6))


class TeachingGUI:
    def __init__(self, root, panel, backend, output, lock, camera_urls=None):
        self.root, self.panel, self.backend, self.output, self.lock = root, panel, backend, output, lock
        self.output.mkdir(parents=True, exist_ok=True)
        self.closed = False
        self.stage_motion=getattr(backend,'stage_motion',False)
        self.last_step = self.last_status = self.last_csv = 0.0
        self.auto_csv = tk.BooleanVar(value=False)
        self.jog_delta = tk.StringVar(value='0.1')
        self.pose_name = tk.StringVar(value='')
        self.mode_text = tk.StringVar(value='STOPPED')
        self.status_text = tk.StringVar(value='Read-only until Repair. Motion needs two approvals.')
        self.speed = tk.IntVar(value=1)
        self.route_cursor = {'forward': 0, 'reverse': 3}
        self.measured = [tk.StringVar(value='--') for _ in JOINTS]
        self.targets = [tk.StringVar(value='--') for _ in JOINTS]
        self.errors = [tk.StringVar(value='--') for _ in JOINTS]
        self._target_entries = []
        self._displayed_target = None
        self.camera_widgets = {}
        self.camera_sources = {}
        self.camera_images = {}
        self.last_camera_update = 0.0
        self._build()
        if camera_urls:
            # Only the explicitly requested streams are opened. No USB camera capture here.
            from robot.control_panel import CameraPreview
            for name, url in camera_urls.items():
                self.camera_sources[name] = CameraPreview(url)
        self._refresh_pose_names()
        root.protocol('WM_DELETE_WINDOW', self._close)
        root.after(100, self._tick)

    def _build(self):
        root = self.root
        root.title('SO-101 Teaching Pendant | SIMULATION' if not self.backend.live else 'SO-101 Teaching Pendant | LIVE')
        root.geometry('1190x800')
        root.minsize(930, 660)
        outer = ttk.Frame(root, padding=12)
        outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer)
        header.pack(fill='x')
        ttk.Label(header, text='SO-101 Teaching Pendant', font=('Segoe UI', 18, 'bold')).pack(side='left')
        ttk.Label(header, textvariable=self.mode_text, foreground='#ba3b35', font=('Segoe UI', 12, 'bold')).pack(side='right')
        ttk.Label(outer, text='Saved pose units: normalized | gripper locked | '+('Driver: so101-control / LeRobot | 10 deg following cap | max 5s' if self.stage_motion else 'Simulation / legacy Studio'), foreground='#a24521').pack(anchor='w', pady=(4,8))

        mid = ttk.Panedwindow(outer, orient='horizontal')
        mid.pack(fill='both', expand=True)
        left = ttk.Frame(mid, padding=6)
        right = ttk.Frame(mid, padding=6)
        mid.add(left, weight=3)
        mid.add(right, weight=2)

        # Headers and all joint rows share one grid, so their columns stay aligned.
        self.joint_table = ttk.Frame(left)
        self.joint_table.pack(fill='x')
        self.joint_table.columnconfigure(2, weight=1)
        self.joint_headers = []
        for column, (label, width, anchor) in enumerate((
                ('Joint', 19, 'w'), ('Measured', 11, 'e'),
                ('Target input', 13, 'center'), ('Error', 9, 'e'))):
            heading = ttk.Label(self.joint_table, text=label, width=width,
                                anchor=anchor, font=('Segoe UI', 9, 'bold'))
            heading.grid(row=0, column=column, padx=3, pady=(0,8), sticky='ew')
            self.joint_headers.append(heading)
        ttk.Label(self.joint_table, text='Jog', anchor='center',
                  font=('Segoe UI', 9, 'bold')).grid(
                      row=0, column=4, columnspan=2, padx=1, pady=(0,8), sticky='ew')
        ttk.Label(self.joint_table, text='Apply', anchor='center',
                  font=('Segoe UI', 9, 'bold')).grid(
                      row=0, column=6, padx=1, pady=(0,8), sticky='ew')
        self.joint_cells = []
        for i, name in enumerate(JOINTS):
            row = i + 1
            label = ttk.Label(self.joint_table, text=f'{i+1} {name}', width=19, anchor='w')
            label.grid(row=row, column=0, padx=3, pady=4, sticky='ew')
            measured = ttk.Label(self.joint_table, textvariable=self.measured[i], width=11, anchor='e')
            measured.grid(row=row, column=1, padx=3, pady=4, sticky='ew')
            entry = ttk.Entry(self.joint_table, textvariable=self.targets[i], width=13, justify='right')
            entry.grid(row=row, column=2, padx=3, pady=4, sticky='ew')
            self._target_entries.append(entry)
            error = ttk.Label(self.joint_table, textvariable=self.errors[i], width=9, anchor='e')
            error.grid(row=row, column=3, padx=3, pady=4, sticky='ew')
            minus = ttk.Button(self.joint_table, text='−', width=4, command=lambda n=i: self._jog(n, -1))
            plus = ttk.Button(self.joint_table, text='+', width=4, command=lambda n=i: self._jog(n, 1))
            apply_btn = ttk.Button(self.joint_table, text='Apply', width=7, command=lambda n=i: self._edit(n))
            minus.grid(row=row, column=4, padx=1, pady=4)
            plus.grid(row=row, column=5, padx=1, pady=4)
            apply_btn.grid(row=row, column=6, padx=1, pady=4)
            self.joint_cells.append((label, measured, entry, error, minus, plus, apply_btn))
            if i == 5:
                entry.configure(state='disabled');minus.configure(state='disabled')
                plus.configure(state='disabled');apply_btn.configure(state='disabled')
        settings = ttk.LabelFrame(left, text='Jog / speed', padding=8)
        settings.pack(fill='x', pady=8)
        ttk.Label(settings, text='Jog delta (normalized)').pack(side='left')
        ttk.Entry(settings, textvariable=self.jog_delta, width=7).pack(side='left', padx=6)
        for level in (1,2,3):
            label=f'{level} ({STAGE_SECONDS[level]:g}s)' if self.stage_motion else f'{level} ({SPEEDS[level]})'
            ttk.Radiobutton(settings, text=label, variable=self.speed, value=level, command=self._set_speed).pack(side='left', padx=4)
        ttk.Label(left, text='Stage duration 5 / 4 / 3 seconds (includes final target hold).' if self.stage_motion else 'Speed means max normalized step per command, NOT a verified physical velocity.').pack(anchor='w')

        route = ttk.LabelFrame(left, text='Saved poses / route (one stage only)', padding=8)
        route.pack(fill='x', pady=8)
        self.pose_list = ttk.Combobox(route, textvariable=self.pose_name, state='normal', width=26)
        self.pose_list.grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(route, text='Load preview', command=self._load).grid(row=0, column=1, padx=4)
        ttk.Button(route, text='Save measured / overwrite', command=self._save).grid(row=0, column=2, padx=4)
        shortcut = ttk.Frame(route)
        shortcut.grid(row=1, column=0, columnspan=3, sticky='w')
        for nm in ('home','raised','entry','observe'):
            ttk.Button(shortcut, text=nm, command=lambda name=nm: self._load(name)).pack(side='left', padx=3)
        custom = ttk.Frame(route)
        custom.grid(row=2, column=0, columnspan=3, sticky='w', pady=(4,0))
        self.custom_pose_buttons = {}
        for number, name in enumerate(CUSTOM_POSES, 1):
            button = ttk.Button(custom, text=f'커스텀 {number}', width=10,
                                command=lambda pose=name: self._load(pose))
            button.pack(side='left', padx=3)
            self.custom_pose_buttons[name] = button
        navigation = ttk.Frame(route)
        navigation.grid(row=3, column=0, columnspan=3, sticky='w')
        ttk.Button(navigation, text='Next forward preview', command=lambda: self._preview_route('forward')).pack(side='left', padx=3)
        ttk.Button(navigation, text='Next reverse preview', command=lambda: self._preview_route('reverse')).pack(side='left', padx=3)
        controls = ttk.LabelFrame(left, text='Stage movement / operator authority', padding=8)
        controls.pack(fill='x', pady=8)
        ttk.Button(controls, text='1. Review target', command=self._review).pack(side='left', padx=3)
        ttk.Button(controls, text='2. Approve ONE stage', command=self._approve).pack(side='left', padx=3)
        ttk.Button(controls, text='SOFTWARE STOP', command=self._stop).pack(side='left', padx=3)
        ttk.Button(controls, text='Repair HOLD', command=self._repair).pack(side='left', padx=3)
        log = ttk.Frame(left)
        log.pack(fill='x')
        ttk.Button(log, text='Save measured CSV', command=self._save_csv).pack(side='left', padx=4)
        ttk.Checkbutton(log, text='1Hz CSV', variable=self.auto_csv).pack(side='left')
        ttk.Label(left, textvariable=self.status_text, wraplength=660, foreground='#255e87').pack(anchor='w', fill='x', pady=12)

        cams = ttk.LabelFrame(right, text='Camera previews (optional URLs; never claim camera locks)', padding=8)
        cams.pack(fill='both', expand=True)
        for name in ('topview','wrist'):
            frame = ttk.LabelFrame(cams, text=name, padding=4)
            frame.pack(fill='both', expand=True, pady=4)
            label = ttk.Label(frame, text='Not configured / no frame', anchor='center')
            label.pack(fill='both', expand=True)
            self.camera_widgets[name] = label

    def _safe(self, fn):
        try:
            return fn()
        except Exception as exc:
            self.status_text.set(f'{type(exc).__name__}: {exc}')
            return None

    def _require_fresh(self):
        if not self.backend.fresh() or self.panel.current is None:
            raise RuntimeError('Fresh robot observation required')
        if self.backend.live and (self.backend.mode != 'hold' or self.backend.error):
            raise RuntimeError('Healthy HOLD connection required')

    def _set_speed(self):
        if self.panel.moving:
            self.speed.set(self.panel.speed)
            self.status_text.set('Finish or stop this stage before changing duration')
            return
        self.panel.speed = self.speed.get()
        self.panel.confirm_pending = False
        self.status_text.set(f'Speed level {self.panel.speed}; previous review cancelled')

    def _edit(self, index):
        def act():
            self._require_fresh()
            if self.panel.stopped: raise RuntimeError('Repair required before editing')
            self.panel.edit(index, float(self.targets[index].get()))
            self.targets[index].set(f'{self.panel.target[KEYS[index]]:.3f}')
            self._displayed_target=dict(self.panel.target)
            self.status_text.set('Target staged only. Nothing moved.')
        self._safe(act)

    def _jog(self,index,sign):
        def act():
            self._require_fresh()
            if self.panel.stopped: raise RuntimeError('Repair required before jogging')
            d=float(self.jog_delta.get())
            if not 0<d<=0.5:raise ValueError('Jog delta must be in (0, 0.5] normalized')
            self.panel.edit(index,self.panel.target[KEYS[index]] + sign*d)
            self.targets[index].set(f'{self.panel.target[KEYS[index]]:.3f}')
            self._displayed_target=dict(self.panel.target)
            self.status_text.set('Jog changed TARGET only. Review and approve before physical movement.')
        self._safe(act)

    def _preview_route(self, direction):
        def act():
            idx=self.route_cursor[direction]
            if not 0 <= idx < len(self.panel.sequence):
                raise RuntimeError('Route boundary reached; select a pose manually or start a new sequence')
            name=self.panel.sequence[idx]
            self._load(name)
            if self.pose_name.get()==name and self.panel.message.startswith('Preview '):
                self.route_cursor[direction] += 1 if direction=='forward' else -1
        self._safe(act)

    def _refresh_pose_names(self):
        self.pose_list.configure(values=sorted(self.panel.poses))
        for name, button in self.custom_pose_buttons.items():
            button.configure(state='normal' if name in self.panel.poses else 'disabled')

    def _load(self, name=None):
        def act():
            self._require_fresh()
            if self.panel.stopped: raise RuntimeError('Repair HOLD before staging a pose')
            pose=(name or self.pose_name.get()).strip()
            self.panel.load(pose)
            for j,k in enumerate(KEYS):self.targets[j].set(f'{self.panel.target[k]:.3f}')
            self._displayed_target=dict(self.panel.target)
            self.pose_name.set(pose)
            self.status_text.set(f'{pose}: preview only. Check clearance and review before moving.')
        self._safe(act)

    def _save(self):
        def act():
            self._require_fresh()
            if self.panel.stopped or self.panel.moving or getattr(self.backend,'pending',None) is not None:
                raise RuntimeError('Save only in stable, non-stopped HOLD (no pending motion)')
            name=self.pose_name.get().strip()
            if not name:raise ValueError('Enter a pose name')
            exists = name in self.panel.poses
            if not messagebox.askyesno('Save measured pose',f'{"OVERWRITE" if exists else "CREATE"} {name}?\nThis saves CURRENT MEASURED joints, not targets.'):
                return
            # Preserve old data on overwrite; no data read from private config.
            if exists and self.panel.pose_file.exists():
                backup=self.panel.pose_file.with_name('poses.backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
                shutil.copy2(self.panel.pose_file,backup)
            self.panel.save(name)
            self._refresh_pose_names()
            self.status_text.set(self.panel.message)
        self._safe(act)

    def _review(self):
        def act():
            # Reviewing again must never act as the second (movement) approval.
            self.panel.confirm_pending = False
            self._require_fresh()
            if self.panel.stopped or self.panel.moving: raise RuntimeError('Repair or finish current movement first')
            if not self.backend.ready():raise RuntimeError(self.backend.error or 'Transport not ready')
            for i in range(5):
                value=float(self.targets[i].get())
                if not math.isfinite(value) or abs(value - self.panel.target[KEYS[i]]) > 0.0006:
                    raise ValueError('Unapplied target input. Press Apply on the edited joint before review.')
            diffs = [abs(self.panel.target[k]-self.panel.current[k]) for k in KEYS[:5]]
            max_delta=max(diffs)
            msg=(f'Current → target (Studio normalized units)\n\n'
                 + '\n'.join(f'{nm}: {self.panel.current[k]:.4f} → {self.panel.target[k]:.4f}' for nm,k in zip(JOINTS,KEYS))
                 + f'\n\nMaximum arm joint delta: {max_delta:.4f}'
                 + (f'\nso101-control: {STAGE_SECONDS[self.panel.speed]:g}s stage, 10 degree following cap'
                    if self.stage_motion else f'\nSpeed level: {self.panel.speed} (max {SPEEDS[self.panel.speed]}/step)')
                 + '\n\nNO COLLISION CHECK. Intermediate joint path may hit the lip.\nReview physical clearance and emergency stop access.')
            if not messagebox.askyesno('Review proposed ONE-stage movement',msg):return
            self.panel.confirm()  # first confirmation only
            self.status_text.set('First approval recorded. Press Approve ONE stage for a separate final confirmation.')
        self._safe(act)

    def _approve(self):
        def act():
            self._require_fresh()
            if not self.panel.confirm_pending:raise RuntimeError('First press Review target')
            if not self.backend.ready():raise RuntimeError(self.backend.error or 'Transport not ready')
            for i in range(5):
                value = float(self.targets[i].get())
                if not math.isfinite(value) or abs(value-self.panel.target[KEYS[i]]) > 0.0006:
                    self.panel.confirm_pending=False
                    raise ValueError('Target input changed; Apply and Review again')
            if not messagebox.askyesno('Final stage approval','Is the path CLEAR and the physical STOP accessible?\nMove this ONE stage using the reviewed duration?'):
                self.panel.confirm_pending=False
                return
            self._require_fresh()
            if not self.panel.confirm_pending or not self.backend.ready():
                raise RuntimeError('State changed during approval; review again')
            self.panel.confirm()
            if self.stage_motion:
                try:self.backend.start_stage(dict(self.panel.target),dict(self.panel.current),self.panel.speed)
                except Exception:
                    self.panel.stop('Stage could not start; repair and review required')
                    self.backend.stop()
                    raise
            self.status_text.set('ONE stage authorized; monitoring physical observations')
        self._safe(act)

    def _stop(self):
        self.panel.stop('Operator software stop latched')
        self.panel.confirm_pending = False
        self.status_text.set('STOP requested (software only); hardware E-stop remains necessary.')
        self._safe(self.backend.stop)

    def _repair(self):
        def act():
            if not self.backend.fresh() or self.panel.current is None:
                raise RuntimeError('Fresh observations required; reconnect if disconnected')
            if self.backend.live and self.backend.mode != 'hold':
                raise RuntimeError('HOLD required')
            if self.panel.moving or getattr(self.backend,'pending',None) is not None:
                raise RuntimeError('Pending movement; do not repair')
            if not messagebox.askyesno('Manual repair','Robot is supported, path clear, and error cause addressed?\nRepair HOLD only (does not home or move to saved pose).'):
                return
            self.backend.repair()
            self.panel.repair()
            self.status_text.set('Repaired; no motion. Review target again for each stage.')
        self._safe(act)

    def _save_csv(self):
        def act():
            self._require_fresh()
            self.panel.export_csv()
            self.status_text.set(self.panel.message)
        self._safe(act)

    def _record_status(self, now, values):
        if now-self.last_status<1:return
        payload={'pid':os.getpid(), 'live':self.backend.live, 'fresh':self.backend.fresh(),
                 'error':self.backend.error, 'measured':values, 'moving':self.panel.moving,
                 'stopped':self.panel.stopped,'recorded_at_unix':time.time(),
                 'failure':getattr(self.backend,'failure',None)}
        payload['driver']=getattr(self.backend,'name','studio' if self.backend.live else 'simulation')
        payload['message']=self.panel.message
        tmp=self.output/'connection_status.tmp'
        tmp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        tmp.replace(self.output/'connection_status.json')
        self.last_status=now

    def _tick(self):
        if self.closed:return
        now=time.monotonic()
        try:
            values=self.backend.snapshot()
            if values is not None:self.panel.observe(values)
            if self.backend.live and (self.backend.error or not self.backend.fresh() or self.backend.mode!='hold'):
                if not self.panel.stopped:
                    self.panel.stop(self.backend.error or 'Studio mode/observation unsafe')
                    try:self.backend.stop()
                    except Exception:pass
                self.status_text.set(self.backend.error or 'Studio disconnected or not in HOLD')
            if self.panel.moving and self.stage_motion:
                result=self.backend.result
                if result is not None:
                    self.backend.result=None
                    self.panel.moving=False;self.panel.armed=False
                    residual=max(result.get('errors_degrees',{}).values(),default=0)
                    self.panel.message=f'Stage finished; max residual {residual:.2f} deg. Check pose before next stage.'
                    self.status_text.set(self.panel.message)
            elif self.panel.moving:
                # ready() deliberately checks pending and can set failure on timeout.
                ready=self.backend.ready()
                if self.backend.error:
                    self.panel.stop(self.backend.error)
                    try:self.backend.stop()
                    except Exception:pass
                elif ready and now-self.last_step>=0.125:
                    point=self.panel.next_step()
                    if self.panel.stopped:
                        self.backend.stop()
                        self.status_text.set(self.panel.message)
                    if point is not None:
                        self.backend.step(point,self.panel.current)
                        self.panel.commanded=dict(point)
                        self.last_step=now
            if self.auto_csv.get() and values is not None and self.backend.fresh() and now-self.last_csv>=1:
                self.panel.export_csv();self.last_csv=now
            for i,key in enumerate(KEYS):
                self.measured[i].set('--' if self.panel.current is None else f'{self.panel.current[key]:.3f}')
                self.errors[i].set('--' if self.panel.current is None or self.panel.target is None else f'{abs(self.panel.current[key]-self.panel.target[key]):.3f}')
                # Don't overwrite a target entry while the user is editing it.
                # Preserve un-applied input even after focus moves to a button.
                if self.panel.target is not None and (self._displayed_target is None or
                        self._displayed_target.get(key) != self.panel.target[key]):
                    self.targets[i].set(f'{self.panel.target[key]:.3f}')
            self._displayed_target = dict(self.panel.target) if self.panel.target is not None else None
            self.mode_text.set(('LIVE' if self.backend.live else 'SIM')+' | '+('ERROR' if self.backend.error else 'STOPPED' if self.panel.stopped else 'MOVING' if self.panel.moving else 'HOLD') + ('' if self.backend.fresh() else ' | STALE'))
            if not self.panel.moving and self.panel.message.startswith('Target reached'):
                self.status_text.set(self.panel.message)
            self._record_status(now,values)
            if now-self.last_camera_update>0.5:
                self._refresh_cameras();self.last_camera_update=now
        except Exception as exc:
            self.panel.stop(f'GUI tick failed: {exc}')
            try:self.backend.stop()
            except Exception:pass
            self.status_text.set(self.panel.message)
        finally:
            if not self.closed:self.root.after(100,self._tick)

    def _refresh_cameras(self):
        # PNG via tkinter PhotoImage; no PIL dependency or device ownership.
        if not self.camera_sources:return
        import cv2
        for name,source in self.camera_sources.items():
            frame=source.frame
            if frame is None:continue
            h,w=frame.shape[:2]
            scaled=cv2.resize(frame,(int(w*min(400/w,230/h)),int(h*min(400/w,230/h))))
            ok,png=cv2.imencode('.png',scaled)
            if not ok:continue
            photo=tk.PhotoImage(data=base64.b64encode(png).decode('ascii'),format='png')
            self.camera_images[name]=photo
            self.camera_widgets[name].configure(image=photo,text='')

    def _close(self):
        if self.closed:return
        if self.panel.moving and not messagebox.askyesno('Stop and close','Movement is active. Request software stop and close?'):
            return
        self.closed=True
        self.panel.stop('Panel closed')
        for camera in self.camera_sources.values():camera.closed=True
        try:self.backend.close()
        finally:
            self.lock.close()
            self.root.destroy()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Connect dedicated so101-control/LeRobot worker')
    parser.add_argument('--driver',choices=['vendor','studio'],default='vendor')
    parser.add_argument('--connect-studio',action='store_true',help='Explicit permission to start Studio HOLD when no session exists')
    parser.add_argument('--studio',default='http://localhost:7860')
    parser.add_argument('--project-id',default=DEFAULT_PROJECT)
    parser.add_argument('--follower-id',default=DEFAULT_FOLLOWER)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--import-recorded',type=Path,help='Import missing pose names only; never overwrite tuned poses')
    parser.add_argument('--topview-url')
    parser.add_argument('--wrist-url')
    args=parser.parse_args()
    if args.connect_studio and not args.live:parser.error('--connect-studio requires --live')
    if args.connect_studio and args.driver!='studio':parser.error('--connect-studio requires --driver studio')
    output=args.output_dir or Path('outputs/robot_panel_live' if args.live else 'outputs/robot_panel_sim')
    lock=PanelLock(Path(__file__).resolve().parents[1]/'outputs'/('robot_panel_live' if args.live else 'robot_panel_sim')/'panel.lock')
    try:
        panel=Panel(output)
        if args.import_recorded:import_recorded_poses(panel,args.import_recorded)
        if not args.live:backend=Simulation()
        elif args.driver=='vendor':backend=VendorBackend(Path(__file__).resolve().parents[1])
        else:backend=Studio(args.studio,args.project_id,args.follower_id,connect=args.connect_studio,
                            trace_path=output/'motion_trace.jsonl')
        root=tk.Tk()
        gui=TeachingGUI(root,panel,backend,output,lock,{k:v for k,v in {'topview':args.topview_url,'wrist':args.wrist_url}.items() if v})
        root.mainloop()
    except Exception:
        if 'backend' in locals():backend.close()
        lock.close()
        raise


if __name__=='__main__':main()
