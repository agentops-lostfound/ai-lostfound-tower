"""LF-12: 단일 소유자의 전송 직전 관문. 하드웨어에 연결하지 않는다."""

import threading


class CommandGate:
    """드라이버 소유 스레드에서만 service()를 호출하는 명령 관문.

    send/hold는 호출자가 제공한다. request_stop은 I/O 잠금을 기다리지 않는다.
    이미 시작된 I/O를 중단하지 못하며 물리적 즉시 정지를 보장하지 않는다.
    실제 Studio 전송 프로토콜 연결 전에는 실물 제어에 사용하지 않는다.
    """

    def __init__(self, *, send, hold):
        self._send = send
        self._hold = hold
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._epoch = 0
        self._pending = None
        self._held = False
        self._owner = None
        self._stop.set()  # 초기 연결 시 자동 이동 금지

    def request_stop(self):
        # 이 잠금은 메모리 상태만 보호하며 I/O 중에는 잡지 않는다.
        with self._lock:
            self._stop.set()
            self._epoch += 1
            self._pending = None
            self._held = False

    def snapshot(self):
        with self._lock:
            return {"epoch": self._epoch, "stop_requested": self._stop.is_set(),
                    "hold_commanded": self._held}

    def resume(self, *, staff_confirmed=False, expected_epoch=None):
        if not staff_confirmed:
            raise PermissionError("직원 확인 필요")
        with self._lock:
            if expected_epoch is not None and expected_epoch != self._epoch:
                raise RuntimeError("오래된 재개 요청")
            if not self._held:
                raise RuntimeError("소유자의 위치 유지 성공 확인 필요")
            self._epoch += 1
            self._pending = None
            self._stop.clear()
            return self._epoch

    def submit(self, epoch, target):
        with self._lock:
            if self._stop.is_set() or epoch != self._epoch:
                return False
            self._pending = (epoch, target)  # 최신 절대 목표 한 개만 유지
            return True

    def service(self):
        owner = threading.get_ident()
        if self._owner is None:
            self._owner = owner
        elif self._owner != owner:
            raise RuntimeError("동일한 드라이버 소유 스레드에서 호출해야 합니다")
        with self._lock:
            epoch = self._epoch
            stopped = self._stop.is_set()
            pending = self._pending
            self._pending = None
            held = self._held
        if stopped:
            if not held:
                # 실제 구현은 최신 위치 읽기+유지 목표 쓰기 성공 후 반환해야 한다.
                # 실패 시 예외를 전달하며 정지 래치와 재개 차단을 유지한다.
                self._hold()
                with self._lock:
                    if self._epoch == epoch:
                        self._held = True
            return "stopped"
        if pending is None:
            return "idle"
        # 추론/전처리는 이 함수 밖에서 수행하고 전송 직전 다시 검사한다.
        with self._lock:
            allowed = not self._stop.is_set() and pending[0] == self._epoch
        if not allowed:
            return "blocked"
        try:
            self._send(pending[1])
        except Exception:
            self.request_stop()
            raise
        return "sent"
