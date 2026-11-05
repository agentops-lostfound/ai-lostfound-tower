"""Short-lived, owner-bound server references. Raw item IDs never enter public cards."""
import hashlib
import hmac
import secrets
import threading
import time


class CandidateRegistry:
    def __init__(self, ttl=600, max_entries=256, max_per_owner=8, clock=time.monotonic):
        self.ttl, self.max_entries, self.max_per_owner, self.clock = ttl, max_entries, max_per_owner, clock
        self._salt, self._entries, self._lock = secrets.token_bytes(32), {}, threading.Lock()

    def _owner(self, access_token):
        return hmac.new(self._salt, (access_token or 'local-demo').encode(), hashlib.sha256).digest()

    def issue(self, item_ids, access_token):
        owner, now, reference = self._owner(access_token), self.clock(), secrets.token_urlsafe(24)
        with self._lock:
            self._entries = {k: v for k, v in self._entries.items() if now - v[0] < self.ttl}
            mine = [key for key, entry in self._entries.items() if hmac.compare_digest(entry[1], owner)]
            if len(mine) >= self.max_per_owner:
                del self._entries[mine[0]]
            if len(self._entries) >= self.max_entries:
                raise RuntimeError('검색 요청이 많습니다. 잠시 후 다시 시도해주세요')
            self._entries[reference] = (now, owner, tuple(item_ids[:3]))
        return reference

    def resolve(self, reference, candidate_no, access_token):
        if not isinstance(reference, str) or len(reference) > 128 or type(candidate_no) is not int:
            raise ValueError('유효한 후보 선택이 필요합니다')
        with self._lock:
            entry = self._entries.get(reference)
            if (not entry or self.clock() - entry[0] >= self.ttl
                    or not hmac.compare_digest(entry[1], self._owner(access_token))
                    or not 1 <= candidate_no <= len(entry[2])):
                raise ValueError('후보를 확인할 수 없습니다. 다시 검색해주세요')
            return entry[2][candidate_no - 1]
