"""LF-5 local HTTP boundaries and input normalization. Never stores question bodies."""
import asyncio
import json
import math
import re
import threading
import time
import unicodedata
from collections import deque
from urllib.parse import urlsplit
from starlette.responses import JSONResponse
from discord_ops.reporter import find_pii


def normalized_text(value):
    value = unicodedata.normalize('NFKC', value)
    value = ''.join('-' if unicodedata.category(c) == 'Pd' or c == '\u2212' else c
                    for c in value if (unicodedata.category(c) not in ('Cf', 'Cc') or c.isspace())
                    and c != '\u034f')
    return re.sub(r'[^\S\n]+', ' ', value).strip()


def has_private_pattern(value):
    # Check ordinary patterns and separators deliberately inserted between digits.
    compact = re.sub(r'(?<=\d)[\s.\-·]+(?=\d)', '', value)
    return bool(find_pii(value) or find_pii(compact)
                or re.search(r'(?<!\d)\d{16}(?!\d)', compact))


SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'",
}


class RequestPolicy:
    """Bounded, process-local sliding windows; forwarded headers are not rate-limit identities."""
    def __init__(self, per_client=30, media_per_client=6, global_limit=120,
                 max_active=4, window=60, clock=time.monotonic):
        self.per_client, self.media_per_client, self.global_limit = per_client, media_per_client, global_limit
        self.max_active, self.window, self.clock = max_active, window, clock
        self._lock, self._clients, self._global = threading.Lock(), {}, deque()
        self._active = 0

    def begin(self, client, media):
        with self._lock:
            now = self.clock()
            for key, events in list(self._clients.items()):
                while events and events[0] <= now - self.window:
                    events.popleft()
                if not events:
                    del self._clients[key]
            while self._global and self._global[0] <= now - self.window:
                self._global.popleft()
            key = (client, media)
            limit = self.media_per_client if media else self.per_client
            if len(self._clients.get(key, ())) >= limit or len(self._global) >= self.global_limit:
                return 'rate'
            if self._active >= self.max_active:
                return 'busy'
            # New clients cannot grow the dictionary without bound, even with spoofed addresses.
            if key not in self._clients and len(self._clients) >= 256:
                return 'rate'
            self._clients.setdefault(key, deque()).append(now)
            self._global.append(now)
            self._active += 1
            return None

    def end(self):
        with self._lock:
            self._active -= 1


