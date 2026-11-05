"""LF-12: 제공된 원본 ZIP에서 실험 패치를 별도 폴더에만 생성한다.

설치된 Studio/physicalai 파일을 수정하거나 로봇을 연결하지 않는다.
"""
import argparse
import ast
import hashlib
import json
import enum
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import sys
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robot.owner_bridge import OwnerBridge

EXPECTED_SHA256 = "fb01e47292a94c48fc00cb5e8ec42a4d6ec9d0987ecefaab0da6f60258a7b625"
OWNER_IN_ZIP = "physicalai/physicalai/robot/transport/_owner_worker.py"
FOLLOWER_ID = "0f876b83-64cd-4bb9-9630-963eaeb3c0b7"


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("원본 소스 구조 불일치: " + old[:70])
    return source.replace(old, new, 1)


def patched_source(source):
    source = once(source, "from loguru import logger\n", "from loguru import logger\nfrom physicalai.robot.transport._lf_owner_bridge import for_so101, guard_manual_start\n")
    source = once(source,
        "    heartbeat_interval_s: float = _HEARTBEAT_INTERVAL_S,\n",
        "    heartbeat_interval_s: float = _HEARTBEAT_INTERVAL_S,\n    safety_bridge: Any = None,\n")
    source = once(source,
        "        _apply_pending_action(driver, action_sub, name)\n",
        "        if safety_bridge is None:\n            _apply_pending_action(driver, action_sub, name)\n        else:\n            # 대상 팔로워의 기존 무세대 /action 명령은 모두 폐기한다.\n            action_sub.try_recv()\n            safety_bridge.tick()\n")
    source = once(source,
        "    reason = OwnerExitReason.LOOP_FAILURE\n    exit_code = 1\n    try:\n",
        "    reason = OwnerExitReason.LOOP_FAILURE\n    exit_code = 1\n    safety_queryable = None\n    safety_bridge = None\n    try:\n"
        f"        if config.name == {FOLLOWER_ID!r}:\n"
        "            if config.allow_remote:\n                raise RuntimeError('LF 안전 연결부는 로컬 전용입니다')\n"
        "            driver_type = type(endpoints.driver)\n"
        "            if (driver_type.__module__, driver_type.__name__) != ('physicalai_so101_plugin.so101', 'SO101'):\n"
        "                raise RuntimeError('검토한 SO101 드라이버만 지원합니다')\n"
        "            safety_bridge = for_so101(endpoints.driver)\n"
        "            safety_key = f'physicalai/robot/{config.name}/lf-safety'\n"
        "            def answer_safety(query):\n"
        "                payload = query.payload\n"
        "                response = safety_bridge.receive(payload.to_bytes() if payload is not None else b'')\n"
        "                query.reply(safety_key, json.dumps(response).encode('utf-8'))\n"
        "            safety_queryable = endpoints.session.declare_queryable(safety_key, answer_safety)\n")
    source = once(source,
        "            on_event=on_event,\n        )\n        exit_code = 0",
        "            on_event=on_event,\n            safety_bridge=safety_bridge,\n        )\n        exit_code = 0")
    source = once(source,
        "        shutdown_event.set()\n        try:\n            endpoints.driver.disconnect()",
        "        shutdown_event.set()\n        if safety_queryable is not None:\n            with contextlib.suppress(Exception):\n                safety_queryable.undeclare()\n        try:\n            endpoints.driver.disconnect()")
    source = once(source, "        driver.connect()\n", "        guard_manual_start(config.name)\n        driver.connect()\n")
    ast.parse(source)
    return source


