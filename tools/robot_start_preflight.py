"""LF-12 팔로워 읽기 전용 점검. 목표값 쓰기는 토크를 켤 수 있어 금지한다."""
import argparse
import dataclasses
import json
import os
from pathlib import Path
import time

SERIAL = "5B91030622"
NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def diagnose_bus(bus, expected, *, backup_dir):
    """불일치 상태도 그대로 기록한다. 모터 레지스터에는 쓰지 않는다."""
    actual = {name: dataclasses.asdict(cal) for name, cal in bus.read_calibration().items()}
    differences = {}
    for name in sorted(set(expected) | set(actual)):
        reference, observed = expected.get(name, {}), actual.get(name, {})
        changed = {key: {"expected": reference.get(key), "actual": observed.get(key)}
                   for key in sorted(set(reference) | set(observed))
                   if reference.get(key) != observed.get(key)}
        if changed:
            differences[name] = changed
    joints = {}
    for name in NAMES:
        if bus.ping(name) != 777:
            raise RuntimeError(f"모터 식별 실패: {name}")
        joints[name] = {key: bus.read(register, name, normalize=False)
                       for key, register in (("torque", "Torque_Enable"),
                           ("mode", "Operating_Mode"), ("present_raw", "Present_Position"),
                           ("goal_raw", "Goal_Position"))}
    result = {"result": "CALIBRATION_MISMATCH" if differences else "CALIBRATION_MATCH",
              "serial": SERIAL, "calibration_matches": not differences,
              "differences": differences, "expected_calibration": expected,
              "actual_calibration": actual, "joints": joints, "writes_performed": False}
    folder = Path(backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"follower-calibration-diagnostic-{time.time_ns()}.json"
    result["backup"] = str(destination)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    return result


def inspect_bus(bus, expected, *, sync_goal=False, backup_dir=None):
    """호출자가 통신 소유권을 확보하고 연결한 버스를 사용한다."""
    if sync_goal:
        raise RuntimeError("--sync-goal 사용 중단: 목표값 기록이 토크를 켤 수 있습니다")
    actual = {name: dataclasses.asdict(cal) for name, cal in bus.read_calibration().items()}
    if actual != expected:
        raise RuntimeError("보드 보정값 불일치: 목표값을 쓰지 않습니다")
    before = {}
    for name in NAMES:
        if bus.ping(name) != 777:
            raise RuntimeError(f"모터 식별 실패: {name}")
        torque = bus.read("Torque_Enable", name, normalize=False)
        mode = bus.read("Operating_Mode", name, normalize=False)
        present = bus.read("Present_Position", name, normalize=False)
        goal = bus.read("Goal_Position", name, normalize=False)
        if torque != 0:
            raise RuntimeError(f"토크 OFF가 아닙니다: {name}")
        if mode != 0:
            raise RuntimeError(f"위치 제어 모드가 아닙니다: {name}")
        if not 0 <= present <= 4095:
            raise RuntimeError(f"현재 raw 위치가 단일 회전 범위 밖입니다: {name}")
        before[name] = {"torque": torque, "mode": mode, "present_raw": present,
                        "goal_raw": goal, "goal_delta_ticks": goal - present}
    after = {}
    for name in NAMES:
        torque = bus.read("Torque_Enable", name, normalize=False)
        present = bus.read("Present_Position", name, normalize=False)
        goal = bus.read("Goal_Position", name, normalize=False)
        after[name] = {"torque": torque, "present_raw": present, "goal_raw": goal,
                       "goal_delta_ticks": goal - present}
        if torque != 0:
            raise RuntimeError(f"점검 후 토크 OFF 검증 실패: {name}")
    return {"result": "PREFLIGHT_READ_ONLY_OK",
            "serial": SERIAL, "calibration_matches": True, "backup": None,
            "joints": after, "torque_enabled_by_tool": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-file", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sync-goal", action="store_true")
    group.add_argument("--diagnose", action="store_true")
    parser.add_argument("--backup-dir", default="/app/storage/soarm-safety-backups")
    args = parser.parse_args()
    if args.sync_goal:
        parser.error("--sync-goal 사용 중단: 목표값 기록이 토크를 켤 수 있습니다")
    saved = json.loads(Path(args.expected_file).read_text(encoding="utf-8-sig"))
    if saved.get("serial") != SERIAL or set(saved.get("calibration", {})) != set(NAMES):
        raise RuntimeError("장비 시리얼/관절 목록 불일치")
    from manage_robot_owner_patch import require_idle
    require_idle()
    from lerobot.motors.feetech import FeetechMotorsBus
    from lerobot.motors.motors_bus import Motor, MotorNormMode
    motors = {name: Motor(i+1, "sts3215", MotorNormMode.RANGE_0_100
                         if name == "gripper" else MotorNormMode.RANGE_M100_100)
              for i, name in enumerate(NAMES)}
    bus = FeetechMotorsBus(f"/dev/serial/by-id/usb-1a86_USB_Single_Serial_{SERIAL}-if00", motors=motors)
    try:
        bus.connect(handshake=False)
        if args.diagnose:
            result = diagnose_bus(bus, saved["calibration"], backup_dir=args.backup_dir)
        else:
            result = inspect_bus(bus, saved["calibration"], sync_goal=args.sync_goal, backup_dir=args.backup_dir)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=False)


if __name__ == "__main__":
    main()

