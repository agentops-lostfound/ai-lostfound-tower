"""Read-only, latest-sample telemetry, independent of executor control locks."""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import subprocess
import threading
import time
import uuid

from robot.joint_motion import JOINTS
from robot.vendor_coordinates import VendorCoordinates


def load_coordinates(path, follower):
    """An explicit snapshot of this follower's existing calibration, never a driver."""
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('Invalid joint calibration snapshot')
    if data.get('follower_id') != follower:
        raise ValueError('Joint calibration belongs to a different follower')
    calibration = data['calibration']
    for name in JOINTS:
        row = calibration[name]
        if any(type(row[key]) is not int for key in ('drive_mode', 'range_min', 'range_max')):
            raise ValueError('Joint calibration must contain integer ranges and drive modes')
        if not 0 <= row['range_min'] < row['range_max'] <= 4095:
            raise ValueError('Invalid joint calibration range')
    return VendorCoordinates(calibration)


def received_observation(row, roundtrip, now):
    """Bound sample age without comparing Windows and WSL wall clocks.

    One outstanding observer-only sample request makes roundtrip an upper
    bound on IPC delay, including any stdout backlog. No runtime command.
    """
    if not isinstance(row, dict):
        raise ValueError('Invalid observation response')
    if row.get('available') is not True:
        return {'available': False}
    age = row['sample_age_seconds']
    if type(age) not in (int, float) or not math.isfinite(age) or age < 0:
        raise ValueError('Invalid observation age')
    return {**row, 'read_at': (now - timedelta(seconds=age + roundtrip)).isoformat()}


class JointTelemetry:
    def __init__(self, *, coordinates=None, max_age=1., clock=time.monotonic,
                 utcnow=lambda: datetime.now(timezone.utc)):
        self.coordinates, self.max_age = coordinates, max_age
        self.clock, self.utcnow = clock, utcnow
        self.lock = threading.Lock()  # Never the executor/lease/motion lock.
        self.sample = None
        self.reason = 'Studio observation not received'

    def unavailable(self, reason='Studio observation unavailable'):
        with self.lock:
            self.sample, self.reason = None, reason

    def accept(self, row):
        """Only follower data; action targets and leader positions are never used."""
        try:
            if not isinstance(row, dict):
                raise ValueError('Invalid observation response')
            if row.get('available') is not True:
                self.unavailable()
                return
            data = row['positions']
            positions = {name + '.pos': data[name + '.pos'] for name in JOINTS}
            # Observation values must be finite. Do not clamp measured data.
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in positions.values()):
                raise ValueError('Invalid observation')
            read_at = datetime.fromisoformat(row['read_at'])
            if read_at.tzinfo is None:
                raise ValueError('Observation time must include a timezone')
            age = (self.utcnow() - read_at).total_seconds()
            if not 0 <= age <= self.max_age:
                raise ValueError('Stale observation')
            degrees = None
            if self.coordinates is not None:
                # VendorCoordinates validates normalized range as well.
                try:
                    degrees = self.coordinates.degrees(positions)
                except ValueError:
                    pass  # Keep real observations even outside calibrated travel.
            with self.lock:
                self.sample = (positions, degrees, read_at.isoformat(), self.clock() - age)
        except (KeyError, TypeError, ValueError, OverflowError):
            self.unavailable('Invalid or stale Studio observation')

    def snapshot(self, instance):
        with self.lock:
            sample, reason = self.sample, self.reason
        if sample is None:
            return {'available': False, 'instance': instance, 'reason': reason}
        positions, degrees, read_at, observed = sample
        if self.clock() - observed > self.max_age:
            return {'available': False, 'instance': instance, 'reason': 'Studio observation is stale'}
        return {'available': True, 'instance': instance, 'unit': 'normalized',
                'positions': dict(positions), 'degrees': None if degrees is None else dict(degrees),
                'read_at': read_at, 'source': 'studio_observation'}


class StudioJointReader:
    """One subscriber process per server; requests only read JointTelemetry."""
    def __init__(self, telemetry, follower, container='physical-ai-studio-cuda',
                 distribution='Ubuntu-24.04', *, popen=subprocess.Popen):
        self.telemetry, self.follower = telemetry, str(uuid.UUID(follower))
        self.container, self.distribution, self.popen = container, distribution, popen
        self.done = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        code = Path(__file__).with_name('studio_joint_worker.py').read_text(encoding='utf-8')
        while not self.done.is_set():
            process = None
            try:
                with self.process_lock:
                    if self.done.is_set():
                        return
                    process = self.popen([
                        'wsl.exe', '-d', self.distribution, '--', 'docker', 'exec', '-i',
                        '-e', 'PYTHONPATH=/app/application/backend/src', self.container,
                        '/app/application/backend/.venv/bin/python', '-u', '-c', code, self.follower,
                    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.process = process
                sent_at = time.monotonic()
                process.stdin.write('sample\n')
                process.stdin.flush()
                for line in process.stdout:
                    if self.done.is_set():
                        break
                    row = received_observation(json.loads(line), time.monotonic() - sent_at,
                                               datetime.now(timezone.utc))
                    self.telemetry.accept(row)
                    sent_at = time.monotonic()
                    process.stdin.write('sample\n')
                    process.stdin.flush()
            except (OSError, KeyError, TypeError, ValueError, OverflowError):
                pass
            finally:
                self.telemetry.unavailable('Studio observation reader disconnected')
                if process is not None:
                    self._detach(process)
                with self.process_lock:
                    self.process = None
            self.done.wait(2.)

    @staticmethod
    def _detach(process):
        # EOF means detach this observer only. No stop/hold command, no runtime kill.
        try:
            process.stdin.close()
            process.wait(timeout=3.)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def close(self):
        self.done.set()
        with self.process_lock:
            process = self.process
        if process is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if self.thread is not None:
            self.thread.join(timeout=4.)
        self.telemetry.unavailable('Studio observation reader closed')
