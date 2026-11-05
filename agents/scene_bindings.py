"""Internal inspection manifest proposal. Not a team API or identity authority."""
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agents.contracts import ITEM_ID_RE
from agents.vision_adapter import adapt_report


def utc_now():
    return datetime.now(timezone.utc)


def moment(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('촬영 시각을 확인해주세요') from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('시간대가 있는 촬영 시각이 필요합니다')
    return value.astimezone(timezone.utc)


def encode_scene(report):
    try:
        if not isinstance(report, dict):
            raise ValueError()
        raw = json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(raw.encode()) > 2_000_000:
            raise ValueError()
        return raw
    except (TypeError, ValueError, RecursionError, RuntimeError):
        raise ValueError('검사 장면 형식이나 크기를 확인해주세요') from None


def scene_digest(report):
    """Producer-side helper; never writes or uploads the report."""
    return hashlib.sha256(encode_scene(report).encode()).hexdigest()


@dataclass(frozen=True, repr=False)
class BoundScene:
    _capture_id: str
    _digest: str
    _captured: datetime
    _raw: str = field(repr=False)
    _items: tuple = field(repr=False)
    _max_age: float
    _clock: object = field(repr=False)

    def __repr__(self):
        return f'BoundScene(objects={len(self._items)}, inspection_only=True)'

    def _fresh(self):
        age = (moment(self._clock()) - self._captured).total_seconds()
        if not 0 <= age <= self._max_age:
            raise ValueError('촬영 결과가 오래됐거나 시각을 확인할 수 없습니다')

    def snapshot(self):
        self._fresh()
        return json.loads(self._raw)

    def resolve_candidates(self, numbers, *, capture_id, report_sha256, inventory_check):
        """Trusted server use only. Caller must separately authorize the claimant."""
        self._fresh()
        if capture_id != self._capture_id or report_sha256 != self._digest:
            raise ValueError('다른 촬영 결과의 후보는 사용할 수 없습니다')
        if (not isinstance(numbers, list) or len(numbers) > 3
                or any(type(n) is not int or not 1 <= n <= len(self._items) for n in numbers)
                or len(set(numbers)) != len(numbers) or not callable(inventory_check)):
            raise ValueError('유효한 후보 번호와 재고 확인이 필요합니다')
        items = tuple(self._items[n-1] for n in numbers)
        for item in items:
            try:
                valid = inventory_check(item) is True
            except Exception:
                raise ValueError('재고 상태를 확인할 수 없습니다') from None
            if not valid:
                raise ValueError('후보 물건의 재고 상태가 변경됐습니다')
        self._fresh()
        return items


def bind_scene(report, manifest, *, clock=utc_now, max_age=300):
    """Validate an explicit server-provided mapping; never infer IDs from order.

    Manifest fields are a local inspection proposal awaiting team agreement.
    Receipt ID format + a matching hash do not establish real object ownership.
    """
    if type(max_age) not in (int, float) or not math.isfinite(max_age) or not 0 < max_age <= 3600 or not callable(clock):
        raise ValueError('검사 유효 시간을 확인해주세요')
    if not isinstance(manifest, dict) or set(manifest) != {'capture_id', 'captured_at', 'report_sha256', 'bindings'}:
        raise ValueError('촬영 연결표 형식이 필요합니다')
    capture = manifest['capture_id']
    if not isinstance(capture, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', capture):
        raise ValueError('촬영 세션 번호를 확인해주세요')
    raw = encode_scene(report)
    snapshot = json.loads(raw)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    if manifest['report_sha256'] != digest:
        raise ValueError('촬영 결과와 연결표가 다릅니다')
    captured = moment(manifest['captured_at'])
    if 'captured_at' in snapshot and moment(snapshot['captured_at']) != captured:
        raise ValueError('촬영 시각과 연결표가 다릅니다')
    objects = snapshot.get('objects')
    sequence = snapshot.get('sequence')
    if (not isinstance(objects, list) or not 1 <= len(objects) <= 50
            or not isinstance(sequence, dict) or sequence.get('status') != 'complete'):
        raise ValueError('완료된 촬영 장면이 필요합니다')
    if any(not isinstance(o, dict) or not isinstance(o.get('qwen'), dict)
           or o['qwen'].get('status') != 'ok' or not isinstance(o['qwen'].get('features'), dict) for o in objects):
        raise ValueError('전체 객체의 검출·특징을 확인해주세요')
    try:
        detections = adapt_report(snapshot)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise ValueError('전체 객체의 검출·특징을 확인해주세요') from None
    if len(detections) != len(objects):
        raise ValueError('전체 객체의 검출·특징을 확인해주세요')
    pairs = manifest['bindings']
    if not isinstance(pairs, list) or len(pairs) != len(objects):
        raise ValueError('모든 객체의 접수 번호 연결이 필요합니다')
    mapping = {}
    for pair in pairs:
        if (not isinstance(pair, dict) or set(pair) != {'vision_id', 'item_id'}
                or type(pair['vision_id']) is not int or pair['vision_id'] in mapping
                or not isinstance(pair['item_id'], str) or not ITEM_ID_RE.fullmatch(pair['item_id'])):
            raise ValueError('객체·접수 번호 연결을 확인해주세요')
        mapping[pair['vision_id']] = pair['item_id']
    if set(mapping) != {o['id'] for o in objects} or len(set(mapping.values())) != len(objects):
        raise ValueError('객체와 접수 번호는 중복 없이 일대일이어야 합니다')
    bound = BoundScene(capture, digest, captured, raw, tuple(mapping[o['id']] for o in objects), float(max_age), clock)
    bound._fresh()
    return bound
