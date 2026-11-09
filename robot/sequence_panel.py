"""Browser sequence experiment panel. Simulation default; --live never auto-moves."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time

from robot.sequence_experiment import SequenceExperiment
from robot.studio_pose_transport import RuntimePipe, StudioPoseTransport


class Telemetry:
    def __init__(self, model, follower, container, distribution):
        self.model, self.follower = model, follower
        self.args = (follower, container, distribution)
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.thread = None

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.closed.clear()
            self.thread = threading.Thread(target=self._receive, daemon=True)
            self.thread.start()

    def _receive(self):
        pipe = None
        try:
            pipe = RuntimePipe(*self.args)
            deadline = time.monotonic() + 10
            ready = False
            while not self.closed.is_set():
                row = pipe.receive()
                if row:
                    if row.get('event') == 'error':
                        raise RuntimeError(row.get('message', 'Studio 수신 연결 오류'))
                    self.model.observe(row)
                    snapshot = self.model.snapshot()
                    state = snapshot['runtime_state']
                    if state.get('connected') and snapshot['packet_age'] is not None:
                        if state.get('saved_pose_robot_id') != self.follower:
                            raise ValueError('Studio 자세 파일의 팔로워 ID가 다릅니다')
                        ready = True
                        self.model.set_connected(True, 'Studio 수신 연결됨 · 실행 전 경로를 확인하세요')
                if not ready and time.monotonic() > deadline:
                    raise RuntimeError('Studio 상태·관절값을 받지 못했습니다. 기존 세션을 확인하세요')
        except Exception as exc:
            if not self.closed.is_set():
                self.model.set_connected(False, str(exc)[:240])
                if self.model.running:
                    self.model.request_stop('Studio 수신 연결 중단')
        finally:
            if pipe:
                pipe.close()  # Read-only worker has no owned movement to cancel.

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(2)


def make_server(model, telemetry=None, port=8766):
    token = secrets.token_urlsafe(32)
    page = Path(__file__).with_suffix('.html').read_text(encoding='utf-8').replace('__CONTROL_TOKEN__', token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, status, value, content_type='application/json; charset=utf-8'):
            data = value.encode('utf-8') if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def _authorized(self, body=None):
            supplied = self.headers.get('X-Sequence-Token') or (body or {}).get('token', '')
            origin = self.headers.get('Origin')
            allowed = (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
            return self._host_ok() and isinstance(supplied, str) and hmac.compare_digest(supplied, token) and (origin is None or origin in allowed)

        def do_GET(self):
            if not self._host_ok():
                return self._reply(403, {'error': 'Local host required'})
            if self.path == '/':
                return self._reply(200, page, 'text/html; charset=utf-8')
            if self.path == '/api/state' and self._authorized():
                model.mark_ui_alive()
                return self._reply(200, model.snapshot())
            return self._reply(403 if self.path == '/api/state' else 404, {'error': 'Not available'})

        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    raise ValueError('잘못된 요청 크기')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('JSON 객체가 필요합니다')
                if not self._authorized(body):
                    return self._reply(403, {'error': 'Control token / origin required'})
                if self.path == '/api/connect':
                    if telemetry:
                        telemetry.start()
                    else:
                        model.set_connected(True, '모의 모드 연결됨')
                elif self.path == '/api/prepare':
                    model.prepare(body.get('slot'), body.get('seconds'), body.get('target'))
                elif self.path == '/api/run':
                    model.start(body.get('mode'), body.get('index'), body.get('approved'))
                elif self.path == '/api/stop':
                    model.request_stop()
                else:
                    return self._reply(404, {'error': 'Unknown command'})
                return self._reply(200, {'ok': True})
            except (ValueError, TypeError, KeyError) as exc:
                return self._reply(400, {'error': str(exc)[:240]})
            except Exception:
                return self._reply(500, {'error': '시험 명령 처리 실패. 상태와 로그를 확인하세요.'})

    # Bind loopback only. No unauthenticated movement endpoint is exposed.
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--follower-id', default='bc50f050-d0a5-4430-af97-0486cdaec3a2')
    parser.add_argument('--container', default='physical-ai-studio-cuda')
    parser.add_argument('--distribution', default='Ubuntu-24.04')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--poses', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'outputs/robot_panel_live/poses.json')
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'outputs/sequence_panel')
    args = parser.parse_args()
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M%S')
    motion = StudioPoseTransport(args.follower_id, args.container, args.distribution) if args.live else None
    model = SequenceExperiment(args.poses, live=args.live, motion=motion,
                               log_path=args.output / f'{stamp}.jsonl', lease_seconds=6)
    telemetry = Telemetry(model, args.follower_id, args.container, args.distribution) if args.live else None
    server = make_server(model, telemetry, args.port)
    print(f"{'LIVE' if args.live else 'SIMULATION'} sequence panel: http://127.0.0.1:{server.server_port}", flush=True)
    print('No motion starts until the operator clicks Run. Ctrl+C requests HOLD before exit.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        model.close()
        if telemetry:
            telemetry.close()
        server.server_close()


if __name__ == '__main__':
    main()
