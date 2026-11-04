"""LF-12 팔로워 시작 전 점검. 토크 ON이나 보정값 쓰기는 하지 않는다.

--sync-goal은 토크 OFF 상태에서 현재 raw 위치를 Goal_Position에 기록한다.
실제 연결 시의 토크 ON 안전성이나 충돌 회피를 보장하는 기능은 아니다.
"""
import argparse
import dataclasses
import json
import os
from pathlib import Path
import time

SERIAL = "5B91030622"
NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def inspect_bus(bus, expected, *, sync_goal=False, backup_dir=None):
    """호출자가 통신 소유권을 확보하고 연결한 버스를 사용한다."""
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
    backup_path = None
    if sync_goal:
        if backup_dir is None:
            raise ValueError("목표값 변경 전 백업 폴더가 필요합니다")
        folder = Path(backup_dir)
        folder.mkdir(parents=True, exist_ok=True)
        backup_path = folder / f"follower-before-goal-sync-{time.time_ns()}.json"
        with backup_path.open("x") as stream:
            json.dump({"serial": SERIAL, "calibration": actual, "joints": before}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # 기록 직전 전 관절의 토크 OFF를 다시 확인한다.
        if any(bus.read("Torque_Enable", name, normalize=False) != 0 for name in NAMES):
            raise RuntimeError("점검 중 토크 상태 변경: 목표값 기록 중단")
        for name in NAMES:
            bus.write("Goal_Position", name, before[name]["present_raw"], normalize=False)
    after = {}
    for name in NAMES:
        torque = bus.read("Torque_Enable", name, normalize=False)
        present = bus.read("Present_Position", name, normalize=False)
        goal = bus.read("Goal_Position", name, normalize=False)
        after[name] = {"torque": torque, "present_raw": present, "goal_raw": goal,
                       "goal_delta_ticks": goal - present}
        if torque != 0:
            raise RuntimeError(f"점검 후 토크 OFF 검증 실패: {name}")
        if sync_goal and (goal != before[name]["present_raw"] or abs(present - goal) > 5):
            raise RuntimeError(f"목표값 불일치 또는 점검 중 자세 변화: {name}. 토크를 켜지 마세요")
    return {"result": "GOAL_SYNCED_TORQUE_OFF" if sync_goal else "PREFLIGHT_READ_ONLY_OK",
            "serial": SERIAL, "calibration_matches": True, "backup": str(backup_path) if backup_path else None,
            "joints": after, "torque_enabled_by_tool": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-file", required=True)
    parser.add_argument("--sync-goal", action="store_true")
    parser.add_argument("--backup-dir", default="/app/storage/soarm-safety-backups")
    args = parser.parse_args()
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
        result = inspect_bus(bus, saved["calibration"], sync_goal=args.sync_goal, backup_dir=args.backup_dir)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=False)


if __name__ == "__main__":
    main()

