"""일반 사용자 인증 연결. 서버 검증 결과만 받고 공개 로그인/토큰 발급은 제공하지 않는다."""
from dataclasses import dataclass, field
import math
import time

from agents.chat_operations import Owner, binding_digest


PERMISSIONS = frozenset(('chat:use', 'chat:search', 'chat:operations:read'))


class FindAuthenticationRequired(PermissionError):
    pass


class FindAuthenticationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, repr=False)
class FindSession:
    owner: Owner = field(repr=False)
    expires_at: float
    id_verified: bool
    consented: bool
    revoked: bool
    permissions: frozenset[str]


class FindSessionAuth:
    """lookup(token_hash) → FindSession. 매 요청 검증하며 성공 결과를 캐시하지 않는다.

    lookup은 권한 있는 서버/DB 어댑터여야 한다. 클라이언트 JSON을 변환해 주입하면 안 된다.
    """

    def __init__(self, lookup, binding_key: bytes, clock=time.time):
        binding_digest(binding_key, 'validate-key', None)
        if not callable(lookup):
            raise ValueError('a trusted session lookup is required')
        self._lookup, self._key, self._clock = lookup, binding_key, clock

    def __repr__(self):
        return 'FindSessionAuth(credentials=***)'

    def require(self, token, permission='chat:use') -> FindSession:
        if permission not in PERMISSIONS:
            raise ValueError('unknown session permission')
        if not isinstance(token, str) or not 1 <= len(token) <= 4096 or any(c.isspace() for c in token):
            raise FindAuthenticationRequired('본인인증·필수 동의가 필요합니다')
        try:
            session = self._lookup(binding_digest(self._key, 'find-token-v1', token))
        except Exception:
            raise FindAuthenticationUnavailable('인증 세션을 확인하지 못했습니다') from None
        try:
            live = (type(session) is FindSession and type(session.expires_at) in (int, float)
                    and math.isfinite(session.expires_at) and session.expires_at > self._clock())
        except (TypeError, ValueError, OverflowError):
            live = False
        valid = (live and isinstance(session.owner, Owner)
                 and session.id_verified is True and session.consented is True and session.revoked is False
                 and type(session.permissions) is frozenset and session.permissions <= PERMISSIONS
                 and permission in session.permissions)
        if not valid:
            raise FindAuthenticationRequired('본인인증·필수 동의가 필요합니다')
        return session

    def authorize(self, token):
        try:
            self.require(token, 'chat:search')
            return True
        except (FindAuthenticationRequired, FindAuthenticationUnavailable):
            return False

    def conversation_id(self, session: FindSession, browser_session_id):
        """화면 대화 번호를 인증 소유자에 묶는다. 원문 사용자 ID/토큰을 그래프에 넣지 않는다."""
        return binding_digest(self._key, 'find-conversation-v1',
                              [session.owner.subject, session.owner.auth_session, browser_session_id or 'default'])

    def staff_conversation_id(self, browser_session_id):
        return binding_digest(self._key, 'staff-conversation-v1', browser_session_id or 'default')