def prepare(archive, output_root):
    with zipfile.ZipFile(archive) as source_zip:
        original = source_zip.read(OWNER_IN_ZIP)
    digest = hashlib.sha256(original).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("검토한 원본 해시와 다릅니다")
    root = Path(__file__).resolve().parents[1]
    gate = (root / "robot/command_gate.py").read_text(encoding="utf-8")
    bridge = (root / "robot/owner_bridge.py").read_text(encoding="utf-8")
    patched = patched_source(original.decode("utf-8"))
    check_patched_loop(patched)
    files = {"_owner_worker.py": patched, "_lf_command_gate.py": gate,
             "_lf_owner_bridge.py": bridge}
    for name, content in files.items():
        compile(content, name, "exec")
    output = Path(output_root) / uuid.uuid4().hex
    output.mkdir(parents=True)
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8", newline="\n")
    manifest = {"status": "PREPARED_NOT_INSTALLED", "target_robot_id": FOLLOWER_ID,
                "source_sha256": digest, "hardware_connected": False,
                "mock_owner_loop_checks": 4,
                "files": {name: hashlib.sha256(content.encode()).hexdigest()
                          for name, content in files.items()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output


def check_patched_loop(source):
    """패치된 실제 루프만 추출해 가짜 장비/전송부로 실행한다."""
    tree = ast.parse(source)
    names = {"OwnerExitReason", "OwnerEvent", "_run_loop"}
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[
        ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    ast.fix_missing_locations(module)
    for scenario in ("initial_hold", "stop_pending", "new_action", "legacy_ungated"):
        calls = []
        stop = threading.Event()
        observation = SimpleNamespace(joint_positions=(0,)*6, state=(0,)*6,
                                      timestamp=0.0, sensor_data=None)
        def read():
            stop.set()  # 한 주기만 실행
            return observation
        legacy = SimpleNamespace(try_recv=lambda: calls.append("discard_legacy"))
        publisher = SimpleNamespace(put=lambda value: None,
                                    matching_status=SimpleNamespace(matching=True))
        logger = SimpleNamespace(warning=lambda *a, **k: None,
                                 error=lambda *a, **k: None, info=lambda *a, **k: None)
        namespace = {"enum": enum, "time": time, "logger": logger,
                     "_HEARTBEAT_INTERVAL_S": 30.0, "_MAX_CONSECUTIVE_FAILURES": 5,
                     "encode_state": lambda **kw: b"mock",
                     "_apply_pending_action": lambda *a: calls.append("legacy_send")}
        exec(compile(module, "<verified-owner-loop>", "exec"), namespace)
        bridge = OwnerBridge(send=lambda target: calls.append("safe_send"),
                             hold=lambda: calls.append("hold"))
        if scenario in ("stop_pending", "new_action"):
            bridge.tick()
            token = bridge.receive(json.dumps({"version": bridge.VERSION,
                "session": bridge.session, "op": "resume", "epoch": 0,
                "staff_confirmed": True, "writer": "test"}).encode())["epoch"]
            bridge.receive(json.dumps({"version": bridge.VERSION,
                "session": bridge.session, "op": "action", "epoch": token,
                "writer": "test", "sequence": 1, "target": [0]*6}).encode())
            if scenario == "stop_pending":
                bridge.receive(json.dumps({"version": bridge.VERSION,
                    "session": bridge.session, "op": "stop"}).encode())
        namespace["_run_loop"](SimpleNamespace(get_observation=read), publisher,
            legacy, rate_hz=1000, idle_timeout=1, name="mock", shutdown_event=stop,
            safety_bridge=None if scenario == "legacy_ungated" else bridge)
        expected = {"initial_hold": ["discard_legacy", "hold"],
                    "stop_pending": ["hold", "discard_legacy", "hold"],
                    "new_action": ["hold", "discard_legacy", "safe_send"],
                    "legacy_ungated": ["legacy_send"]}[scenario]
        if calls != expected:
            raise RuntimeError(f"소유자 루프 모의 시험 실패: {scenario}: {calls}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", required=True)
    parser.add_argument("--output-root", default="outputs/robot-owner-patch")
    args = parser.parse_args()
    output = prepare(args.source_zip, args.output_root)
    print("PREPARED_NOT_INSTALLED")
    print(output.resolve())
    print("원본 해시 및 Python 구문 검증 완료. 설치·USB·모터 접근 없음.")
    print("패치된 소유자 루프 모의 시험 4개 통과.")


if __name__ == "__main__":
    main()
