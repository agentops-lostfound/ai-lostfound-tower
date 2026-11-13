"""Authenticated LAN job executor on the Studio PC. Simulation is the default.

Live mode starts disarmed. Only a loopback operator can arm it. Never opens a
serial port, starts Studio, changes DB records, or resumes work after restart.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import threading
import time
import uuid


METHODS = {'go_pose': 'robot_go_pose', 'sequence': 'run_pose_sequence_test',
           'taught_sequence': 'robot_run_sequence',
           'grasp': 'robot_grasp', 'verify_grasp': 'robot_verify_grasp',
           'deliver': 'robot_deliver', 'home': 'robot_home'}
TERMINAL = {'completed', 'failed', 'cancelled'}


def validate_job(operation, arguments):
    if operation not in METHODS or not isinstance(arguments, dict):
        raise ValueError('Unsupported operation')
    if operation == 'go_pose':
        from agents.storage import SLOT_NUMBERS
        slot = arguments.get('slot_id')
        n = SLOT_NUMBERS.get(slot) if isinstance(slot, str) else None
        if set(arguments) != {'slot_id', 'pose_name'} or n is None or arguments['pose_name'] != f'pose_{n}':
            raise ValueError('DB slot and pose do not match')
    elif operation in ('sequence', 'taught_sequence'):
        from robot.db_pose_sequence import sequence_for_target
        if set(arguments) != {'target'}:
            raise ValueError('A DB target is required')
        sequence_for_target(arguments['target'])
    elif operation == 'home':
        if arguments and (set(arguments) != {'empty_gripper_confirmed'} or arguments['empty_gripper_confirmed'] is not True):
            raise ValueError('Explicit empty-gripper recovery confirmation required')
    elif arguments:
        raise ValueError('This operation takes no arguments')


class Executor:
    def __init__(self, factory, *, live=False, readiness=None, lease_seconds=5., clock=time.monotonic,
                 allowed_slots=(), joint_telemetry=None):
        from robot.joint_telemetry import JointTelemetry
        self.joint_telemetry = joint_telemetry if joint_telemetry is not None else JointTelemetry()
        self.factory, self.live, self.readiness = factory, live, readiness
        self.clock, self.lease = clock, lease_seconds
        self.instance = str(uuid.uuid4())
        self.lock = threading.RLock()
        self.backend = None
        self.armed = False
        self.uncertain_stop = False
        self.jobs = {}
        self.cancelled_ids = set()
        self.active = None
        self.closed = threading.Event()
        self.allowed_slots = frozenset(allowed_slots)
        from agents.storage import SLOT_NUMBERS
        from robot.db_pose_sequence import sequence_for_target
        # Snapshot the runner's plan at startup so old/new peers can compare
        # before a job is submitted, rather than discovering it after a pick.
        self.sequence_plans = {slot: sequence_for_target({
            'ok': True, 'slot_id': slot, 'number': number, 'pose_name': f'pose_{number}'})
            for slot, number in SLOT_NUMBERS.items()}

    def health(self):
        with self.lock:
            return {'instance': self.instance, 'mode': 'live' if self.live else 'simulation',
                    'armed': self.armed, 'active_job': self.active,
                    'home_recovery': True,
                    'stop_uncertain': self.uncertain_stop,
                    'sequence_slots': sorted(self.allowed_slots) if self.live else 'simulation',
                    'sequence_plans': {slot: list(plan) for slot, plan in self.sequence_plans.items()}}

    def arm(self):
        with self.lock:
            if self.active is not None or self.uncertain_stop:
                raise ValueError('Active job or unconfirmed stop; inspect locally first')
            if self.armed:
                return
            # Readiness is attach-only, never movement. Constructor also must
            # be side-effect free (the existing TowerRobot satisfies this).
            if self.readiness:
                self.readiness()
            backend = self.factory()
            if getattr(backend, 'error', ''):
                raise ValueError('Robot pose/configuration check failed')
            self.backend, self.armed = backend, True
            self.instance = str(uuid.uuid4())  # Fence delayed requests from an earlier arming.

    def submit(self, instance, job_id, operation, arguments, approved):
        job_id = str(uuid.UUID(job_id))
        validate_job(operation, arguments)
        if (self.live and operation == 'taught_sequence'
                and arguments['target']['slot_id'] not in self.allowed_slots):
            raise ValueError('This slot has not been enabled by the local operator')
        fingerprint = hashlib.sha256(json.dumps([operation, arguments], sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()
        with self.lock:
            if instance != self.instance:
                raise ValueError('Executor restarted; old requests cannot be replayed')
            if approved is not True:
                raise ValueError('Explicit movement approval required')
            if job_id in self.cancelled_ids:
                raise ValueError('Job cancelled before its submission was observed')
            old = self.jobs.get(job_id)
            if old:
                if old['fingerprint'] != fingerprint:
                    raise ValueError('Job ID reused for different work')
                return self.status(job_id)
            recovery = operation == 'home'
            if ((not self.armed and not recovery) or self.active is not None or self.closed.is_set()
                    or (recovery and self.uncertain_stop)):
                raise ValueError('Executor disarmed or busy')
            if len(self.jobs) + len(self.cancelled_ids) >= 1024:
                raise ValueError('Job history full; inspect and restart locally')
            if recovery:
                # HOME is explicitly requested through the staff-confirmed recovery path.
                # It does not arm pickup operations or revive the cancelled backend.
                backend = self.factory()
                if getattr(backend, 'error', ''):
                    raise ValueError('Robot pose/configuration check failed')
                self.backend = backend  # Preserve an existing local arm; HOME never grants a new one.
            job = {'job_id': job_id, 'fingerprint': fingerprint, 'operation': operation,
                   'arguments': json.loads(json.dumps(arguments)), 'status': 'pending',
                   'result': None, 'stop_confirmed': None, 'heartbeat': self.clock(),
                   'cancelled': threading.Event(), 'thread': None, 'stop_lock': threading.Lock(),
                   'events': []}
            self.jobs[job_id] = job
            self.active = job_id
            job['thread'] = threading.Thread(target=self._run, args=(job,), daemon=True)
            job['thread'].start()
            return self.status(job_id)

    def status(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            return {**{key: job[key] for key in ('job_id', 'operation', 'status', 'result', 'stop_confirmed')},
                    'events': [dict(event) for event in job['events']]}

    def heartbeat(self, instance, job_id):
        with self.lock:
            if instance != self.instance:
                raise ValueError('Executor instance changed')
            job = self.jobs[job_id]
            if job['status'] not in TERMINAL and not job['cancelled'].is_set():
                job['heartbeat'] = self.clock()
            return self.status(job_id)

    def _run(self, job):
        try:
            with self.lock:
                if job['cancelled'].is_set():
                    raise InterruptedError('Cancelled before execution')
                job['status'] = 'running'
                backend = self.backend
            method = getattr(backend, METHODS[job['operation']])
            def progress(event):
                with self.lock:
                    if job['cancelled'].is_set():
                        raise InterruptedError('Cancelled during sequence')
                    if len(job['events']) >= 22:
                        raise ValueError('Too many sequence events')
                    job['events'].append(dict(event))
            result = (method(**job['arguments'], progress=progress)
                      if job['operation'] == 'taught_sequence' else method(**job['arguments']))
            if not isinstance(result, dict) or type(result.get('ok')) is not bool:
                raise ValueError('Invalid robot result')
        except Exception as exc:
            result = {'ok': False, 'reason': f'Executor job failed: {type(exc).__name__}'}
        if not result['ok'] and not job['cancelled'].is_set():
            self.stop(job['job_id'])
        with self.lock:
            job['result'] = result
            job['status'] = ('cancelled' if job['cancelled'].is_set() else
                             'completed' if result['ok'] else 'failed')
            # Do not free the executor until any concurrent stop finishes.
            if not job['stop_lock'].locked():
                self.active = None

    def stop(self, job_id=None):
        with self.lock:
            active = self.active
            if job_id is not None and job_id != active:
                if job_id in self.jobs and self.jobs[job_id]['status'] in TERMINAL:
                    old = self.jobs[job_id]
                    confirmed = old['stop_confirmed'] is True or (
                        old['status'] == 'completed' and old['result'].get('ok') is True)
                    return {'ok': confirmed, 'reason': '' if confirmed else 'Previous stop unconfirmed',
                            'already_terminal': True}
                if len(self.cancelled_ids) + len(self.jobs) >= 1024:
                    self.armed = False
                    return {'ok': False, 'reason': 'Cancellation history full; inspect locally'}
                self.cancelled_ids.add(job_id)  # Stop can precede registration of a slow POST.
                if active is None:
                    self.armed = False
                    if self.uncertain_stop:
                        return {'ok': False, 'reason': 'Previous robot stop remains unconfirmed'}
                return {'ok': True, 'reason': '', 'cancelled_before_submission': True}
            self.armed = False
            if active is None:
                if self.uncertain_stop:
                    return {'ok': False, 'reason': 'Previous robot stop remains unconfirmed'}
                return {'ok': True, 'reason': '', 'no_owned_job': True}
            job = self.jobs[active]
            job['cancelled'].set()
            cancelled = getattr(self.backend, 'cancelled', None)
            if cancelled is not None:
                cancelled.set()  # Covers cancellation just before method entry.
            if not job['stop_lock'].acquire(blocking=False):
                return {'ok': False, 'reason': 'Stop already pending'}
            job['status'] = 'stopping'
        try:
            confirmed = False
            response = self.backend.robot_stop()
            confirmed = isinstance(response, dict) and response.get('ok') is True
        except Exception:
            confirmed = False
        finally:
            with self.lock:
                job['stop_confirmed'] = confirmed
                self.uncertain_stop |= not confirmed
                job['stop_lock'].release()
                if job['result'] is not None:
                    job['status'] = 'cancelled'
                    self.active = None
        return {'ok': confirmed, 'reason': '' if confirmed else 'Studio stop not confirmed; inspect robot locally'}

    def expire(self):
        with self.lock:
            job = self.jobs.get(self.active)
            expired = (job is not None and not job['cancelled'].is_set()
                       and self.clock() - job['heartbeat'] > self.lease)
            job_id = job['job_id'] if expired else None
        if job_id:
            self.stop(job_id)

    def monitor(self):
        while not self.closed.wait(.1):
            self.expire()

    def close(self):
        self.closed.set()
        self.stop()


def make_server(executor, token, *, host='127.0.0.1', port=8767, allow_clients=()):
    if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError('Use a random ASCII authentication token of at least 32 characters')
    allowed = {str(ipaddress.ip_address(ip)) for ip in allow_clients}
    allowed.update(('127.0.0.1', '::1'))

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def log_message(self, *args):
            pass  # Never log Authorization headers or request bodies.

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            expected = 'Bearer ' + token
            supplied = self.headers.get('Authorization', '')
            return (self.client_address[0] in allowed and not self.headers.get('Origin')
                    and supplied.isascii() and hmac.compare_digest(supplied, expected))

        def do_GET(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Forbidden'})
            try:
                if self.path == '/v1/health':
                    return self.reply(200, executor.health())
                if self.path == '/v1/joints':
                    return self.reply(200, executor.joint_telemetry.snapshot(executor.instance))
                prefix = '/v1/jobs/'
                if self.path.startswith(prefix):
                    job_id = str(uuid.UUID(self.path[len(prefix):]))
                    return self.reply(200, executor.status(job_id))
                return self.reply(404, {'error': 'Not found'})
            except (KeyError, ValueError):
                return self.reply(404, {'error': 'Unknown job'})

        def do_POST(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Forbidden'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or body.get('instance') != executor.instance:
                    raise ValueError('Invalid body or executor instance')
                if self.path == '/v1/arm':
                    if not ipaddress.ip_address(self.client_address[0]).is_loopback or body.get('approved') is not True:
                        return self.reply(403, {'error': 'Local operator arming required'})
                    executor.arm()
                    return self.reply(200, executor.health())
                if self.path == '/v1/stop':
                    job_id = str(uuid.UUID(body['job_id'])) if body.get('job_id') is not None else None
                    return self.reply(200, executor.stop(job_id))
                if self.path == '/v1/jobs':
                    result = executor.submit(body['instance'], body['job_id'], body['operation'],
                                             body.get('arguments'), body.get('approved'))
                    return self.reply(200, result)
                prefix, suffix = '/v1/jobs/', '/heartbeat'
                if self.path.startswith(prefix) and self.path.endswith(suffix):
                    job_id = str(uuid.UUID(self.path[len(prefix):-len(suffix)]))
                    return self.reply(200, executor.heartbeat(body['instance'], job_id))
                return self.reply(404, {'error': 'Not found'})
            except (KeyError, TypeError, ValueError):
                return self.reply(409, {'error': 'Job rejected; check instance, approval, slot, arming and busy state'})
            except Exception:
                return self.reply(500, {'error': 'Executor failed; inspect locally'})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def live_readiness(follower, container, distribution):
    import socket
    from robot.studio_pose_transport import StudioPoseTransport
    # The standalone panel must be closed before assigning remote ownership.
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8766)) == 0:
            raise ValueError('Close the standalone sequence panel before arming remote control')
    transport = StudioPoseTransport(follower, container, distribution)
    pipe = transport._open()
    try:
        transport._ready(pipe, 'home')
    finally:
        pipe.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--allow-client', action='append', default=[])
    parser.add_argument('--allow-slot', action='append', default=[],
                        help='Locally verified slot allowed for tower-triggered sequences, e.g. R1-1')
    parser.add_argument('--tls-cert', type=Path)
    parser.add_argument('--tls-key', type=Path)
    parser.add_argument('--poses', type=Path, default=Path(__file__).resolve().parents[1] / 'outputs/robot_panel_live/poses.json')
    parser.add_argument('--joint-calibration', type=Path,
                        help='Read-only follower_id/calibration JSON snapshot for telemetry degrees')
    args = parser.parse_args()
    if not ipaddress.ip_address(args.host).is_loopback and not args.allow_client:
        parser.error('LAN binding requires --allow-client with the tower IP')
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error('TLS needs both --tls-cert and --tls-key')
    from robot.tower_part import TowerRobot
    if args.live:
        follower = str(uuid.UUID(os.environ.get('TOWER_STUDIO_FOLLOWER_ID', '')))
        container = os.environ.get('TOWER_STUDIO_CONTAINER') or 'physical-ai-studio-cuda'
        distribution = os.environ.get('TOWER_STUDIO_DISTRIBUTION') or 'Ubuntu-24.04'
        readiness = lambda: live_readiness(follower, container, distribution)
        factory = lambda: TowerRobot(poses_path=args.poses)
    else:
        from robot.db_pose_sequence import SimulatedPoseMotion
        poses = json.loads(args.poses.read_text(encoding='utf-8-sig'))
        factory = lambda: TowerRobot(motion=SimulatedPoseMotion(poses), poses_path=args.poses, environ={})
        readiness = None
    from agents.storage import SLOT_NUMBERS
    if any(slot not in SLOT_NUMBERS for slot in args.allow_slot):
        parser.error('--allow-slot must name a robot storage slot R1-1 through R4-2')
    from robot.joint_telemetry import JointTelemetry, StudioJointReader, load_coordinates
    coordinates = None
    if args.live and args.joint_calibration:
        try:
            coordinates = load_coordinates(args.joint_calibration, follower)
        except (OSError, KeyError, TypeError, ValueError):
            print('Joint calibration unavailable; telemetry degrees will be null', flush=True)
    telemetry = JointTelemetry(coordinates=coordinates)
    executor = Executor(factory, live=args.live, readiness=readiness, allowed_slots=args.allow_slot,
                        joint_telemetry=telemetry)
    server = make_server(executor, os.environ.get('TOWER_REMOTE_ROBOT_TOKEN', ''),
                         host=args.host, port=args.port, allow_clients=args.allow_client)
    if args.tls_cert:
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=executor.monitor, daemon=True).start()
    reader = StudioJointReader(telemetry, follower, container, distribution) if args.live else None
    if reader is not None:
        reader.start()
    print(f"{'LIVE' if args.live else 'SIMULATION'} remote executor on {args.host}:{server.server_port}; DISARMED", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if reader is not None:
            reader.close()
        executor.close()
        server.server_close()


if __name__ == '__main__':
    main()
