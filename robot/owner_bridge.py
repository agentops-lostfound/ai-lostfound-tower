"""LF-12 실험용 소유자 연결부. import만으로 장비에 연결하지 않는다.

JSON 요청은 별도 safety queryable로 전달한다. 기존 /action은 우회 방지를
위해 패치된 대상 소유자에서 폐기한다. 실제 설치/구동 전용 코드는 별도다.
"""
import json
import math
import threading
import uuid

try:
    from .command_gate import CommandGate
except ImportError:
    from ._lf_command_gate import CommandGate


class OwnerBridge:
    VERSION = "lf-owner-safety-v1"

    def __init__(self, *, send, hold, dimensions=6):
        self.session = uuid.uuid4().hex
        self._gate = CommandGate(send=send, hold=hold)
        self._lock = threading.Lock()
        self._writer = None
        self._sequence = -1
        self._dimensions = dimensions

    def status(self):
        return {"version": self.VERSION, "session": self.session,
                **self._gate.snapshot()}

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

    hold는 raw 읽기/쓰기로 관절 범위 클리핑을 피한다. 토크 상태는 변경하지
    않으며 이미 구동 중인 토크 ON 팔로워의 위치 유지 용도다.
    """
    import numpy as np

    if driver.role != "follower" or driver.unit != "normalized":
        raise RuntimeError("보정된 normalized SO101 팔로워만 지원합니다")

    def hold():
        raw = driver._read_joint_positions()
        if raw.shape != (6,) or not np.all(np.isfinite(raw)):
            raise RuntimeError("현재 위치 읽기 검증 실패")
        driver._write_joint_positions(raw.astype(np.int32))

    def send(target):
        # 실제 프로젝트 안전 범위는 별도 정책으로 검증해야 한다.
        if any(not -100 <= x <= 100 for x in target[:5]) or not 0 <= target[5] <= 100:
            raise ValueError("정규화 관절 범위 밖의 목표")
        driver.send_action(np.asarray(target, dtype=np.float32))

    return OwnerBridge(send=send, hold=hold)
