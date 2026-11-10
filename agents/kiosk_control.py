"""키오스크 조작 화면은 하나 — 같은 등록기계 화면을 여러 PC 에서 열어도 한 화면만 찍고 접수한다 (LF-2, 11/10 변재원)

한줄 설명: 카메라(포토박스)는 하나인데 습득 화면을 연 PC 마다 따로 "물건이 놓였다"를 판단해 찍으면 서로 꼬인다.
그래서 관제탑이 기계마다 **지금 조작 중인 화면 하나**만 인정하고, 나머지 화면은 영상만 보는 '보기 전용'이 된다.

규칙
- 조작 화면이 없거나, 있던 화면이 STALE_S 초 동안 소식이 없으면(창을 닫음·다른 탭으로 감) → 먼저 물은 화면이 조작 화면이 된다
- 조작 화면이 살아 있으면 다른 화면은 보기 전용. 그 화면에서 [여기서 조작하기]를 누르면(take) 조작 화면이 넘어온다
- 화면은 2초마다 묻는다(POST /api/kiosk/control/{기계} {"client": 화면 ID, "take": false})
- 기억은 관제탑 메모리에만 둔다(다시 켜면 처음 묻는 화면이 조작 화면). 개인정보는 없다 — 화면 ID 는 브라우저가 만든 무작위 글자
"""
from __future__ import annotations

import re
import threading
import time

STALE_S = 8.0                                   # 이 시간 동안 소식이 없으면 조작 화면이 떠난 것으로 본다
MACHINE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
CLIENT = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


class KioskControl:
    def __init__(self, clock=time.monotonic, stale_s: float = STALE_S):
        self._clock, self.stale_s = clock, stale_s
        self._lock = threading.Lock()
        self._owner: dict[str, tuple[str, float]] = {}        # 기계 → (화면 ID, 마지막 소식)
        self._seen: dict[str, dict[str, float]] = {}          # 기계 → {화면 ID: 마지막 소식}  (보는 화면 수 표시용)

    def beat(self, machine: str, client: str, take: bool = False) -> dict:
        """화면 하나의 소식 → {"control": 이 화면이 조작 화면인가, "watchers": 같이 열어 둔 다른 화면 수, "taken": 방금 넘겨받음}"""
        now = self._clock()
        with self._lock:
            seen = self._seen.setdefault(machine, {})
            seen[client] = now
            for c in [c for c, t in seen.items() if now - t > self.stale_s]:
                del seen[c]
            owner = self._owner.get(machine)
            alive = owner is not None and now - owner[1] <= self.stale_s
            taken = False
            if owner is not None and owner[0] == client:
                self._owner[machine] = (client, now)
            elif not alive or take:
                taken = alive                                  # 살아 있는 조작 화면에서 넘겨받았는가
                self._owner[machine] = (client, now)
            control = self._owner[machine][0] == client
            return {"control": control, "watchers": max(0, len(seen) - 1), "taken": taken}

    def owner(self, machine: str) -> str | None:
        with self._lock:
            o = self._owner.get(machine)
            return o[0] if o is not None and self._clock() - o[1] <= self.stale_s else None


def add_control_routes(app, control: KioskControl | None = None) -> KioskControl:
    """POST /api/kiosk/control/{기계} — 화면이 2초마다 묻는다(로그인 없이: 키오스크 화면이 부름)"""
    from fastapi import Body, HTTPException
    ctl = control or KioskControl()
    try:
        app.state.kiosk_control = ctl             # 사진 접수(POST /api/kiosk/items)가 조작 화면인지 확인할 때 쓴다
    except Exception:
        pass

    @app.post("/api/kiosk/control/{machine}")
    def kiosk_control(machine: str, payload: dict = Body(...)) -> dict:
        client = payload.get("client") if isinstance(payload, dict) else None
        if not MACHINE.match(machine or "") or not isinstance(client, str) or not CLIENT.match(client):
            raise HTTPException(status_code=422, detail="machine·client 형식")
        return ctl.beat(machine, client, take=payload.get("take") is True)

    return ctl


__all__ = ["KioskControl", "add_control_routes", "STALE_S"]
