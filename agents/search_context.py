"""Explicit, public search constraints; never an identity or consent assertion."""
import re
from agents.contracts import CATEGORIES, COLORS, UNKNOWN
from agents.lost_input import checked_text, location, text_features

FIELDS = {'category', 'color', 'lost_line', 'lost_station', 'lost_date'}


def normalize_station(value):
    value = checked_text(value, '역', 32).removesuffix('역').strip()
    if not value:
        raise ValueError('역 이름을 입력해주세요')
    return value


def checked_context(context=None):
    if context is not None and (not isinstance(context, dict) or set(context) - FIELDS):
        raise ValueError('검색 조건에는 품목·색상·분실 날짜·호선·역만 사용할 수 있습니다')
    context = context or {}
    result = {key: checked_text(value, '검색 조건', 32) for key, value in context.items() if value is not None}
    if result.get('category') not in (None, *CATEGORIES):
        raise ValueError('검색 품목을 확인해주세요')
    if result.get('color') not in (None, *COLORS):
        raise ValueError('검색 색상을 확인해주세요')
    metadata = location({k: result[k] for k in ('lost_date', 'lost_line', 'lost_station') if k in result})
    result.update(metadata)
    if result.get('lost_line') and not re.fullmatch(r'[1-9][0-9]?호선', result['lost_line']):
        raise ValueError('호선은 1호선처럼 입력해주세요')
    if result.get('lost_station'):
        result['lost_station'] = normalize_station(result['lost_station'])
    return result


def search_context(question, context=None):
    result = checked_context(context)
    # A new explicit question overrides the reviewed form. Ambiguity is never silently ignored.
    features, warnings = text_features(question)
    if result.get('category') and features.get('category') not in (None, UNKNOWN, result['category']):
        result = {}
    result.update({k: features[k] for k in ('category', 'color') if features.get(k) not in (None, UNKNOWN)})
    result.update(location({}, re.sub(r'(\d{1,2}호선)\s*', r'\1 ', question)))
    result = checked_context(result)
    result.setdefault('category', UNKNOWN)
    return result, warnings
