"""State machine for a keyboard panel. No hardware imports."""
import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from robot.joint_motion import JOINTS,vector

KEYS=[n+'.pos' for n in JOINTS]
SPEEDS={1:0.05,2:0.10,3:0.25}  # normalized units per command, at most 8Hz


class Panel:
    def __init__(self,directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.pose_file=self.directory/'poses.json'
        self.poses=json.loads(self.pose_file.read_text(encoding='utf-8')) if self.pose_file.exists() else {}
        for values in self.poses.values():vector(values)
        self.current=None;self.target=None;self.speed=1;self.selected=0
        self.commanded=None
        self.wait_since=None
        self.stopped=True;self.armed=False;self.moving=False;self.confirm_pending=False
        self.message='STOPPED. Repair (R) after checking the arm.'
        self.sequence=['home','raised','entry','observe'];self.sequence_index=0

    def observe(self,values):
        vector(values);self.current=dict(values)
        if self.target is None:self.target=dict(values)

    def stop(self,reason='Operator stop'):
        self.stopped=True;self.armed=False;self.moving=False;self.confirm_pending=False
        if self.current is not None:self.target=dict(self.current)
        self.message=reason

    def repair(self):
        if self.current is None:raise ValueError('Fresh observations required')
        self.stopped=False;self.armed=False;self.moving=False;self.confirm_pending=False
        self.target=dict(self.current);self.message='Repaired; target reset. Review and Enter twice to move.'
        self.commanded=dict(self.current)
        self.wait_since=None

    def edit(self,index,value):
        if self.moving:raise ValueError('Stop before editing')
        if self.current is None:raise ValueError('No observation')
        candidate=dict(self.target);candidate[KEYS[index]]=float(value);vector(candidate)
        if index==5:raise ValueError('Gripper motion locked in this version')
        self.target=candidate;self.armed=False;self.confirm_pending=False

    def save(self,name):
        if self.current is None:raise ValueError('No observation')
        if not name or len(name)>40 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):
            raise ValueError('Pose name: letters, digits, underscore or hyphen; max 40')
        self.poses[name]=dict(self.current)
        temp=self.pose_file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.poses,indent=2),encoding='utf-8');temp.replace(self.pose_file)
        self.message='Saved current measured pose: '+name

    def load(self,name):
        if self.moving:raise ValueError('Stop before choosing a pose')
        if self.current is None:raise ValueError('No observation')
        values=dict(self.poses[name]);vector(values)
        values[KEYS[5]]=self.current[KEYS[5]]
        self.target=values;self.armed=False;self.confirm_pending=False
        self.message='Preview '+name+'; Enter twice for this stage only'

    def confirm(self):
        if self.stopped or self.current is None:raise ValueError('Repair first')
        if self.moving:return
        if not self.confirm_pending:
            self.confirm_pending=True;self.message='Confirm target and clear path; Enter again starts this stage'
        else:
            self.armed=True;self.moving=True;self.confirm_pending=False;self.message='Moving one stage'
            self.commanded=dict(self.current)
            self.wait_since=None

    def _wait_for_tracking(self, reason):
        now=time.monotonic()
        if self.wait_since is None:self.wait_since=now
        self.message=reason
        if now-self.wait_since>1.5:self.stop(reason+'; no further commands (1.5s)')

    def next_step(self):
        if not self.moving or self.stopped or not self.armed:return None
        a=vector(self.commanded or self.current);b=vector(self.target)
        measured=vector(self.current)
        if abs(measured[5]-b[5])>0.5:self.stop('Gripper changed externally');return None
        error=max(abs(x-y) for x,y in zip(a,b))
        if error<=0.025:
            if max(abs(x-y) for x,y in zip(measured[:5],b[:5]))<=0.15:
                self.moving=False;self.armed=False;self.message='Target reached within 0.15 normalized. Confirm next stage.'
                self.wait_since=None
            else:self._wait_for_tracking('Final target not reached')
            return None
        step=SPEEDS[self.speed]
        # Interpolate along the joint-space line, preserve proportions.
        ratio=min(1,step/error)
        point=[x+(y-x)*ratio for x,y in zip(a,b)]
        # Stay inside the existing server's 0.5 following bound, with margin.
        # Never accumulate an unbounded queue against a stalled arm.
        if max(abs(x-y) for x,y in zip(point[:5],measured[:5]))>0.45:
            self._wait_for_tracking('Waiting for measured arm before next step')
            return None
        self.wait_since=None
        return dict(zip(KEYS,point))

    def export_csv(self):
        if self.current is None:raise ValueError('No observation')
        path=self.directory/'observations.csv';exists=path.exists() and path.stat().st_size>0
        with path.open('a',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream)
            if not exists:writer.writerow(['timestamp_utc','unit','speed_level',*KEYS])
            writer.writerow([datetime.now(timezone.utc).isoformat(),'studio_normalized',self.speed,*vector(self.current)])
        self.message='CSV appended: '+str(path)
        return path


def import_recorded_poses(panel,root):
    """Explicitly import historical snapshots; never mark routes collision checked."""
    for name in panel.sequence:
        if name in panel.poses:continue  # Preserve the operator's customized saved pose.
        matches=sorted(Path(root).glob('*_'+name+'/pose.json'))
        if not matches:continue
        row=json.loads(matches[-1].read_text(encoding='utf-8'))
        if row.get('unit')!='studio_normalized':raise ValueError('Unexpected pose unit')
        values=row['samples'][-1]['joints'];vector(values);panel.poses[name]=values
    panel.pose_file.write_text(json.dumps(panel.poses,indent=2),encoding='utf-8')
