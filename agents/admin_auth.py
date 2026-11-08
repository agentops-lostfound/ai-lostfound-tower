"""관리자 로그인 (LF-2) — 관제탑 관리자 API 를 비밀번호 하나로 잠근다.

한줄 설명: .env 의 LF_ADMIN_PASSWORD 가 있으면 관리자 API(반환·로봇 원점·관제 상태·찾기 조회)가 로그인 세션(쿠키)을 요구한다.
- LF_ADMIN_PASSWORD  관리자 비밀번호. 비어 있으면 로그인 기능 꺼짐(예전처럼 열림, 시연·시험용) — /health 의 admin_auth 로 확인
- LF_ADMIN_SECRET    세션 서명 비밀(선택). 없으면 관제탑을 켤 때마다 새로 만들어 재시작하면 모두 로그아웃
- LF_ADMIN_API_KEY   로그인 없이 부르는 도구(봇·스크립트)용 키(선택). 헤더 X-Admin-Key 로 보낸다
- 정지(/robot/stop)는 안전 원칙상 로그인 없이 항상 동작한다(이 모듈과 무관)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

COOKIE = "lf_admin"
TTL_SECONDS = 8 * 3600
MAX_FAILS = 5          # 같은 주소에서 연속 실패 허용 횟수
LOCK_SECONDS = 60      # 넘으면 잠시 잠금


class AdminAuth:
    def __init__(self, password: str = "", secret: str = "", api_key: str = "", ttl: int = TTL_SECONDS):
        self.password = password or ""
        self._secret = (secret or secrets.token_hex(32)).encode()
        self.api_key = api_key or ""
        self.ttl = ttl
        self._fails: dict[str, tuple[int, float]] = {}

    @classmethod
    def from_env(cls) -> "AdminAuth":
        return cls(os.environ.get("LF_ADMIN_PASSWORD", ""), os.environ.get("LF_ADMIN_SECRET", ""),
                   os.environ.get("LF_ADMIN_API_KEY", ""))

    @property
    def enabled(self) -> bool:
        return bool(self.password)

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def locked(self, who: str, now: float | None = None) -> bool:
        count, since = self._fails.get(who, (0, 0.0))
        return count >= MAX_FAILS and (now or time.time()) - since < LOCK_SECONDS

    def login(self, password: str, who: str = "", now: float | None = None) -> str | None:
        """맞으면 세션 토큰, 틀리거나 잠겨 있으면 None"""
        now = now or time.time()
        if not self.enabled or self.locked(who, now):
            return None
        if not hmac.compare_digest(str(password).encode(), self.password.encode()):
            count, since = self._fails.get(who, (0, now))
            self._fails[who] = (count + 1, now if count + 1 >= MAX_FAILS else since)
            return None
        self._fails.pop(who, None)
        expires = str(int(now) + self.ttl)
        return f"{expires}.{self._sign(expires)}"

    def valid_token(self, token: str, now: float | None = None) -> bool:
        expires, _, sig = (token or "").partition(".")
        # 11/8 무작위 시험: 비ASCII 쿠키(lf_admin=1.é)에서 compare_digest 가 TypeError → 500. 바이트끼리 비교
        if not expires.isdigit() or not hmac.compare_digest(sig.encode('utf-8', 'replace'), self._sign(expires).encode()):
            return False
        return int(expires) > (now or time.time())

    def allowed(self, cookie: str = "", api_key: str = "") -> bool:
        if not self.enabled:
            return True
        if self.api_key and api_key and hmac.compare_digest(api_key.encode(), self.api_key.encode()):
            return True
        return self.valid_token(cookie)
