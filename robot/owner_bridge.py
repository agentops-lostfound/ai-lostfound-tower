"""LF-12 실험용 소유자 연결부. import만으로 장비에 연결하지 않는다.

JSON 요청은 별도 safety queryable로 전달한다. 기존 /action은 우회 방지를
위해 패치된 대상 소유자에서 폐기한다. 실제 설치/구동 전용 코드는 별도다.
"""
import json
import math
import threading
import time
import uuid

try:
    from .command_gate import CommandGate
except ImportError:
    from ._lf_command_gate import CommandGate


class OwnerBridge:
    VERSION = "lf-owner-safety-v1"

    def __init__(self, *, send, hold, dimensions=6, delivery_status=None):
        self._delivery_status = delivery_status
        self.session = uuid.uuid4().hex
        self._gate = CommandGate(send=send, hold=hold)
        self._lock = threading.Lock()
        self._writer = None
        self._sequence = -1
        self._dimensions = dimensions

    def status(self):
        result = {"version": self.VERSION, "session": self.session,
                  **self._gate.snapshot()}
        if self._delivery_status is not None:
            result["delivery"] = self._delivery_status()
        return result

    def tick(self):
        return self._gate.service()

    def receive(self, data):
        """콜백 스레드에서 호출 가능. 모터 I/O는 tick에서만 실행한다.

        staff_confirmed는 호출자의 명시적 확인 표시이며 인증 기능이 아니다.
        대상 패치는 allow_remote=False인 로컬 전용 소유자에서만 허용한다.
        """
        with self._lock:
            try:
                if not isinstance(data, bytes) or len(data) > 8192:
                    raise ValueError("요청 크기/형식 오류")
                request = json.loads(data)
                if not isinstance(request, dict) or request.get("version") != self.VERSION:
                    raise ValueError("전용 명령 형식 필요")
                operation = request.get("op")
                if operation == "status":
                    return {"ok": True, **self.status()}
                if request.get("session") != self.session:
                    raise ValueError("소유자 세션 불일치")
                if operation == "stop":
                    self._gate.request_stop()
                    self._writer = None
                    return {"ok": True, "ack": "stop_requested", **self.status()}
                epoch = request.get("epoch")
                if type(epoch) is not int:
                    raise ValueError("명령 세대 번호 필요")
                if operation == "resume":
                    if request.get("staff_confirmed") is not True:
                        raise PermissionError("직원 확인 필요")
                    writer = request.get("writer")
                    if not isinstance(writer, str) or not 1 <= len(writer) <= 128:
                        raise ValueError("제어 클라이언트 식별자 필요")
                    if not self._gate.snapshot()["stop_requested"]:
                        raise RuntimeError("이미 재개 상태")
                    self._gate.resume(staff_confirmed=True, expected_epoch=epoch)
                    self._writer = writer
                    self._sequence = -1
                    return {"ok": True, **self.status()}
                if operation != "action":
                    raise ValueError("지원하지 않는 명령")
                if self._writer is None or request.get("writer") != self._writer:
                    raise PermissionError("제어 클라이언트 불일치")
                sequence = request.get("sequence")
                if type(sequence) is not int or sequence <= self._sequence:
                    raise ValueError("중복/역순 명령")
                target = request.get("target")
                if not isinstance(target, list) or len(target) != self._dimensions:
                    raise ValueError("관절 목표 차원 불일치")
                if any(type(x) not in (int, float) or not math.isfinite(x) for x in target):
                    raise ValueError("유한한 관절 목표 필요")
                if not self._gate.submit(epoch, tuple(target)):
                    raise RuntimeError("정지 상태 또는 오래된 명령")
                self._sequence = sequence
                return {"ok": True, "ack": "queued", **self.status()}
            except (ValueError, TypeError, RuntimeError, PermissionError, UnicodeError, OverflowError) as error:
                return {"ok": False, "error": str(error), **self.status()}


def for_so101(driver):
    """연결된 SO101 소유자에 사용. 함수 호출 자체는 연결/토크 조작 없음.

    hold는 raw 읽기/쓰기로 관절 범위 클리핑을 피한다. 토크 ON 쓰기를 명시적으로
    추가하지 않지만 목표 기록이 모터 토크를 켤 수 있어 이미 토크 ON인 팔로워에만 쓴다.
    """
    import numpy as np

    if driver.role != "follower" or driver.unit != "normalized":
        raise RuntimeError("보정된 normalized SO101 팔로워만 지원합니다")

    def hold():
        raw = driver._read_joint_positions()
        if raw.shape != (6,) or not np.all(np.isfinite(raw)):
            raise RuntimeError("현재 위치 읽기 검증 실패")
        driver._write_joint_positions(raw.astype(np.int32))

    delivery_lock = threading.Lock()
    delivery = {"schema": "lf-pan-goal-readback-v1", "attempts": 0,
                "driver_calls_returned": 0, "readbacks": 0}

    def delivery_status():
        with delivery_lock:
            return dict(delivery)

    def send(target):
        # 실제 프로젝트 안전 범위는 별도 정책으로 검증해야 한다.
        if any(not -100 <= x <= 100 for x in target[:5]) or not 0 <= target[5] <= 100:
            raise ValueError("정규화 관절 범위 밖의 목표")
        action = np.asarray(target, dtype=np.float32)
        expected_raw = int(driver._unit_to_ticks(action)[0])
        with delivery_lock:
            delivery.update(attempts=delivery["attempts"] + 1, requested_pan=float(target[0]),
                            requested_pan_raw=expected_raw, stage="driver_call",
                            error=None, observed_goal_raw=None, goal_matches_request=None,
                            read_at_monotonic=None, observed_present_raw=None, torque=None)
        try:
            driver.send_action(action)
            with delivery_lock:
                delivery["driver_calls_returned"] += 1
                delivery["stage"] = "read_goal"
            # 소유자 스레드에서만 읽는다. 정지 콜백은 이 I/O 잠금을 기다리지 않는다.
            conn = driver._require_connection()
            block, comm, error = conn.packet_handler.readTxRx(
                conn.port_handler, driver.servo_ids["shoulder_pan"], 40, 18)
            if comm != 0 or error != 0:
                raise RuntimeError(f"pan 목표 읽기 실패: comm={comm}, error={error}")
            if len(block) != 18:
                raise RuntimeError("pan 상태 읽기 길이 오류")
            goal = int(block[2]) | (int(block[3]) << 8)
            present = int(block[16]) | (int(block[17]) << 8)
            with delivery_lock:
                delivery.update(observed_present_raw=present, torque=int(block[0]), readbacks=delivery["readbacks"] + 1,
                                observed_goal_raw=int(goal), goal_matches_request=int(goal) == expected_raw,
                                stage="goal_readback", read_at_monotonic=time.monotonic())
            if int(goal) != expected_raw:
                raise RuntimeError("pan 목표 레지스터와 요청값 불일치")
        except Exception as error:
            with delivery_lock:
                delivery.update(stage="error", error=str(error))
            raise

    return OwnerBridge(send=send, hold=hold, delivery_status=delivery_status)