class LocalRequestGuard:
    """Reject cross-site/local-host rebinding and oversized bodies before JSON parsing."""
    def __init__(self, app, policy=None, body_timeout=15):
        self.app, self.policy, self.body_timeout = app, policy or RequestPolicy(), body_timeout

    @staticmethod
    def _authority(value):
        try:
            if not re.fullmatch(r'(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?', value, re.IGNORECASE):
                return None
            parsed = urlsplit('http://' + value)
            if (parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username is not None
                    or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
                    or parsed.port is not None and not 1 <= parsed.port <= 65535):
                return None
            return parsed
        except (ValueError, TypeError):
            return None

    @staticmethod
    async def _deny(scope, receive, send, status, message):
        headers = {**SECURITY_HEADERS}
        if status == 429:
            headers['Retry-After'] = '60'
        await JSONResponse({'detail': message}, status_code=status, headers=headers)(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {}
        for key, value in scope.get('headers', []):
            key = key.decode('latin1').lower()
            if key in headers and key in ('host', 'origin', 'authorization', 'content-length', 'content-type'):
                return await self._deny(scope, receive, send, 400, '중복된 요청 헤더입니다')
            headers[key] = value.decode('latin1')
        authority = self._authority(headers.get('host', ''))
        if authority is None:
            return await self._deny(scope, receive, send, 400, '허용되지 않은 접속 주소입니다')
        origin = headers.get('origin')
        if origin is not None:
            try:
                parsed = urlsplit(origin)
                origin_ok = (parsed.scheme == scope.get('scheme', 'http')
                    and parsed.hostname == authority.hostname
                    and (parsed.port or (443 if parsed.scheme == 'https' else 80)) ==
                        (authority.port or (443 if scope.get('scheme') == 'https' else 80))
                    and parsed.username is None and parsed.password is None
                    and not parsed.path and not parsed.query and not parsed.fragment)
            except ValueError:
                origin_ok = False
            if not origin_ok:
                return await self._deny(scope, receive, send, 403, '외부 사이트에서는 이 로컬 API를 호출할 수 없습니다')
        if headers.get('sec-fetch-site') == 'cross-site':
            return await self._deny(scope, receive, send, 403, '외부 사이트 요청을 허용하지 않습니다')
        if len(headers.get('authorization', '')) > 4096:
            return await self._deny(scope, receive, send, 400, '인증 정보 형식이 올바르지 않습니다')

        async def secured_send(message):
            if message['type'] == 'http.response.start':
                extra = {k.lower().encode(): v.encode() for k, v in SECURITY_HEADERS.items()}
                message['headers'] = [(k, v) for k, v in message.get('headers', []) if k.lower() not in extra] + list(extra.items())
            await send(message)

        if scope['method'] != 'POST':
            return await self.app(scope, receive, secured_send)
        path = scope.get('path', '')
        limit = 7_100_000 if path == '/descriptions/photo' else 2_600_000 if path in (
            '/descriptions/audio', '/chat/transcriptions') else 16_384 if path.startswith('/descriptions/') else 8192
        if headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
            return await self._deny(scope, receive, send, 415, 'JSON 형식의 요청만 지원합니다')
        declared = headers.get('content-length')
        try:
            if declared is not None and (not declared.isdecimal() or int(declared) < 0):
                raise ValueError()
            declared = int(declared) if declared is not None else None
        except ValueError:
            return await self._deny(scope, receive, send, 400, '요청 크기 정보가 올바르지 않습니다')
        if declared is not None and declared > limit:
            return await self._deny(scope, receive, send, 413, '요청 크기가 제한을 초과했습니다')
        media = path in ('/descriptions/photo', '/descriptions/audio', '/chat/transcriptions')
        denied = self.policy.begin((scope.get('client') or ('unknown',))[0], media)
        if denied:
            return await self._deny(scope, receive, send, 429 if denied == 'rate' else 503,
                                    '요청이 많습니다. 잠시 후 다시 시도해주세요')
        try:
            chunks, size, started = [], 0, time.monotonic()
            while True:
                remaining = self.body_timeout - (time.monotonic() - started)
                if remaining <= 0:
                    return await self._deny(scope, receive, send, 408, '요청 수신 시간이 초과됐습니다')
                try:
                    message = await asyncio.wait_for(receive(), timeout=remaining)
                except TimeoutError:
                    return await self._deny(scope, receive, send, 408, '요청 수신 시간이 초과됐습니다')
                if message['type'] == 'http.disconnect':
                    return
                part = message.get('body', b'')
                size += len(part)
                if size > limit:
                    return await self._deny(scope, receive, send, 413, '요청 크기가 제한을 초과했습니다')
                chunks.append(part)
                if not message.get('more_body', False):
                    break
            if declared is not None and size != declared:
                return await self._deny(scope, receive, send, 400, '요청 크기 정보가 일치하지 않습니다')
            body = b''.join(chunks)
            chunks.clear()
            try:
                def unique_object(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError('Duplicate key')
                        result[key] = value
                    return result
                value = json.loads(body, object_pairs_hook=unique_object)
                if not isinstance(value, dict):
                    raise ValueError('Object required')
                stack, nodes = [(value, 0)], 0
                while stack:
                    item, depth = stack.pop()
                    nodes += 1
                    if depth > 32 or nodes > 2048 or isinstance(item, float) and not math.isfinite(item):
                        raise ValueError('JSON complexity')
                    if isinstance(item, (dict, list)):
                        if len(item) > 2048:
                            raise ValueError('JSON complexity')
                        stack.extend((v, depth + 1) for v in (item.values() if isinstance(item, dict) else item))
            except (ValueError, UnicodeError, RecursionError):
                return await self._deny(scope, receive, send, 422, 'JSON 입력 형식이나 중첩 구조가 올바르지 않습니다')
            del value, item, stack
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                return await receive()
            await self.app(scope, replay, secured_send)
        finally:
            self.policy.end()
