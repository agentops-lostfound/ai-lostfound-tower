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


def run_trial(client, *, confirmed=False, sleep=time.sleep, emit=print):
    require(confirmed is True, "사용자 준비 확인 없이 이동하지 않습니다")
    initial = client.rpc("status")
    require(initial.get("ok") and initial.get("stop_requested") and initial.get("hold_commanded"),
            "정지 요청 상태 및 유지 명령 완료가 필요합니다")
    session = initial["session"]
    epoch = initial["epoch"]
    # 카운트다운 중 누른 정지 버튼도 취소로 인정하며 재개로 덮어쓰지 않는다.
    for second in (3, 2, 1):
        emit(f"{second}초 후 맨 아래 좌우 회전 관절만 최대 정규화 1단위 이동", flush=True)
        for _ in range(10):
            sleep(0.1)
            status = client.rpc("status")
            require(status.get("ok") and status.get("session") == session
                    and status.get("epoch") == epoch and status.get("stop_requested")
                    and status.get("hold_commanded"), "카운트다운 중 상태 변경: 이동 취소")
    baseline = client.positions()
    validate_positions(baseline)
    writer = "bounded-stop-" + uuid.uuid4().hex
    result = {"result": "MANUAL_STOP_NOT_OBSERVED", "joint": "shoulder_pan",
              "max_command_delta_normalized": MAX_DELTA, "baseline": baseline,
              "sent_targets": 0, "max_observed_delta_normalized": 0.0,
              "automatic_return": False, "stop_requested_after_trial": False}
    try:
        resumed = client.rpc("resume", session=session, epoch=epoch,
                             writer=writer, staff_confirmed=True)
        require(resumed.get("ok") and resumed.get("session") == session, "재개 실패")
        token = resumed["epoch"]
        emit("이동 시작 — 정지 화면의 빨간 버튼을 누르세요.", flush=True)
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
            target[0] += MAX_DELTA * sequence / STEPS
            response = client.rpc("action", session=session, epoch=token, writer=writer,
                                  sequence=sequence, target=target)
            if not response.get("ok"):
                if response.get("session") == session and response.get("stop_requested"):
                    result["result"] = "MANUAL_STOP_OBSERVED"
                    break
                raise RuntimeError("이동 요청 거부: " + response.get("error", "unknown"))
            result["sent_targets"] += 1
            sleep(PERIOD)
    finally:
        # 정상 종료/통신 오류/Ctrl+C 모두 같은 세션에 정지를 시도한다.
        # 이전 위치로 자동 복귀하지 않는다. 이미 전송된 I/O는 취소할 수 없다.
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
    args = parser.parse_args()
    if not args.confirm_ready:
        parser.error("실물 이동 시험입니다. 준비 확인 후 --confirm-ready가 필요합니다")
    print("실물 제한 이동 시험: 정지 화면을 보면서 이동 시작 후 정지 버튼을 누르세요.", flush=True)
    client = Client()
    try:
        print(json.dumps(run_trial(client, confirmed=True), ensure_ascii=True, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
