"""Explicit, public search constraints; never an identity or consent assertion."""
import re
from agents.contracts import CATEGORIES, COLORS, UNKNOWN
from agents.lost_input import checked_text, location, text_features

FIELDS = {'category', 'color', 'lost_line', 'lost_station', 'lost_date'}


def constraint_update(question):
    """명시적으로 불명/제한 해제를 말한 검색 칸만 제외한다."""
    from agents.chat_turn import attribute_semantics, declined_change
    question = attribute_semantics(question)
    labels = {'색상':'color','색':'color','분실날짜':'lost_date','날짜':'lost_date','언제':'lost_date',
              '호선':'lost_line','역':'lost_station','장소':'lost_station'}
    label = re.compile('|'.join(labels))
    unknown = re.compile(r'모르|모름|몰라|기억(?:이)?안|확실하지않|확신.{0,4}(?:없|못)|상관없|제한없|제한없이|제한을없|해제|없애|제거|빼(?:줘|주|줄|고)|지워|풀어|구분하지말|아무거나|무관')
    cleared, kept, cleaned = set(), set(), []
    for part in re.split(r'[,.;!?？]|그리고|하지만', question):
        hits = list(label.finditer(part))
        ranges = []
        for i, hit in enumerate(hits):
            end = hits[i+1].start() if i+1 < len(hits) else len(part)
            segment = re.sub(r'\s+', '', part[hit.end():end])
            keep = (declined_change(segment) or re.search(r'유지|그대로|건드리지|(?:모르|모른|기억).{0,20}(?:뜻.{0,3}아니|한적없|말한적없)', segment))
            if keep:
                kept.add(labels[hit.group()])
                ranges.append((hit.start(), end))
            elif unknown.search(segment):
                cleared.add(labels[hit.group()])
                ranges.append((hit.start(), end))
        for start, end in reversed(ranges):
            part = part[:start]+' '+part[end:]
        cleaned.append(part)
    return ' '.join(cleaned).strip(), cleared, kept


def constraint_text(question):
    text, cleared, _ = constraint_update(question)
    return text, cleared


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
    physical_text, cleared = constraint_text(question)
    for key in cleared:
        result.pop(key, None)
    # A new explicit question overrides the reviewed form. Ambiguity is never silently ignored.
    features, warnings = text_features(physical_text) if physical_text else ({'category': UNKNOWN}, [])
    if result.get('category') and features.get('category') not in (None, UNKNOWN, result['category']):
        result = {}
    result.update({k: features[k] for k in ('category', 'color') if features.get(k) not in (None, UNKNOWN)})
    result.update(location({}, re.sub(r'(\d{1,2}호선)\s*', r'\1 ', physical_text)))
    for key in cleared:
        result.pop(key, None)
    result = checked_context(result)
    result.setdefault('category', UNKNOWN)
    return result, warnings
