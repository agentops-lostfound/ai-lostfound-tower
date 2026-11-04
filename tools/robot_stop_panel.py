"""LF-12 로컬 상태·정지 화면. 장비 연결/이동/재개/Home 명령은 제공하지 않는다.

실제 모드도 기존 소유자에 통신으로만 접근하며 새 소유자를 시작하지 않는다.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import uuid

ROBOT_ID = "0f876b83-64cd-4bb9-9630-963eaeb3c0b7"


def worker_main():
    import zenoh
    from test_robot_owner_zenoh import open_peer
    import hashlib

    prefix = f"physicalai/robot/{ROBOT_ID}"
    port = 20000 + int.from_bytes(hashlib.sha256(prefix.encode()).digest()[:4], "big") % 40000
    session = open_peer(zenoh, port, listen=False)
    # 구독은 소유자가 있는 경우 읽기만 한다. 하드웨어 소유자를 생성하지 않는다.
    subscriber = session.declare_subscriber(prefix + "/state", zenoh.handlers.RingChannel(1))
    try:
        for line in sys.stdin:
            request = json.loads(line)
            response = {"id": request.get("id"), "ok": False}
            try:
                operation = request.get("op")
                if operation not in ("status", "stop"):
                    raise ValueError("상태·정지만 지원합니다")
                payload = {"version": "lf-owner-safety-v1", "op": operation}
                if operation == "stop":
                    value = request.get("session")
                    if not isinstance(value, str) or not value:
                        raise ValueError("화면에서 확인한 소유자 세션이 필요합니다")
                    payload["session"] = value
                for reply in session.get(prefix + "/lf-safety", payload=json.dumps(payload).encode(), timeout=1.5):
                    if reply.ok is not None:
                        response.update(json.loads(reply.ok.payload.to_bytes()))
                        break
                else:
                    response["error"] = "전용 소유자 응답 없음. 장비를 자동 연결하지 않습니다."
            except Exception as error:
                response["error"] = str(error)
            print(json.dumps(response, ensure_ascii=True), flush=True)
    finally:
        subscriber.undeclare()
        session.close()


class Worker:
    def __init__(self, command):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, encoding="utf-8", bufsize=1)
        self.replies = queue.Queue()
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            try:
                self.replies.put(json.loads(line))
            except ValueError:
                pass
        self.replies.put({"worker_exited": True})

    def request(self, operation, session=None):
        with self.lock:
            if self.process.poll() is not None:
                return {"ok": False, "error": "통신 작업자가 종료됐습니다"}
            identity = uuid.uuid4().hex
            try:
                self.process.stdin.write(json.dumps({"id": identity, "op": operation, "session": session}) + "\n")
                self.process.stdin.flush()
                import time
                deadline = time.monotonic() + 4
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise queue.Empty
                    reply = self.replies.get(timeout=remaining)
                    if reply.get("worker_exited"):
                        return {"ok": False, "error": "통신 작업자가 종료됐습니다"}
                    if reply.get("id") == identity:
                        return reply
            except (queue.Empty, BrokenPipeError, OSError):
                return {"ok": False, "error": "통신 실패: 실제 정지를 확인할 수 없습니다"}

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self.process.terminate()
            self.process.wait(timeout=3)


PAGE = r'''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SO101 정지 시험</title>
<style>body{font:18px system-ui;max-width:720px;margin:50px auto;padding:20px;background:#f4f6f8;color:#17212b}button{font:700 24px system-ui;border:0;border-radius:12px;padding:24px;width:100%;cursor:pointer}#stop{background:#b91c1c;color:white}button:disabled{opacity:.45}#state{background:white;padding:24px;border-radius:12px;margin:24px 0;white-space:pre-wrap}small{display:block;margin:20px 0;line-height:1.7}</style>
<h1>SO101 정지 시험</h1><small>새 팔로워 · 상태 확인과 정지만 지원합니다.<br>이 화면은 로봇 연결·토크 ON·이동·Home을 시작하지 않습니다.</small>
<div id="state" role="status">소유자 연결 상태 확인 중…</div>
<button id="stop" disabled>정지 요청</button><small>‘유지 명령 전송 완료’는 실제 팔이 멈췄다는 센서 검증이 아닙니다.</small>
<pre id="detail"></pre>
<script>
const token=__TOKEN__; let current=null, busy=false, stopping=false;
const box=document.getElementById('state'), button=document.getElementById('stop');
async function call(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:{'X-LF-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('화면 통신 실패');return response.json()}
function show(value){if(!value.ok){button.disabled=!current;box.textContent=value.error||'소유자 상태 확인 실패';return}if(current&&value.session===current.session&&value.epoch<current.epoch)return;current=value;button.disabled=false;box.textContent=value.stop_requested?(value.hold_commanded?'정지 요청 상태 · 유지 명령 전송 완료':'정지 요청 접수 · 유지 처리 대기'):'이동 허용 상태';document.getElementById('detail').textContent='소유자 세션: '+value.session+'\n명령 세대: '+value.epoch;}
async function poll(){if(busy||stopping)return;busy=true;try{const value=await call('/status');if(!stopping)show(value)}catch(error){if(!stopping)show({ok:false,error:'통신 실패 · 실제 정지 상태를 확인할 수 없습니다'})}finally{busy=false}}
button.onclick=async()=>{if(!current||stopping)return;const session=current.session;stopping=true;button.disabled=true;box.textContent='정지 요청 전송 중…';try{show(await call('/stop',{session}))}catch(error){show({ok:false,error:'정지 요청 전달 실패 · 실제 장비 상태를 확인하세요'})}finally{stopping=false;poll()}};
poll();setInterval(poll,1000);
</script></html>'''


def make_handler(status_worker, stop_worker, token, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def json_reply(self, value, status=200):
            content = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def allowed(self, *, control=False):
            if self.headers.get("Host") not in allowed_hosts:
                return False
            if control and self.headers.get("X-LF-Token") != token:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in {"http://" + host for host in allowed_hosts}

        def do_GET(self):
            if not self.allowed(control=self.path != "/"):
                self.json_reply({"ok": False, "error": "허용하지 않는 요청"}, 403)
            elif self.path == "/":
                content = PAGE.replace("__TOKEN__", json.dumps(token)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif self.path == "/status":
                self.json_reply(status_worker.request("status"))
            else:
                self.json_reply({"ok": False}, 404)

        def do_POST(self):
            if not self.allowed(control=True):
                self.json_reply({"ok": False, "error": "허용하지 않는 요청"}, 403)
                return
            if self.path != "/stop":
                self.json_reply({"ok": False}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("요청 크기 오류")
                body = json.loads(self.rfile.read(length))
                session = body.get("session")
                if not isinstance(session, str) or not session:
                    raise ValueError("소유자 세션 필요")
            except (ValueError, TypeError, AttributeError):
                self.json_reply({"ok": False, "error": "요청 형식 오류"}, 400)
                return
            self.json_reply(stop_worker.request("stop", session))
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio-worker", action="store_true")
    parser.add_argument("--container-dir")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    if args.stdio_worker:
        worker_main()
        return
    if not args.container_dir or not args.container_dir.startswith("/tmp/lf-owner-"):
        parser.error("시험 파일이 있는 /tmp/lf-owner-... 경로를 --container-dir로 지정하세요")
    command = ["docker", "exec", "-i", "physical-ai-studio-cuda", "python",
               args.container_dir.rstrip("/") + "/robot_stop_panel.py", "--stdio-worker"]
    status_worker = stop_worker = server = None
    try:
        status_worker = Worker(command)
        stop_worker = Worker(command)  # 상태 조회 대기와 정지 전송을 분리한다.
        token = secrets.token_urlsafe(32)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(status_worker, stop_worker, token, args.port))
        print(f"브라우저에서 http://127.0.0.1:{args.port} 를 여세요. 새 소유자를 시작하지 않습니다.", flush=True)
        print("종료: Ctrl+C. 화면 종료는 실제 로봇 정지 명령이 아닙니다.", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.server_close()
        for worker in (status_worker, stop_worker):
            if worker is not None:
                worker.close()


if __name__ == "__main__":
    main()
