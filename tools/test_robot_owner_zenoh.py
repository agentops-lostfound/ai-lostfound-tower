"""LF-12: 설치 전 패치 후보와 실제 Zenoh, 가짜 모터로 통신 시험.

드라이버·모델·Studio API·USB를 사용하지 않는다. loopback 임시 시험
이름만 사용하며 설치 파일과 보정값을 변경하지 않는다.
"""
import argparse
from concurrent.futures import Future
import hashlib
import importlib.util
from importlib.metadata import version
import json
from pathlib import Path
import queue
import sys
import threading
import time
import types
import uuid


EXPECTED_SOURCE = "fb01e47292a94c48fc00cb5e8ec42a4d6ec9d0987ecefaab0da6f60258a7b625"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_candidate(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("status") == "PREPARED_NOT_INSTALLED", "설치 전 후보가 아닙니다")
    require(manifest.get("source_sha256") == EXPECTED_SOURCE, "검토한 원본 해시 불일치")
    for name in ("_owner_worker.py", "_lf_command_gate.py", "_lf_owner_bridge.py"):
        content = (directory / name).read_bytes()
        require(hashlib.sha256(content).hexdigest() == manifest["files"].get(name),
                f"후보 파일 해시 불일치: {name}")
        compile(content, name, "exec")
    package_name = "lf_candidate_" + uuid.uuid4().hex
    package = types.ModuleType(package_name)
    package.__path__ = [str(directory)]
    sys.modules[package_name] = package
    name = package_name + "._lf_owner_bridge"
    spec = importlib.util.spec_from_file_location(name, directory / "_lf_owner_bridge.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.OwnerBridge


def open_peer(zenoh, port, *, listen):
    config = zenoh.Config()
    config.insert_json5("mode", '"peer"')
    config.insert_json5("scouting/multicast/enabled", "false")
    config.insert_json5("scouting/gossip/enabled", "false")
    config.insert_json5("listen/endpoints", f'["tcp/127.0.0.1:{port}"]' if listen else '[]')
    if not listen:
        config.insert_json5("connect/endpoints", f'["tcp/127.0.0.1:{port}"]')
        config.insert_json5("connect/retry", '{"period_init_ms":100,"period_max_ms":500,"period_increase_factor":1.5}')
    return zenoh.open(config)


def run(directory):
    import zenoh

    bridge_type = load_candidate(directory)
    identity = "lf-dryrun-" + uuid.uuid4().hex
    # 실제 장비 식별자와 독립된 임시 시험 포트를 사용한다.
    port = 20000 + int(hashlib.sha256(identity.encode()).hexdigest()[:8], 16) % 40000
    key = f"physicalai/robot/{identity}/lf-safety"
    calls = []
    jobs = queue.Queue()
    release = threading.Event()
    entered = threading.Event()
    block = threading.Event()

    def send(target):
        if block.is_set():
            entered.set()
            if not release.wait(8):
                raise TimeoutError("가짜 I/O 대기 시간 초과")
        calls.append(("send", target))

    bridge = bridge_type(send=send, hold=lambda: calls.append(("hold", None)))

    def owner():
        while True:
            future = jobs.get()
            if future is None:
                return
            try:
                future.set_result(bridge.tick())
            except Exception as error:
                future.set_exception(error)

    worker = threading.Thread(target=owner, name="fake-motor-owner", daemon=True)
    worker.start()

    def tick(wait=True):
        future = Future()
        jobs.put(future)
        return future.result(timeout=4) if wait else future

    server = client = endpoint = None
    checks = []
    try:
        server = open_peer(zenoh, port, listen=True)

        def answer(query):
            payload = query.payload.to_bytes() if query.payload is not None else b""
            response = bridge.receive(payload)
            query.reply(key, json.dumps(response).encode("utf-8"))

        endpoint = server.declare_queryable(key, answer)
        client = open_peer(zenoh, port, listen=False)

        def raw_rpc(payload):
            for reply in client.get(key, payload=payload, timeout=2.0):
                if reply.ok is not None:
                    return json.loads(reply.ok.payload.to_bytes())
            raise TimeoutError("Zenoh 응답 없음")

        def rpc(operation, **fields):
            return raw_rpc(json.dumps({"version": bridge.VERSION,
                "session": bridge.session, "op": operation, **fields}).encode())

        deadline = time.monotonic() + 6
        while True:
            try:
                status = rpc("status")
                break
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        require(status["ok"] and status["stop_requested"], "초기 정지 상태 오류")
        require(not calls, "통신 연결만으로 I/O가 발생했습니다")
        checks.append("연결만으로 이동하지 않음")

        rejected = rpc("resume", epoch=status["epoch"], writer="trial", staff_confirmed=True)
        require(not rejected["ok"], "유지 확인 전 재개 허용")
        tick()
        response = rpc("resume", epoch=0, writer="trial", staff_confirmed=True)
        require(response["ok"], "확인 후 재개 실패")
        token = response["epoch"]
        checks.append("소유자 유지 처리 후 확인 재개")

        reply = rpc("action", epoch=token, writer="trial", sequence=1, target=[0]*6)
        require(reply["ok"] and reply["ack"] == "queued", "이동 대기 등록 실패")
        stopped = rpc("stop")
        require(stopped["ok"] and not stopped["hold_commanded"], "정지 접수/유지 응답 구분 실패")
        tick()
        require(rpc("status")["hold_commanded"], "유지 명령 완료 확인 실패")
        require(all(kind == "hold" for kind, target in calls), "정지한 대기 목표가 전송됨")
        checks.append("정지 접수와 유지 완료 구분 및 대기 목표 폐기")

        require(not rpc("resume", epoch=token, writer="trial", staff_confirmed=True)["ok"],
                "오래된 재개 요청 허용")
        resumed = rpc("resume", epoch=stopped["epoch"], writer="trial", staff_confirmed=True)
        require(resumed["ok"], "새 세대 재개 실패")
        new_token = resumed["epoch"]
        require(not rpc("action", epoch=token, writer="trial", sequence=2, target=[0]*6)["ok"],
                "늦은 추론 결과 허용")
        require(not rpc("stop", session="previous-owner")["ok"], "다른 소유자 세션 허용")
        require(not raw_rpc(b'{"action":[0,0,0,0,0,0]}')["ok"], "기존 형식 우회 허용")
        checks.append("오래된 세대/다른 세션/기존 명령 형식 거부")

        block.set()
        require(rpc("action", epoch=new_token, writer="trial", sequence=1, target=[0]*6)["ok"],
                "가짜 I/O 등록 실패")
        inflight = tick(wait=False)
        require(entered.wait(3), "가짜 I/O 시작 실패")
        started = time.perf_counter()
        response = rpc("stop")
        stop_rpc_seconds = time.perf_counter() - started
        require(response["ok"] and not response["hold_commanded"], "실행 중 정지 접수 실패")
        require(not inflight.done(), "가짜 I/O가 정지 요청 전에 끝남")
        require(not rpc("action", epoch=new_token, writer="trial", sequence=2, target=[0]*6)["ok"],
                "정지 후 새 목표 허용")
        release.set()
        inflight.result(timeout=4)
        tick()
        require(rpc("status")["hold_commanded"], "I/O 종료 후 유지 처리 실패")
        require(sum(kind == "send" for kind, target in calls) == 1, "추가 목표 전송 발생")
        checks.append("실행 중 I/O를 기다리지 않고 정지 접수, 이후 명령 차단")
        return {"result": "ZENOH_FAKE_ROBOT_OK", "checks": checks,
                "zenoh_version": version("eclipse-zenoh"),
                "stop_rpc_seconds": stop_rpc_seconds,
                "hardware_connected": False, "installed_files_changed": False,
                "note": "실제 로봇 정지 시간 측정이 아닙니다"}
    finally:
        release.set()
        jobs.put(None)
        worker.join(10)
        if endpoint is not None:
            endpoint.undeclare()
        if client is not None:
            client.close()
        if server is not None:
            server.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch-dir", required=True)
    args = parser.parse_args()
    print("FAKE ROBOT ONLY: USB/Studio/모델에 연결하지 않습니다", flush=True)
    print(json.dumps(run(args.patch_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
