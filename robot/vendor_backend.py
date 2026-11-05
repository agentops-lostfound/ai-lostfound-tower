"""Windows GUI transport to the dedicated WSL LeRobot/vendor worker."""
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from robot.joint_motion import vector

CONTAINER='physical-ai-studio-cuda'
PYTHON='/app/application/backend/.venv/bin/python'
REMOTE='/tmp/lf-teaching'
STAGE_SECONDS={1:5.0,2:4.0,3:3.0}


def deploy(repo):
    repo=Path(repo).resolve()
    source=repo/'outputs/external/so101-control/src/so101_control'
    calibration=repo/'outputs/so101_vendor_trial/calibration.json'
    if not source.is_dir() or not calibration.is_file():
        raise RuntimeError('Vendor source/calibration missing; see robot/README-panel.md')
    stage=repo/'outputs/vendor_gui_worker';stage.mkdir(parents=True,exist_ok=True)
    (stage/'robot').mkdir(exist_ok=True)
    for name in ('joint_motion.py','stage_timing.py','vendor_coordinates.py','vendor_motion.py','vendor_worker.py'):
        shutil.copy2(repo/'robot'/name,stage/'robot'/name)
    (stage/'follower.json').write_text(calibration.read_text(encoding='utf-8-sig'),encoding='utf-8')
    prefix=['wsl.exe','-d','Ubuntu-24.04','--','docker']
    def run(args):
        result=subprocess.run(prefix+args,capture_output=True,text=True,timeout=30,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError((result.stderr or result.stdout).strip())
    run(['exec',CONTAINER,PYTHON,'-c',
         "from pathlib import Path; [Path(p).mkdir(parents=True,exist_ok=True) for p in ['/tmp/lf-teaching/robot','/tmp/lf-teaching/so101_control','/tmp/lf-teaching/calibration']]"])
    def wsl_path(path):
        path=Path(path).resolve()
        return '/mnt/'+path.drive[0].lower()+path.as_posix()[2:]
    run(['cp',wsl_path(stage/'robot')+'/.',CONTAINER+':'+REMOTE+'/robot'])
    run(['cp',wsl_path(source)+'/.',CONTAINER+':'+REMOTE+'/so101_control'])
    run(['cp',wsl_path(stage/'follower.json'),CONTAINER+':'+REMOTE+'/calibration/follower.json'])
    return prefix+['exec','-i','-e','PYTHONPATH='+REMOTE,CONTAINER,PYTHON,'-m','robot.vendor_worker',
                   '--calibration',REMOTE+'/calibration/follower.json','--trace',REMOTE+'/motion.jsonl']


class VendorBackend:
    live=True
    stage_motion=True
    name='so101-control'

    def __init__(self,repo,process=None):
        self.lock=threading.RLock();self.write_lock=threading.Lock()
        self.closed=False;self.values=None;self.last=0;self.error=None;self.failure=None
        self.mode='hold';self.capable=False;self.busy=False;self.stopped=True
        self.pending=None;self.result=None;self.sequence=0
        self.repo=Path(repo);self.ready_event=threading.Event()
        if process is None:
            command=deploy(self.repo)
            logs=self.repo/'outputs/robot_panel_live';logs.mkdir(parents=True,exist_ok=True)
            self.stderr=(logs/'vendor_worker.stderr.log').open('a',encoding='utf-8')
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=self.stderr,text=True,encoding='utf-8',bufsize=1,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else:self.stderr=None
        self.process=process
        threading.Thread(target=self._read,daemon=True).start()
        threading.Thread(target=self._heartbeat,daemon=True).start()
        if not self.ready_event.wait(15) or not self.capable or not self.fresh():
            reason=self.error or 'Vendor connection timed out'
            self.close();raise RuntimeError(reason)

    def _accept(self,row):
        with self.lock:
            kind=row.get('event')
            if kind=='ready':self.capable=True
            elif kind=='status':
                vector(row['values']);self.values=row['values'];self.last=time.monotonic()
                self.busy=row['busy'];self.stopped=row['stopped'];self.error=row['error']
                if self.capable:self.ready_event.set()
            elif kind=='ack':
                if row.get('command')=='repair':self.stopped=False;self.error=None
            elif kind=='result':
                if row.get('id')==self.pending:
                    self.result=row;self.pending=None;self.busy=False
                    self.error=row.get('error')
            elif kind=='error':
                self.error=row.get('message','Vendor error');self.stopped=True
                self.pending=None;self.failure=row;self.ready_event.set()

    def _read(self):
        try:
            for line in self.process.stdout:
                self._accept(json.loads(line))
        except Exception as exc:
            if not self.closed:self.error=str(exc)
        finally:
            if not self.closed:
                self.capable=False;self.error=self.error or 'Vendor worker disconnected'
                try:self._send('stop')
                except Exception:pass
                self.ready_event.set()

    def _send(self,command,**data):
        with self.write_lock:
            self.sequence+=1
            row={'command':command,'id':self.sequence,**data}
            self.process.stdin.write(json.dumps(row)+'\n');self.process.stdin.flush()
            return row['id']

    def _heartbeat(self):
        while not self.closed:
            if self.error and not self.capable:return
            try:self._send('ping')
            except Exception:return
            time.sleep(0.25)

    def snapshot(self):
        with self.lock:return dict(self.values) if self.values is not None else None

    def fresh(self):return time.monotonic()-self.last<0.75

    def ready(self):
        with self.lock:
            return self.capable and self.fresh() and not self.error and not self.stopped and not self.busy and self.pending is None

    def start_stage(self,target,expected,level):
        vector(target);vector(expected)
        with self.lock:
            if not self.ready():raise RuntimeError(self.error or 'Vendor not ready; Repair first')
            self.result=None;self.busy=True
            self.pending=self._send('move',target=target,expected=expected,
                                    duration=STAGE_SECONDS[level],approved=True)

    def stop(self):self._send('stop')
    def repair(self):
        if not self.capable or not self.fresh() or self.busy:
            raise RuntimeError('Fresh idle vendor connection required')
        self._send('repair')

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            self._send('shutdown');self.process.stdin.close()
            self.process.wait(timeout=8)
        except Exception:
            # Closing stdin requests worker stop/hold; never start a second owner here.
            try:self.process.stdin.close()
            except Exception:pass
        if self.stderr:self.stderr.close()
