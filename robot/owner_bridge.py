"""LF-12 실험용 소유자 연결부. import만으로 장비에 연결하지 않는다.

JSON 요청은 별도 safety queryable로 전달한다. 기존 /action은 우회 방지를
위해 패치된 대상 소유자에서 폐기한다. 실제 설치/구동 전용 코드는 별도다.
"""
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

try:
    from .command_gate import CommandGate
except ImportError:
    from ._lf_command_gate import CommandGate


MANUAL_ROBOT_ID = "0f876b83-64cd-4bb9-9630-963eaeb3c0b7"
MANUAL_GUARD_FILE = Path("/app/storage/lf-robot-safety/manual-pose-5B91030622.json")


def guard_manual_start(robot_id, guard_file=MANUAL_GUARD_FILE):
    if robot_id == MANUAL_ROBOT_ID and Path(guard_file).exists():
        raise RuntimeError("수동 자세 변경이 종료되지 않았습니다. 자동 연결을 차단합니다. 현재 자세 유지 복구가 필요합니다")


class ManualPose:
    """소유자 스레드에서 토크 OFF와 현재 위치 유지를 처리한다."""
    def __init__(self, driver, *, clock=time.monotonic, guard_file=None):
        self.driver = driver
        self.guard_file = None if guard_file is None else Path(guard_file)
        self.clock = clock
        self.gate = None
        self.lock = threading.Lock()
        self.phase = "idle"
        self.message = ""
        self.verified = False
        self.pose_valid = False
        self.torques = {}
        self.last_checked = None
        self.pan_raw = None
        self.previous_disconnect = None
        self.anchor = None
        self.anchor_at = None
        self.approved_epoch = None

    def snapshot(self):
        with self.lock:
            return {"state": self.phase, "message": self.message,
                    "torque_off_verified": self.verified,
                    "pose_in_calibrated_range": self.pose_valid,
                    "torque": dict(self.torques), "current_pan_raw": self.pan_raw,
                    "last_checked": self.last_checked,
                    "age_seconds": None if self.last_checked is None else self.clock() - self.last_checked}

    def request(self, operation, epoch):
        state = self.gate.snapshot()
        if state["epoch"] != epoch or not state["stop_requested"]:
            raise RuntimeError("현재 정지 상태와 명령 세대를 확인하세요")
        with self.lock:
            if operation == "manual_pose":
                if self.phase == "idle" and not state["hold_commanded"]:
                    raise RuntimeError("위치 유지 완료 후 자세 변경을 시작하세요")
                if self.phase not in ("idle", "active", "error"):
                    raise RuntimeError("자세 변경 전환이 진행 중입니다")
                self.phase, self.message = "entering", "토크 OFF 처리 중 · 아직 팔을 움직이지 마세요"
                self.verified = False
            else:
                if self.phase not in ("active", "error") or not self.verified or not self.pose_valid:
                    raise RuntimeError("토크 OFF 및 보정 범위 안의 자세를 먼저 확인하세요")
                self.phase, self.message = "hold_check", "현재 자세가 안정적인지 확인 중"
                self.anchor = self.anchor_at = None
            self.gate.request_stop()
            self.approved_epoch = self.gate.snapshot()["epoch"]

    def cancel_hold(self):
        with self.lock:
            if self.phase in ("hold_check", "hold_write"):
                self.phase, self.verified = "cancel_pending", False
                self.message = "자세 유지 전환 취소 · 토크 OFF 확인 중"

    def read_torques(self):
        conn = self.driver._require_connection()
        values = {}
        for name, identity in self.driver.servo_ids.items():
            value, comm, error = conn.packet_handler.read1ByteTxRx(conn.port_handler, identity, 40)
            if comm != 0 or error != 0:
                raise RuntimeError(f"토크 상태 읽기 실패: {name}")
            values[name] = int(value)
        return values

    def verify_goals(self, raw):
        conn = self.driver._require_connection()
        for index, name in enumerate(self.driver.JOINT_ORDER):
            value, comm, error = conn.packet_handler.read2ByteTxRx(
                conn.port_handler, self.driver.servo_ids[name], 42)
            if comm != 0 or error != 0 or int(value) != int(raw[index]):
                raise RuntimeError(f"현재 위치 목표 기록 검증 실패: {name}")

    def read_pose(self):
        raw = self.driver._read_joint_positions()
        if len(raw) != 6 or any(not math.isfinite(float(value)) or not 0 <= value <= 4095 for value in raw):
            raise RuntimeError("현재 원시 위치를 확인할 수 없습니다")
        calibration = self.driver._require_calibration()
        valid = all(calibration.joints[name].range_min <= raw[i] <= calibration.joints[name].range_max
                    for i, name in enumerate(self.driver.JOINT_ORDER))
        return raw, bool(valid)

    def verify_off(self):
        torques = self.read_torques()
        if any(value != 0 for value in torques.values()) or len(torques) != 6:
            raise RuntimeError("6개 관절의 토크 OFF가 확인되지 않았습니다")
        raw, valid = self.read_pose()
        with self.lock:
            self.torques, self.verified, self.pose_valid = torques, True, valid
            self.last_checked, self.pan_raw = self.clock(), int(raw[0])
        return raw

    def ensure_guard(self):
        if self.guard_file is None:
            return
        self.guard_file.parent.mkdir(parents=True, exist_ok=True)
        if self.guard_file.exists():
            existing = json.loads(self.guard_file.read_text())
            if existing.get("robot_id") != MANUAL_ROBOT_ID or existing.get("serial") != "5B91030622":
                raise RuntimeError("알 수 없는 수동 자세 변경 기록을 보존합니다")
            with self.guard_file.open("rb") as stream:
                os.fsync(stream.fileno())
            self.sync_guard_directory()
            return
        handle, temporary = tempfile.mkstemp(prefix=".manual-", dir=self.guard_file.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"robot_id": MANUAL_ROBOT_ID, "serial": "5B91030622"}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.guard_file)
            self.sync_guard_directory()
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def sync_guard_directory(self):
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(self.guard_file.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def clear_guard(self):
        if self.guard_file is not None:
            existing = json.loads(self.guard_file.read_text())
            if existing.get("robot_id") != MANUAL_ROBOT_ID or existing.get("serial") != "5B91030622":
                raise RuntimeError("알 수 없는 수동 자세 변경 기록을 지우지 않습니다")
            self.guard_file.unlink()
            self.sync_guard_directory()

    def turn_off(self):
        self.ensure_guard()
        if self.previous_disconnect is None:
            self.previous_disconnect = self.driver.torque_on_disconnect
        # 수동 모드에서 소유자가 종료되어도 disconnect가 토크를 다시 켜지 않게 한다.
        self.driver.torque_on_disconnect = False
        self.driver.set_torque(enabled=False)
        return self.verify_off()

    def service(self):
        with self.lock:
            phase, checked = self.phase, self.last_checked
        if phase == "idle":
            return False
        try:
            if phase in ("entering", "cancel_pending"):
                self.turn_off()
                with self.lock:
                    self.phase, self.message = "active", "토크 OFF 확인 · 팔을 받친 상태에서 자세를 바꾸세요"
            elif phase == "active":
                if checked is None or self.clock() - checked >= 0.25:
                    self.verify_off()
            elif phase == "hold_check":
                raw = self.verify_off()
                if not self.pose_valid:
                    raise RuntimeError("보정 범위 밖입니다. 토크 OFF 상태에서 자세를 조정하세요")
                with self.lock:
                    if self.phase != "hold_check":
                        return True
                    if self.anchor is None:
                        self.anchor, self.anchor_at = list(raw), self.clock()
                        return True
                    if self.clock() - self.anchor_at < 0.2:
                        return True
                    if any(abs(float(a) - float(b)) > 2 for a, b in zip(raw, self.anchor)):
                        raise RuntimeError("자세가 움직이고 있습니다. 받침을 안정시킨 뒤 다시 확인하세요")
                    if self.gate.snapshot()["epoch"] != self.approved_epoch:
                        self.phase = "cancel_pending"
                        return True
                    self.phase = "hold_write"
                self.driver._write_joint_positions(raw)
                self.verify_goals(raw)
                # 목표 기록 자체가 토크를 켤 수 있다. 이 경로는 사용자 확인 후에만 도달한다.
                with self.lock:
                    cancelled = self.phase != "hold_write" or self.gate.snapshot()["epoch"] != self.approved_epoch
                if cancelled:
                    self.turn_off()
                    with self.lock:
                        self.phase, self.message = "active", "유지 전환 취소 · 토크 OFF"
                    return True
                self.driver.set_torque(enabled=True)
                torques = self.read_torques()
                if len(torques) != 6 or any(value != 1 for value in torques.values()):
                    raise RuntimeError("현재 자세 유지의 토크 ON 검증 실패")
                with self.lock:
                    cancelled = self.phase != "hold_write" or self.gate.snapshot()["epoch"] != self.approved_epoch
                if not cancelled:
                    self.clear_guard()
                    self.driver.torque_on_disconnect = self.previous_disconnect
                with self.lock:
                    cancelled = self.phase != "hold_write" or self.gate.snapshot()["epoch"] != self.approved_epoch
                    if not cancelled:
                        self.previous_disconnect = None
                        self.phase, self.message = "idle", "현재 자세 유지 시작 · 토크 ON"
                        self.verified, self.torques = False, torques
                if cancelled:
                    self.turn_off()
                    with self.lock:
                        self.phase, self.message = "active", "유지 전환 취소 · 토크 OFF"
                    return True
                return False
            # error에서는 명령을 추가하지 않고 사용자 재확인을 기다린다.
        except Exception as error:
            message = str(error)
            try:
                self.turn_off()
            except Exception as off_error:
                message += "; 토크 OFF 재확인 실패: " + str(off_error)
                with self.lock:
                    self.verified = False
            with self.lock:
                self.phase, self.message = "error", message
        return True


class OwnerBridge:
    VERSION = "lf-owner-safety-v1"

    def __init__(self, *, send, hold, dimensions=6, delivery_status=None, manual_pose=None):
        self._manual_pose = manual_pose
        self._delivery_status = delivery_status
        self.session = uuid.uuid4().hex
        self._gate = CommandGate(send=send, hold=hold)
        if manual_pose is not None:
            manual_pose.gate = self._gate
        self._lock = threading.Lock()
        self._writer = None
        self._sequence = -1
        self._dimensions = dimensions

    def status(self):
        result = {"version": self.VERSION, "session": self.session,
                  **self._gate.snapshot()}
        if self._manual_pose is not None:
            result["manual_pose"] = self._manual_pose.snapshot()
            if result["manual_pose"]["state"] != "idle":
                result["hold_commanded"] = False
        if self._delivery_status is not None:
            result["delivery"] = self._delivery_status()
        return result

    def tick(self):
        if self._manual_pose is not None and self._manual_pose.service():
            return "manual_pose"
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
                    if self._manual_pose is not None:
                        self._manual_pose.cancel_hold()
                    self._writer = None
                    return {"ok": True, "ack": "stop_requested", **self.status()}
                epoch = request.get("epoch")
                if type(epoch) is not int:
                    raise ValueError("명령 세대 번호 필요")
                if operation in ("manual_pose", "manual_hold"):
                    if self._manual_pose is None or request.get("staff_confirmed") is not True:
                        raise PermissionError("자세 변경 지원과 사용자 준비 확인이 필요합니다")
                    self._manual_pose.request(operation, epoch)
                    self._writer = None
                    return {"ok": True, **self.status()}
                if self._manual_pose is not None and self._manual_pose.snapshot()["state"] != "idle":
                    raise RuntimeError("수동 자세 변경 중에는 이동·재개를 허용하지 않습니다")
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

    return OwnerBridge(send=send, hold=hold, delivery_status=delivery_status, manual_pose=ManualPose(driver, guard_file=MANUAL_GUARD_FILE))
