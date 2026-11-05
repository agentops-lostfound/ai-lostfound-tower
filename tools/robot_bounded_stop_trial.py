"""LF-12 기존 소유자의 맨 아래 회전 관절만 제한 이동시키는 정지 시험.

--confirm-ready 없이 이동하지 않는다. 새 소유자 생성/토크 ON/보정/Home은
제공하지 않는다. 실물 실행 전 빈 집게·고정된 베이스·빈 이동 공간과 사용자가
보는 정지 화면이 필요하다. 정규화 1단위는 1도가 아니다.
"""
import argparse
import hashlib
import json
import math
import time
import uuid

ROBOT_ID = "0f876b83-64cd-4bb9-9630-963eaeb3c0b7"
VERSION = "lf-owner-safety-v1"
MAX_DELTA = 1.0
STEPS = 60
PERIOD = 0.05


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Client:
    """장비를 새로 연결하지 않고 기존 소유자에만 통신한다."""
    def __init__(self):
        import zenoh
        try:
            from .test_robot_owner_zenoh import open_peer
        except ImportError:
            from test_robot_owner_zenoh import open_peer
        prefix = f"physicalai/robot/{ROBOT_ID}"
        port = 20000 + int.from_bytes(hashlib.sha256(prefix.encode()).digest()[:4], "big") % 40000
        self.session = open_peer(zenoh, port, listen=False)
        self.key = prefix + "/lf-safety"
        self.subscriber = self.session.declare_subscriber(prefix + "/state", zenoh.handlers.RingChannel(1))

    def rpc(self, operation, **fields):
        payload = json.dumps({"version": VERSION, "op": operation, **fields}).encode()
        for reply in self.session.get(self.key, payload=payload, timeout=1.0):
            if reply.ok is not None:
                result = json.loads(reply.ok.payload.to_bytes())
                require(result.get("version") == VERSION, "전용 소유자 응답이 아닙니다")
                return result
        raise TimeoutError("소유자 응답 없음")

    def positions(self):
        from physicalai.robot.transport._codec import decode_state
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            sample = self.subscriber.try_recv()
            if sample is not None:
                observation = decode_state(sample.payload.to_bytes())
                age = time.monotonic() - observation.timestamp
                if -0.05 <= age <= 0.2:
                    return [float(value) for value in observation.joint_positions]
            time.sleep(0.005)
        raise TimeoutError("최신 관절 상태를 읽지 못했습니다")

    def close(self):
        self.subscriber.undeclare()
        self.session.close()


def validate_positions(values):
    require(isinstance(values, (tuple, list)) and len(values) == 6, "6개 관절 상태 필요")
    require(all(type(x) in (int, float) and math.isfinite(x) for x in values), "유효한 관절 상태 필요")
    require(all(-100 <= x <= 100 for x in values[:5]) and 0 <= values[5] <= 100,
            "관절 상태가 정규화 범위 밖입니다")
    require(-95 <= values[0] <= 95, "맨 아래 회전 관절이 시험 허용 시작 범위 밖입니다")


def plan_offset(baseline, profile, *, side="positive"):
    try:
        from robot.home_profiles import validate_profile
    except ImportError:
        from home_profiles import validate_profile
    validate_profile(profile)
    validate_positions(baseline)
    home = profile["positions"]
    require(abs(baseline[0] - home[0]) <= 1.0, "Home 근거리 범위 밖입니다")
    require(all(abs(baseline[i] - home[i]) <= 0.2 for i in range(1, 6)),
            "다른 관절이 Home 자세와 다릅니다")
    require(side in ("positive", "negative"), "지원하지 않는 시험 방향입니다")
    end = home[0] + (0.8 if side == "positive" else -0.5)
    require(-95 <= end <= 95 and abs(end - baseline[0]) <= MAX_DELTA,
            "Home 기준 목표 또는 이동량이 기존 시험 한계를 넘습니다")
    return end


