"""LF-11/12: 정지 중인 기존 소유자의 현재 자세를 Home 후보로만 저장.

상태 조회 외 제어 요청, 새 장비 연결, 토크/보정/목표값 쓰기는 하지 않는다.
후보 저장은 해당 자세나 복귀 경로의 안전성 승인 또는 Home 실행이 아니다.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time

try:
    from .robot_bounded_stop_trial import Client, ROBOT_ID
except ImportError:
    from robot_bounded_stop_trial import Client, ROBOT_ID

NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def capture(client, output_file, reference, *, sleep=time.sleep):
    if reference.get("serial") != "5B91030622" or set(reference.get("calibration", {})) != set(NAMES):
        raise RuntimeError("최종 팔로워 보정 기준 파일 불일치")
    initial = client.rpc("status")
    if not initial.get("ok") or not initial.get("stop_requested") or not initial.get("hold_commanded"):
        raise RuntimeError("정지 요청 및 유지 명령 완료 상태에서만 기록합니다")
    samples = []
    for _ in range(20):
        state = client.rpc("status")
        if (not state.get("ok") or state.get("session") != initial["session"]
                or state.get("epoch") != initial["epoch"]
                or not state.get("stop_requested") or not state.get("hold_commanded")):
            raise RuntimeError("기록 중 소유자/정지 상태 변경: 후보를 저장하지 않습니다")
        position = client.positions()
        if (not isinstance(position, (list, tuple)) or len(position) != 6
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in position)):
            raise RuntimeError("관절 상태 형식 오류")
        if any(not -100 <= x <= 100 for x in position[:5]) or not 0 <= position[5] <= 100:
            raise RuntimeError("정규화 범위 밖의 관절 상태")
        samples.append(list(position))
        sleep(0.05)
    spans = [max(row[i] for row in samples) - min(row[i] for row in samples) for i in range(6)]
    if any(span > 0.5 for span in spans):
        raise RuntimeError("관측 중 자세 변화: 후보를 저장하지 않습니다")
    canonical = json.dumps(reference["calibration"], sort_keys=True, separators=(",", ":")).encode()
    profile = {
        "schema": "lf-home-candidate-v1", "candidate_only": True,
        "home_approved": False, "path_verified": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "robot_id": ROBOT_ID, "serial": reference["serial"], "unit": "normalized",
        "joint_order": list(NAMES), "positions": samples[-1],
        "observation_span_normalized": spans, "sample_count": len(samples),
        "owner_session": initial["session"], "epoch": initial["epoch"],
        "calibration_reference_sha256": hashlib.sha256(canonical).hexdigest(),
        "board_calibration_checked_by_capture": False,
        "movement_commands_sent": 0,
    }
    # 저장 직전에도 상태를 대조해 재개 요청을 확인한다.
    final = client.rpc("status")
    if (not final.get("ok") or final.get("session") != initial["session"]
            or final.get("epoch") != initial["epoch"]
            or not final.get("stop_requested") or not final.get("hold_commanded")):
        raise RuntimeError("저장 직전에 상태가 변경됐습니다")
    path = Path(output_file)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(profile, stream, ensure_ascii=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    return {"result": "HOME_CANDIDATE_SAVED", "container_file": str(path),
            "positions": profile["positions"], "home_approved": False,
            "path_verified": False, "movement_commands_sent": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--calibration-reference", required=True)
    args = parser.parse_args()
    reference = json.loads(Path(args.calibration_reference).read_text(encoding="utf-8-sig"))
    client = Client()
    try:
        print(json.dumps(capture(client, args.output_file, reference), ensure_ascii=True, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
