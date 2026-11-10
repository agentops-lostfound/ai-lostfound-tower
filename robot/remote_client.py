"""Tower-PC client; standard library only, no WSL/Studio/serial dependencies."""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from urllib.parse import urlsplit
import urllib.request
import uuid


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a robot credential to another address.


class RemoteTowerRobot:
    def __init__(self, *, url=None, token=None, expected_mode=None, opener=None, sleep=time.sleep):
        self.url = (url if url is not None else os.environ.get('TOWER_REMOTE_ROBOT_URL', '')).rstrip('/')
        self.token = token if token is not None else os.environ.get('TOWER_REMOTE_ROBOT_TOKEN', '')
        self.error = ''
        self.expected_mode = expected_mode or os.environ.get('TOWER_REMOTE_ROBOT_MODE') or 'live'
        parsed = urlsplit(self.url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or len(self.token) < 32
                or not self.token.isascii() or any(c.isspace() for c in self.token)
                or self.expected_mode not in ('live', 'simulation')):
            self.error = 'Remote URL/token configuration required'
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.sleep = sleep
        self.operation = threading.Lock()
        self.lock = threading.RLock()
        self.active = None
        self.stop_requested = threading.Event()
        self.faulted = False
        self.fault_instance = None
        self.stop_generation = 0

    def request(self, path, body=None, *, timeout=2):
        if self.error:
            raise ValueError(self.error)
        req = urllib.request.Request(self.url + path, headers={
            'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
            data=None if body is None else json.dumps(body).encode())
        with self.opener.open(req, timeout=timeout) as response:
            data = response.read(65537)
            if len(data) > 65536:
                raise ValueError('Oversized executor response')
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError('Invalid executor response')
            return result

    def health(self):
        return self.request('/v1/health')

    def arm_local(self):
        with self.lock:
            generation = self.stop_generation
        state = self.health()
        result = self.request('/v1/arm', {'instance': state['instance'], 'approved': True}, timeout=15)
        with self.lock:
            if generation == self.stop_generation:
                self.faulted = False
                self.stop_requested.clear()
        return result

    def _call(self, operation, arguments, progress=None):
        if not self.operation.acquire(blocking=False):
            return {'ok': False, 'reason': 'Another remote operation is running'}
        submitted = False
        try:
            with self.lock:
                generation = self.stop_generation
            state = self.health()
            with self.lock:
                if generation != self.stop_generation:
                    return {'ok': False, 'reason': 'Stopped during remote preparation'}
                if self.faulted or self.stop_requested.is_set():
                    if (not state.get('armed') or self.fault_instance is None
                            or state.get('instance') == self.fault_instance):
                        return {'ok': False, 'reason': 'Previous remote failure requires local inspection/rearming'}
                    self.faulted = False  # Only a new local arming epoch may clear an old stop.
                    self.stop_requested.clear()
            if state.get('mode') != self.expected_mode:
                return {'ok': False, 'reason': 'Executor mode differs from configured live/simulation mode'}
            if not state.get('armed'):
                return {'ok': False, 'reason': 'Robot PC must be armed by its local operator'}
            instance, job_id = state['instance'], str(uuid.uuid4())
            with self.lock:
                if self.stop_requested.is_set():
                    return {'ok': False, 'reason': 'Cancelled before remote submission'}
                self.active = (instance, job_id)
            submitted = True  # Delivery may precede an HTTP response failure.
            job = self.request('/v1/jobs', {'instance': instance, 'job_id': job_id,
                'operation': operation, 'arguments': arguments, 'approved': True})
            delivered = 0
            while True:
                if self.stop_requested.is_set():
                    raise InterruptedError('Remote stop requested')
                if job.get('job_id') != job_id:
                    raise ValueError('Executor returned another job')
                if progress is not None:
                    events = job.get('events')
                    if not isinstance(events, list) or not delivered <= len(events) <= 22:
                        raise ValueError('Invalid sequence event history')
                    for event in events[delivered:]:
                        progress(event)
                        delivered += 1
                if job.get('status') in ('completed', 'failed', 'cancelled'):
                    result = job.get('result')
                    if not isinstance(result, dict) or type(result.get('ok')) is not bool:
                        raise ValueError('Missing robot result')
                    if job['status'] != 'completed' or not result['ok']:
                        return {**result, 'ok': False, 'reason': str(result.get('reason') or 'Remote job interrupted')[:240],
                                'job_id': job_id, 'stop_confirmed': job.get('stop_confirmed')}
                    return {**result, 'job_id': job_id, 'remote_mode': state['mode']}
                # This is a control lease, not an arrival timeout. Never
                # resubmit a command with a fresh ID after uncertain delivery.
                self.sleep(.25)
                self.request(f'/v1/jobs/{job_id}/heartbeat', {'instance': instance})
                job = self.request(f'/v1/jobs/{job_id}')
        except (Exception, KeyboardInterrupt) as exc:
            self.faulted = True
            self.fault_instance = self.active[0] if self.active else locals().get('state', {}).get('instance')
            stopped = self.robot_stop() if submitted else {'ok': False}
            return {'ok': False, 'reason': f'Remote operation failed: {type(exc).__name__}; '
                    + ('stop state confirmed' if stopped['ok'] else 'stop unconfirmed; inspect robot locally'),
                    'stop_confirmed': stopped['ok']}
        finally:
            with self.lock:
                self.active = None
            self.operation.release()

    def robot_go_pose(self, pose_name, slot_id):
        return self._call('go_pose', {'pose_name': pose_name, 'slot_id': slot_id})

    def run_pose_sequence_test(self, target):
        return self._call('sequence', {'target': target})

    def robot_run_sequence(self, target, progress=None):
        return self._call('taught_sequence', {'target': target}, progress=progress)

    def robot_approach(self, center_mm, center_px):
        return {'ok': False, 'reason': 'Remote executor requires DB slot/pose mode'}

    def robot_grasp(self):
        return self._call('grasp', {})

    def robot_verify_grasp(self):
        return self._call('verify_grasp', {})

    def robot_deliver(self):
        return self._call('deliver', {})

    def robot_home(self):
        return self._call('home', {})

    def robot_state(self):
        # CompositeBackend must not fall back to simulated joint values for
        # a real remote robot. The public state contract uses degrees while
        # Studio reports calibrated normalized units; conversion is pending.
        raise NotImplementedError('Remote joint state in contract units is unavailable; use job health/status')

    def robot_stop(self):
        with self.lock:
            self.stop_requested.set()
            self.stop_generation += 1
            generation = self.stop_generation
            self.faulted = True
            self.fault_instance = None
        try:
            with self.lock:
                active = self.active
            state = self.health()
            with self.lock:
                if generation == self.stop_generation:
                    self.fault_instance = state['instance']
            if active and active[0] != state['instance']:
                return {'ok': False, 'reason': 'Executor restarted; old stop not confirmed'}
            result = self.request('/v1/stop', {'instance': state['instance'],
                                             'job_id': active[1] if active else None})
            return {'ok': result.get('ok') is True, 'reason': str(result.get('reason') or '')[:240]}
        except Exception:
            return {'ok': False, 'reason': 'Remote stop unconfirmed; inspect robot locally'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('status', 'arm', 'stop', 'sequence'))
    parser.add_argument('--tower', help='Tower base URL for read-only DB target lookup')
    parser.add_argument('--item-id')
    parser.add_argument('--approved', action='store_true', help='Operator explicitly authorizes the physical route')
    args = parser.parse_args()
    client = RemoteTowerRobot()
    if args.operation == 'status':
        result = client.health()
    elif args.operation == 'arm':
        if not args.approved:
            parser.error('Local operator approval required: --approved')
        result = client.arm_local()
    elif args.operation == 'stop':
        result = client.robot_stop()
    else:
        if not args.approved or not args.tower or not args.item_id:
            parser.error('Sequence needs --tower, --item-id and --approved; DB lookup alone is not approval')
        from urllib.parse import quote
        req = urllib.request.Request(args.tower.rstrip('/') + '/api/admin/storage/robot-target/'
                                     + quote(args.item_id, safe=''))
        with urllib.request.urlopen(req, timeout=5) as response:
            target = json.load(response)
        if target.get('item_id') != args.item_id:
            parser.error('Tower returned another item')
        result = client.run_pose_sequence_test(target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get('ok') is False else 0


if __name__ == '__main__':
    raise SystemExit(main())