def run_trial(client, *, confirmed=False, sleep=time.sleep, emit=print, home_profile=None, home_side="positive"):
    require(confirmed is True, "사용자 준비 확인 없이 이동하지 않습니다")
    initial = client.rpc("status")
    require(initial.get("ok") and initial.get("stop_requested") and initial.get("hold_commanded"),
            "정지 요청 상태 및 유지 명령 완료가 필요합니다")
    session = initial["session"]
    epoch = initial["epoch"]
    # 카운트다운 중 누른 정지 버튼도 취소로 인정하며 재개로 덮어쓰지 않는다.
    for second in (3, 2, 1):
        label = ("Home 기준 +0.8 위치로 제한 이동" if home_side == "positive"
                 else "Home 기준 -0.5 위치로 제한 이동") if home_profile is not None else "맨 아래 좌우 회전 관절만 최대 정규화 1단위 이동"
        emit(f"{second}초 후 {label}", flush=True)
        for _ in range(10):
            sleep(0.1)
            status = client.rpc("status")
            require(status.get("ok") and status.get("session") == session
                    and status.get("epoch") == epoch and status.get("stop_requested")
                    and status.get("hold_commanded"), "카운트다운 중 상태 변경: 이동 취소")
    baseline = client.positions()
    validate_positions(baseline)
    end_pan = baseline[0] + MAX_DELTA if home_profile is None else plan_offset(baseline, home_profile, side=home_side)
    if home_profile is not None and abs(end_pan - baseline[0]) <= 0.2:
        return {"result": "HOME_OFFSET_ALREADY_REACHED", "baseline": baseline,
                "target_pan": end_pan, "sent_targets": 0, "automatic_return": False}
    writer = "bounded-stop-" + uuid.uuid4().hex
    result = {"result": "MANUAL_STOP_NOT_OBSERVED", "joint": "shoulder_pan",
              "max_command_delta_normalized": MAX_DELTA, "baseline": baseline,
              "sent_targets": 0, "max_observed_delta_normalized": 0.0,
              "automatic_return": False, "stop_requested_after_trial": False,
              "target_pan": end_pan, "position_trace": [],
              "request_acknowledgement": "queued_only", "delivery_before": initial.get("delivery")}
    try:
        resumed = client.rpc("resume", session=session, epoch=epoch,
                             writer=writer, staff_confirmed=True)
        require(resumed.get("ok") and resumed.get("session") == session, "재개 실패")
        token = resumed["epoch"]
        emit("이동 시작 — 이상 움직임이면 정지 버튼을 누르세요." if home_profile is not None
             else "이동 시작 — 정지 화면의 빨간 버튼을 누르세요.", flush=True)
        for sequence in range(1, STEPS+1):
            status = client.rpc("status")
            require(status.get("ok") and status.get("session") == session, "소유자 변경/응답 실패")
            if status.get("stop_requested"):
                result["result"] = "MANUAL_STOP_OBSERVED"
                break
            require(status.get("epoch") == token, "다른 제어 명령이 들어와 시험 중단")
            measured = client.positions()
            validate_positions(measured)
            delta = abs(measured[0] - baseline[0])
            result["max_observed_delta_normalized"] = max(result["max_observed_delta_normalized"], delta)
            require(delta <= MAX_DELTA + 0.5, "관측 이동량이 시험 한계를 초과했습니다")
            require(all(abs(measured[i] - baseline[i]) <= 1.0 for i in range(1, 6)),
                    "다른 관절 위치 변화로 시험 중단")
            target = list(baseline)
            target[0] = baseline[0] + (end_pan - baseline[0]) * sequence / STEPS
            if home_profile is not None:
                require(abs(measured[0] - home_profile["positions"][0]) <= 1.0,
                        "관측 위치가 Home 시험 한계를 넘었습니다")
                require(all(abs(measured[i] - home_profile["positions"][i]) <= 0.2
                            for i in range(1, 6)), "다른 관절이 Home 허용 범위를 벗어났습니다")
            response = client.rpc("action", session=session, epoch=token, writer=writer,
                                  sequence=sequence, target=target)
            if not response.get("ok"):
                if response.get("session") == session and response.get("stop_requested"):
                    result["result"] = "MANUAL_STOP_OBSERVED"
                    break
                raise RuntimeError("이동 요청 거부: " + response.get("error", "unknown"))
            result["sent_targets"] += 1
            if sequence == 1 or sequence % 10 == 0:
                result["position_trace"].append({"sequence": sequence,
                    "requested_pan": target[0], "observed_pan_before_request": measured[0],
                    "delivery_before_request": status.get("delivery")})
            sleep(PERIOD)
        else:
            if home_profile is not None:
                result["result"] = "HOME_OFFSET_SEQUENCE_COMPLETE"
                emit("최종 목표를 유지하며 최대 2초간 위치를 관측합니다.", flush=True)
                for settle in range(40):
                    current = client.rpc("status")
                    require(current.get("ok") and current.get("session") == session,
                            "도달 관측 중 소유자/응답 변경")
                    if current.get("stop_requested"):
                        result["result"] = "MANUAL_STOP_OBSERVED"
                        break
                    require(current.get("epoch") == token, "도달 관측 중 제어 세대 변경")
                    observed = client.positions()
                    validate_positions(observed)
                    require(abs(observed[0] - home_profile["positions"][0]) <= 1.0,
                            "도달 관측 중 Home 범위 이탈")
                    require(all(abs(observed[i] - home_profile["positions"][i]) <= 0.2
                                for i in range(1, 6)), "도달 관측 중 다른 관절 변화")
                    if settle in (0, 19, 39):
                        result["position_trace"].append({"phase": "settle", "sample": settle + 1,
                            "requested_pan": end_pan, "observed_pan": observed[0],
                            "delivery": current.get("delivery")})
                    sleep(0.05)
    finally:
        # 정상 종료/통신 오류/Ctrl+C 모두 같은 세션에 정지를 시도한다.
        # 이전 위치로 자동 복귀하지 않는다. 이미 전송된 I/O는 취소할 수 없다.
        try:
            result["delivery_before_stop"] = client.rpc("status").get("delivery")
        except Exception as error:
            result["delivery_read_error"] = str(error)
        try:
            reply = client.rpc("stop", session=session)
            result["stop_requested_after_trial"] = bool(reply.get("ok") and reply.get("session") == session
                                                         and reply.get("stop_requested"))
        except Exception as error:
            result["stop_error"] = str(error)
        emit("종료 정지 요청: " + json.dumps(result, ensure_ascii=True), flush=True)
    require(result["stop_requested_after_trial"], "종료 정지 요청 확인 실패: 실제 장비 상태를 확인하세요")
    for _ in range(20):
        status = client.rpc("status")
        require(status.get("ok") and status.get("session") == session and status.get("stop_requested"),
                "정지 확인 중 소유자/모드 변경")
        if status.get("hold_commanded"):
            result["hold_commanded_after_trial"] = True
            samples = []
            for _ in range(10):
                sample = client.positions()
                validate_positions(sample)
                samples.append(sample)
                sleep(0.05)
            result["final_positions"] = samples[-1]
            if home_profile is not None:
                require(all(abs(row[0] - home_profile["positions"][0]) <= 1.0 for row in samples),
                        "정지 후 관측 위치가 Home 시험 한계를 넘었습니다")
                require(all(abs(row[i] - home_profile["positions"][i]) <= 0.2
                            for row in samples for i in range(1, 6)),
                        "정지 후 다른 관절이 Home 허용 범위를 벗어났습니다")
                result["offset_reached"] = abs(samples[-1][0] - end_pan) <= 0.2
            result["post_stop_span_normalized"] = [
                max(row[i] for row in samples) - min(row[i] for row in samples)
                for i in range(6)
            ]
            result["max_observed_delta_normalized"] = max(
                result["max_observed_delta_normalized"],
                max(abs(row[0] - baseline[0]) for row in samples),
            )
            result["note"] = "정규화 관절 상태의 관측값이며 물리적 즉시 정지 보장은 아닙니다"
            return result
        sleep(0.05)
    raise TimeoutError("유지 명령 완료를 확인하지 못했습니다")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-ready", action="store_true")
    parser.add_argument("--home-profile")
    parser.add_argument("--home-side", choices=("positive", "negative"), default="positive")
    args = parser.parse_args()
    if not args.confirm_ready:
        parser.error("실물 이동 시험입니다. 준비 확인 후 --confirm-ready가 필요합니다")
    profile = None
    if args.home_profile:
        from pathlib import Path
        profile = json.loads(Path(args.home_profile).read_text(encoding="utf-8-sig"))
    print("실물 제한 이동 시험: 정지 화면을 보면서 진행하세요.", flush=True)
    client = Client()
    try:
        print(json.dumps(run_trial(client, confirmed=True, home_profile=profile, home_side=args.home_side), ensure_ascii=True, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
