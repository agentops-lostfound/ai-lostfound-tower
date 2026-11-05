"""LF-12 로컬 정지·근거리 Home 시험 화면.

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


def home_worker_main():
    from robot_home_return import run_home, Client
    for line in sys.stdin:
        request = json.loads(line)
        response = {"id": request.get("id"), "ok": False}
        client = None
        try:
            if (request.get("op") != "home" or request.get("staff_confirmed") is not True
                    or not isinstance(request.get("session"), str) or type(request.get("epoch")) is not int):
                raise ValueError("직원 확인과 현재 소유자 상태가 필요합니다")
            client = Client()
            result = run_home(client, request["profile"], expected_session=request["session"],
                expected_epoch=request["epoch"], confirmed=True, local_trial=True)
            response.update(ok=result["result"] != "HOME_ABORTED", home_result=result)
        except Exception as error:
            response["error"] = str(error)
            # run_home 내부의 이동 이후 오류는 결과로 반환한다.
            # 여기로 온 일반 예외는 초기 조건 거부 또는 Client 생성 실패다.
            response["not_started"] = True
        finally:
            if client is not None:
                client.close()
        print(json.dumps(response, ensure_ascii=True), flush=True)


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

    def request(self, operation, session=None, *, timeout=4, **fields):
        with self.lock:
            if self.process.poll() is not None:
                return {"ok": False, "error": "통신 작업자가 종료됐습니다"}
            identity = uuid.uuid4().hex
            try:
                self.process.stdin.write(json.dumps({**fields, "id": identity, "op": operation, "session": session}) + "\n")
                self.process.stdin.flush()
                import time
                deadline = time.monotonic() + timeout
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


class HomeController:
    def __init__(self, home_worker, stop_worker, profile_loader, action_lock=None):
        self.action_lock = action_lock or threading.Lock()
        self.worker = home_worker
        self.stop_worker = stop_worker
        self.profile_loader = profile_loader
        self.lock = threading.Lock()
        self.thread = None
        self.current = {"ok": True, "state": "idle", "message": "Home 시험 대기"}

    def start(self, session, epoch, *, staff_confirmed=False):
        if staff_confirmed is not True or not isinstance(session, str) or type(epoch) is not int:
            raise ValueError("직원 확인과 화면에서 읽은 세션·세대가 필요합니다")
        if not self.action_lock.acquire(blocking=False):
            raise RuntimeError("Home 이동 또는 설정 작업이 진행 중입니다")
        try:
            profile = self.profile_loader()
            with self.lock:
                if self.current["state"] == "running":
                    raise RuntimeError("이미 Home이 진행 중입니다")
                if self.current["state"] == "error":
                    raise RuntimeError("이전 Home 오류를 확인하고 화면을 재시작해야 합니다")
                self.current = {"ok": True, "state": "running", "session": session,
                                "name": profile["name"], "revision": profile["revision"],
                                "message": "근거리 Home 진행 중 · 정지 버튼으로 중단 가능"}
                self.thread = threading.Thread(target=self._run, args=(session, epoch, profile), daemon=True)
                self.thread.start()
                return dict(self.current)
        except Exception:
            self.action_lock.release()
            raise

    def _run(self, session, epoch, profile):
        try:
            self._execute(session, epoch, profile)
        finally:
            self.action_lock.release()

    def _execute(self, session, epoch, profile):
        try:
            response = self.worker.request("home", session, timeout=25, epoch=epoch,
                                           staff_confirmed=True, profile=profile)
            result = response.get("home_result", {})
            code = result.get("result")
            state = "completed" if response.get("ok") and code in ("HOME_REACHED", "HOME_ALREADY_REACHED") else "error"
            if response.get("ok") and code == "HOME_STOPPED":
                state = "stopped"
            message = {"HOME_REACHED": "Home 허용 범위 도달 · 실제 복귀 확인 · 유지 명령 완료",
                       "HOME_ALREADY_REACHED": "이미 Home 범위 안에 있습니다 · 이동 없음",
                       "HOME_STOPPED": "Home 중단 · 자동 재시작 없음"}.get(code,
                          result.get("reason") or response.get("error") or "Home 결과 확인 실패")
            if (state == "error" and not response.get("not_started")
                    and not (result.get("stop_requested_after_home") and result.get("hold_commanded_after_home"))):
                # 오류/시간 초과 시에도 별도 정지 통신으로 같은 세션을 정지시킨다.
                self.stop_worker.request("stop", session)
            with self.lock:
                self.current.update(ok=state != "error", state=state, message=message, result=result)
        except Exception as error:
            try:
                self.stop_worker.request("stop", session)
            finally:
                with self.lock:
                    self.current.update(ok=False, state="error", message=str(error))

    def status(self):
        with self.lock:
            snapshot = dict(self.current)
        if snapshot["state"] == "running":
            snapshot["configured_name"] = snapshot["name"]
            snapshot["configured_revision"] = snapshot["revision"]
        else:
            try:
                profile = self.profile_loader()
                snapshot.update(configured_name=profile["name"], configured_revision=profile["revision"])
            except Exception as error:
                snapshot.update(ok=False, state="error", message="Home 설정 확인 실패: " + str(error))
        return snapshot

    def close(self):
        state = self.status()
        if state["state"] == "running":
            self.stop_worker.request("stop", state["session"])
        thread = self.thread
        if thread is not None:
            thread.join(10)


PAGE = r'''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SO101 정지·Home 시험</title>
<style>body{font:18px system-ui;max-width:720px;margin:36px auto;padding:20px;background:#f4f6f8;color:#17212b}button{font:700 23px system-ui;border:0;border-radius:12px;padding:22px;width:100%;cursor:pointer;margin:6px 0}#stop{background:#b91c1c;color:white}#home{background:#164e82;color:white}button:disabled{opacity:.45}#state,#home-state{background:white;padding:20px;border-radius:12px;margin:18px 0;white-space:pre-wrap}small{display:block;margin:14px 0;line-height:1.6}pre{font-size:13px;white-space:pre-wrap}#home-settings{background:white;padding:20px;border-radius:12px;margin-top:24px}#capture-home{background:#e2e8f0;color:#17212b}#save-home{background:#176644;color:white}#home-name{display:block;box-sizing:border-box;width:100%;padding:12px;font:inherit;margin:8px 0}#pose-preview{width:100%;border-collapse:collapse;margin:16px 0}#pose-preview th,#pose-preview td{text-align:left;padding:8px;border-bottom:1px solid #d7dde5}</style>
<h1>SO101 정지·Home 시험</h1><small>새 팔로워 · 장비를 자동 연결하거나 토크를 켜지 않습니다.</small>
<div id="state" role="status">소유자 연결 상태 확인 중…</div>
<button id="stop" disabled>정지 요청</button>
<button id="home" disabled>저장한 Home으로 복귀 · 근거리 시험</button>
<div id="home-state" role="status">Home 시험 대기</div>
<small>현재는 Home 근처에서 맨 아래 좌우 회전만 복귀합니다. 도달 오차 6틱 이내와 실제 복귀 진척 2틱 이상을 함께 확인합니다. 다른 관절이 달라졌거나 멀리 떨어진 자세에서는 실행을 거부합니다.<br>‘유지 명령 전송 완료’는 실제 팔의 정지 상태와 함께 확인하세요.</small>
<section id="home-settings" hidden>
<h2>Home 대기 위치 재설정</h2>
<p id="configured-home"></p>
<small>현재 정지 시험 구성에서는 Studio Teleoperate로 팔을 조작할 수 없습니다. 자세 배치는 조작 연결을 먼저 준비한 뒤 진행하세요.</small>
<label>Home 이름 <input id="home-name" maxlength="100" placeholder="보관함 옆 대기"></label>
<button id="capture-home" disabled>현재 자세 읽기</button>
<div id="settings-state" role="status">정지·유지 상태에서 현재 자세를 기록할 수 있습니다.</div>
<table id="pose-preview" hidden><thead><tr><th>관절</th><th>기록한 위치</th></tr></thead><tbody></tbody></table>
<button id="save-home" disabled>이 자세를 Home으로 저장</button>
<small>현재 자세를 읽어 미리본 뒤 저장합니다. 저장은 로봇을 움직이거나 보정값을 바꾸지 않습니다. 이전 설정은 이력에 보존합니다. 새 자세까지의 복귀 경로 확인은 별도입니다.</small>
</section>
<pre id="detail"></pre><pre id="home-detail"></pre>
<script>
const token=__TOKEN__,homeEnabled=__HOME_ENABLED__,settingsEnabled=__SETTINGS_ENABLED__;let current=null,busy=false,stopping=false,homeRunning=false,homeStarting=false,statusHealthy=false,homeAvailable=true;
const box=document.getElementById('state'),button=document.getElementById('stop'),homeButton=document.getElementById('home');
const captureButton=document.getElementById('capture-home'),saveButton=document.getElementById('save-home'),homeName=document.getElementById('home-name');
let settingsBusy=false,settingsRequestBusy=false,settingsJob=null,settingsError=null;
document.getElementById('home-settings').hidden=!settingsEnabled;
async function call(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:{'X-LF-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(5000)});let value=await response.json();if(!response.ok)throw Error(value.error||'화면 통신 실패');return value}
function buttons(){button.disabled=!current||stopping;const held=statusHealthy&&current&&current.stop_requested&&current.hold_commanded;
homeButton.disabled=!homeEnabled||!homeAvailable||!held||homeRunning||homeStarting||stopping||settingsBusy||settingsRequestBusy;
captureButton.disabled=!settingsEnabled||!held||homeRunning||homeStarting||stopping||settingsBusy||settingsRequestBusy;
saveButton.disabled=captureButton.disabled||!settingsJob||settingsJob.state!=='preview'||settingsJob.session!==current?.session||settingsJob.epoch!==current?.epoch;}
function show(value){if(!value.ok){statusHealthy=false;box.textContent=value.error||'소유자 상태 확인 실패';homeButton.disabled=true;button.disabled=!current;return}if(current&&value.session===current.session&&value.epoch<current.epoch)return;statusHealthy=true;current=value;buttons();box.textContent=value.stop_requested?(value.hold_commanded?'정지 요청 상태 · 유지 명령 전송 완료':'정지 요청 접수 · 유지 처리 대기'):'이동 허용 상태';document.getElementById('detail').textContent='소유자 세션: '+value.session+'\n명령 세대: '+value.epoch+(value.delivery&&Number.isFinite(value.delivery.observed_present_raw)?'\n맨 아래 회전 현재 위치(raw): '+value.delivery.observed_present_raw+' / 요청 목표(raw): '+value.delivery.requested_pan_raw+' / 토크: '+value.delivery.torque:'')}
async function poll(){if(busy||stopping)return;busy=true;try{const value=await call('/status');if(!stopping)show(value)}catch(error){if(!stopping)show({ok:false,error:'통신 실패 · 실제 정지 상태를 확인할 수 없습니다'})}finally{busy=false}}
async function homePoll(){if(!homeEnabled)return;try{const job=await call('/home-status');homeRunning=job.state==='running';homeAvailable=job.state!=='error';if(job.configured_name)homeButton.textContent=job.configured_name+' 복귀 · 근거리 시험';document.getElementById('home-state').textContent=job.message||'Home 시험 대기';document.getElementById('home-detail').textContent=job.result?JSON.stringify(job.result,null,2):'';buttons()}catch(error){document.getElementById('home-state').textContent='Home 상태 조회 실패';homeButton.disabled=true}}
button.onclick=async()=>{if(!current||stopping)return;const session=current.session;stopping=true;buttons();box.textContent='정지 요청 전송 중…';try{show(await call('/stop',{session}))}catch(error){show({ok:false,error:'정지 요청 전달 실패 · 실제 장비 상태를 확인하세요'})}finally{stopping=false;buttons();poll()}};
homeButton.onclick=async()=>{if(homeButton.disabled)return;if(!confirm('빈 집게·고정된 베이스·빈 이동 공간을 확인했나요?\n저장한 Home 근처에서만 복귀합니다. 정지 버튼으로 중단할 수 있습니다.'))return;const session=current.session,epoch=current.epoch;homeStarting=true;buttons();try{await call('/home',{session,epoch,staff_confirmed:true});homeRunning=true;document.getElementById('home-state').textContent='Home 요청 접수'}catch(error){document.getElementById('home-state').textContent=error.message}finally{homeStarting=false;buttons();homePoll()}};
async function settingsPoll(){if(!settingsEnabled)return;try{settingsJob=await call('/home-settings');settingsBusy=settingsJob.state==='reading'||settingsJob.state==='saving';
document.getElementById('settings-state').textContent=settingsError||settingsJob.message||'';
if(settingsJob.configured){document.getElementById('configured-home').textContent='현재 Home: '+settingsJob.configured.name+' · 버전 '+settingsJob.configured.revision;if(!homeName.dataset.loaded){homeName.value=settingsJob.configured.name;homeName.dataset.loaded='1';}}
const table=document.getElementById('pose-preview'),tbody=table.querySelector('tbody');table.hidden=settingsJob.state!=='preview';tbody.replaceChildren();
if(settingsJob.state==='preview'){const names=['1. 맨 아래 좌우 회전','2. 팔 숙이기·세우기','3. 두 긴 팔 사이 접힘','4. 집게 쪽 위아래 꺾기','5. 집게 전체 회전','6. 집게 여닫기'];settingsJob.positions.forEach((value,index)=>{const row=document.createElement('tr');for(const text of [names[index],Number(value).toFixed(3)]){const cell=document.createElement('td');cell.textContent=text;row.appendChild(cell);}tbody.appendChild(row);});}
if(settingsJob.state==='preview'&&current&&(settingsJob.session!==current.session||settingsJob.epoch!==current.epoch)){document.getElementById('settings-state').textContent='정지 상태가 바뀌었습니다. 현재 자세를 다시 읽어주세요.';}
buttons();}catch(error){settingsBusy=false;settingsJob=null;document.getElementById('settings-state').textContent=error.message;buttons();}}
captureButton.onclick=async()=>{if(captureButton.disabled)return;settingsRequestBusy=true;settingsError=null;buttons();try{await call('/home-capture',{session:current.session,epoch:current.epoch,staff_confirmed:true});}catch(error){settingsError=error.message;document.getElementById('settings-state').textContent=error.message;}finally{settingsRequestBusy=false;settingsPoll();buttons();}};
saveButton.onclick=async()=>{if(saveButton.disabled)return;const name=homeName.value.trim();if(!name){document.getElementById('settings-state').textContent='Home 이름을 입력하세요.';return;}if(!confirm('기록한 자세를 "'+name+'" Home으로 저장할까요?\n로봇은 움직이지 않습니다. 새 복귀 경로 확인은 별도입니다.'))return;settingsRequestBusy=true;settingsError=null;buttons();try{await call('/home-save',{session:current.session,epoch:current.epoch,candidate_id:settingsJob.candidate_id,name,staff_confirmed:true});}catch(error){settingsError=error.message;document.getElementById('settings-state').textContent=error.message;}finally{settingsRequestBusy=false;settingsPoll();homePoll();buttons();}};
poll();homePoll();settingsPoll();setInterval(poll,1000);setInterval(homePoll,1000);setInterval(settingsPoll,1000);
</script></html>'''


def make_handler(status_worker, stop_worker, token, port, home_controller=None, settings_controller=None):
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
                content = PAGE.replace("__TOKEN__", json.dumps(token)).replace(
                    "__HOME_ENABLED__", "true" if home_controller is not None else "false").replace(
                    "__SETTINGS_ENABLED__", "true" if settings_controller is not None else "false").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif self.path == "/status":
                self.json_reply(status_worker.request("status"))
            elif self.path == "/home-settings" and settings_controller is not None:
                self.json_reply(settings_controller.status())
            elif self.path == "/home-status" and home_controller is not None:
                self.json_reply(home_controller.status())
            else:
                self.json_reply({"ok": False}, 404)

        def do_POST(self):
            if not self.allowed(control=True):
                self.json_reply({"ok": False, "error": "허용하지 않는 요청"}, 403)
                return
            if (self.path != "/stop" and not (self.path == "/home" and home_controller is not None)
                    and not (self.path in ("/home-capture", "/home-save") and settings_controller is not None)):
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
            if self.path in ("/home-capture", "/home-save"):
                try:
                    if self.path == "/home-capture":
                        result = settings_controller.capture(session, body.get("epoch"),
                            staff_confirmed=body.get("staff_confirmed"))
                    else:
                        result = settings_controller.save(body.get("candidate_id"), session, body.get("epoch"),
                            name=body.get("name"), staff_confirmed=body.get("staff_confirmed"))
                except ValueError as error:
                    self.json_reply({"ok": False, "error": str(error)}, 400)
                except RuntimeError as error:
                    self.json_reply({"ok": False, "error": str(error)}, 409)
                except Exception as error:
                    self.json_reply({"ok": False, "error": str(error)}, 500)
                else:
                    self.json_reply(result, 202 if self.path == "/home-capture" else 200)
                return
            if self.path == "/home":
                try:
                    job = home_controller.start(session, body.get("epoch"), staff_confirmed=body.get("staff_confirmed"))
                except ValueError as error:
                    self.json_reply({"ok": False, "error": str(error)}, 400)
                except RuntimeError as error:
                    self.json_reply({"ok": False, "error": str(error)}, 409)
                else:
                    self.json_reply(job, 202)
                return
            self.json_reply(stop_worker.request("stop", session))
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio-worker", action="store_true")
    parser.add_argument("--stdio-home-worker", action="store_true")
    parser.add_argument("--container-dir")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--trial-file")
    parser.add_argument("--expected-file")
    args = parser.parse_args()
    if args.stdio_worker:
        worker_main()
        return
    if args.stdio_home_worker:
        home_worker_main()
        return
    if not args.container_dir or not args.container_dir.startswith("/tmp/lf-owner-"):
        parser.error("시험 파일이 있는 /tmp/lf-owner-... 경로를 --container-dir로 지정하세요")
    command = ["docker", "exec", "-i", "physical-ai-studio-cuda", "python",
               args.container_dir.rstrip("/") + "/robot_stop_panel.py", "--stdio-worker"]
    status_worker = stop_worker = home_worker = home_controller = settings_controller = server = None
    try:
        status_worker = Worker(command)
        stop_worker = Worker(command)  # 상태 조회 대기와 정지 전송을 분리한다.
        home_worker = Worker([*command[:-1], "--stdio-home-worker"])
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from robot.home_profiles import load_home
        action_lock = threading.Lock()
        home_controller = HomeController(home_worker, stop_worker, load_home, action_lock)
        if args.trial_file:
            if not args.expected_file:
                parser.error("Home 설정에는 --expected-file이 필요합니다")
            from tools.prepare_robot_owner_trial import load_trial, capture_home
            from tools.robot_home_settings import HomeSettingsController
            from robot.home_profiles import select_candidate
            def capture_pose(session, epoch):
                result = capture_home(load_trial(args.trial_file), args.expected_file,
                                      expected_session=session, expected_epoch=epoch)
                candidate = json.loads(Path(result["windows_file"]).read_text(encoding="utf-8-sig"))
                return {**candidate, "windows_file": result["windows_file"]}
            def save_pose(candidate, name):
                return select_candidate(candidate["windows_file"], name=name)
            settings_controller = HomeSettingsController(capture_pose, save_pose, status_worker,
                                                         load_home, action_lock)
        token = secrets.token_urlsafe(32)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(status_worker, stop_worker, token, args.port, home_controller, settings_controller))
        print(f"브라우저에서 http://127.0.0.1:{args.port} 를 여세요. 새 소유자를 시작하지 않습니다.", flush=True)
        print("종료: Ctrl+C. 진행 중 Home에는 정지를 요청하지만 실제 정지 상태는 별도로 확인하세요.", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.server_close()
        if settings_controller is not None:
            settings_controller.close()
        if home_controller is not None:
            home_controller.close()
        for worker in (home_worker, status_worker, stop_worker):
            if worker is not None:
                worker.close()


if __name__ == "__main__":
    main()
