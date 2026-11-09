"""Reduce bounded user turns into search corrections; no negative-color SQL or feature claims."""
import re
from agents.lost_input import text_features, COLORS, ALIASES, location
from agents.chat_conversation import compact, search_intent, brief_reaction
from agents.chat_communication import scope_violation

NEGATIVE = r'(?:아니|아님|아닌|아닙|말고|제외)'
DETAIL = r'키링|열쇠고리|스티커|케이스|스트랩|로고|흠집|스크래치|찍힘|문양|무늬|재질|가죽'
NEW_TOPIC = r'주웠|주운|습득|신고|운영|수령|인증|동의|개인정보|보관기간|사진.*(?:올|첨부)|사용법|이용법'
HELP_TOPIC = r'방법|절차|어떻게|뜻|의미|확정|어떤물건'


def color_statement(question):
    q = compact(question)
    lookup = {term: color for color, terms in COLORS.items() for term in terms}
    pattern = '|'.join(re.escape(term) for term in sorted(lookup, key=len, reverse=True))
    positive, negative = set(), set()
    for match in re.finditer(pattern, q):
        if match.group() == '은색' and match.start() and re.match(r'[가-힣]', q[match.start()-1]):
            continue
        tail = q[match.end():]
        target = negative if re.match(r'^(?:색|거|것)?(?:은|는|이|가)?'+NEGATIVE, tail) else positive
        target.add(lookup[match.group()])
    unclear = len(positive) > 1 or bool(positive & negative)
    # Complex or double negation is never guessed.
    if (positive or negative) and re.search(NEGATIVE, q) and not negative:
        unclear = True
    if len(re.findall(NEGATIVE, q)) > 1:
        unclear = True
    return positive, negative, unclear


def _category(question, negative_colors):
    features, _ = text_features(question)
    category = features.get('category')
    if category != '확인 불가':
        return category
    if negative_colors:
        # The general form parser treats negation conservatively across all fields.
        # Recover a single explicitly positive item only when color is being negated.
        q = compact(question)
        matches = {name for name, aliases in ALIASES.items() if any(term.replace(' ', '') in q for term in aliases)}
        if len(matches) == 1:
            name = next(iter(matches))
            if not any(re.search(re.escape(term.replace(' ', ''))+r'(?:은|는|이|가)?'+NEGATIVE, q) for term in ALIASES[name]):
                return name
    return None


def color_issue(question, positive, negative, unclear):
    _, warnings = text_features(question)
    # Keep unrecognized colors and shades distinct from color negation.
    if any('색상을 검색 조건으로 확정' in warning for warning in warnings):
        return 'unsupported'
    if re.fullmatch(r'(?:라벤더|민트|베이지|아이보리|카키|무지개|투명|purple|lavender|mint|beige)(?:색|빛|컬러)?(?:이야|임|이에요)?[!?？.]*', compact(question)):
        return 'unsupported'
    if re.search(r'(?:연|진한|밝은|어두운)(?:회색|파랑|파란|초록|녹색|분홍|갈색|남색)', compact(question)):
        return 'unsupported'
    if len(positive) > 1:
        return 'multiple'
    if unclear:
        return 'ambiguous'
    if negative and not positive:
        return 'negation'
    return None


def prepare_search_turn(guidance, question, history, context):
    state, pending = dict(context), None

    def apply(turn):
        nonlocal state, pending
        q = compact(turn)
        if brief_reaction(turn):
            return
        if re.search(NEW_TOPIC, q) or (re.search(HELP_TOPIC, q) and not re.search(DETAIL, q)) or scope_violation(turn):
            state, pending = {}, None
            return
        mentioned = {name for name, aliases in ALIASES.items() if any(term.replace(' ', '') in q for term in aliases)}
        if len(mentioned) > 1:
            state, pending = {}, None
            return
        positive, negative, unclear = color_statement(turn)
        issue = color_issue(turn, positive, negative, unclear)
        category = _category(turn, negative)
        detail = bool(re.search(DETAIL, q))
        if category:
            if state.get('category') not in (None, category):
                state, pending = {}, None
            state['category'] = category
        if state.get('category'):
            state.update(location({}, re.sub(r'(\d{1,2}호선)\s*', r'\1 ', turn)))
        if detail:
            if negative:
                state.pop('color', None)
                pending = 'negation'
            return  # Accessory colors are never automatically assigned to the item.
        if issue:
            state.pop('color', None)
            pending = issue
        if len(positive) == 1 and not issue:
            state['color'] = next(iter(positive))
            pending = None
        if not (category or positive or negative or detail or issue or search_intent(turn)):
            state, pending = {}, None

    for turn in history:
        apply(turn)
    q = compact(question)
    if re.search(NEW_TOPIC, q) or (re.search(HELP_TOPIC, q) and not re.search(DETAIL, q)):
        return None
    positive, negative, unclear = color_statement(question)
    issue = color_issue(question, positive, negative, unclear)
    category = _category(question, negative)
    detail = bool(re.search(DETAIL, q))
    prior_category = state.get('category')
    apply(question)
    known = state.get('category')
    display = '휴대폰' if known == '모형폰' else known

    def response(answer, needs_details=True):
        status = 'search_needs_details' if pending == 'unsupported' else 'clarification_needed' if needs_details else 'answered'
        return {'response': {**guidance._response(status, answer, []),
            'agent': 'guidance', 'generation_used': False, 'generation_status': 'not_needed',
            'context_used': bool(history or context), 'color_confirmation_required': bool(pending),
            'color_issue': pending, 'candidates': [], 'reservation_created': False,
            'feature_search_supported': False, 'understood_category': known}}

    categories = {name for name, aliases in ALIASES.items() if any(term.replace(' ', '') in q for term in aliases)}
    if len(categories) > 1:
        known, pending = None, None
        result = response('여러 물건을 말씀하셨군요. 현재 한 번에 한 품목씩 검색할 수 있어요. 먼저 찾을 물건 하나를 골라주세요.')
        result['response']['status'] = 'search_needs_details'
        return result

    if detail:
        if not known:
            return response('물건의 추가 특징을 말씀하셨군요. 어떤 물건에 달린 특징인지 품목부터 알려주세요. 현재 키링·스티커·케이스 같은 상세 특징은 자동 검색에 반영하지 못합니다.')
        answer = f'{display}의 추가 특징을 말씀하신 것으로 이해했어요. 현재 키링·스티커·케이스 같은 상세 특징은 자동 검색에 반영하지 못해, 이 특징으로 일치한다고 판단하거나 다시 검색하지 않았어요.'
        if pending == 'negation':
            answer += ' 앞서 부정하신 색상을 다시 적용하지 않겠습니다. 실제 물건 색상을 알려주세요.'
        elif pending:
            answer += ' 앞서 말씀하신 색상 조건은 아직 검색에 반영하지 않았어요. 한 가지 표준 색상으로 조회할지 확인해주세요.'
        elif positive:
            answer += ' 부속품의 색상을 물건 자체 색상으로 적용하지 않았어요. 물건 자체 색상은 별도로 확인해주세요.'
        return response(answer, pending)
    if issue == 'unsupported' and pending:
        return response((f'{display}의 ' if display else '')+'색상 설명으로 이해했어요. 다만 이 색상·색조는 현재 검색 색상 목록에 없어 조회하지 않았습니다. 다른 색으로 임의 변환하지 않겠습니다. 원하시면 검정·흰색·회색·빨강·파랑·남색·초록·노랑·갈색·분홍 중 대표 색상 하나로 검색할지 알려주세요.')
    if issue == 'multiple' and pending:
        return response((f'{display}에 ' if display else '')+'여러 색상이 있다는 뜻으로 이해했어요. 현재 복수 색상을 함께 반영하는 검색은 지원하지 않아 조회하지 않았습니다. 어느 한 색으로 단정하지 않겠습니다. 원하시면 대표 색상 하나로 조회할지 알려주세요.')
    if (negative or unclear) and pending:
        prefix = f'{display}의 ' if display else ''
        if pending == 'ambiguous':
            return response(prefix+'색상 표현을 정확히 구분하기 어려워 조회하지 않았어요. 적용할 색상 하나를 분명하게 알려주세요.')
        return response(prefix+'색상을 정정하신 것으로 이해했어요. 부정한 색상으로 후보를 맞다고 판단하거나 다른 색상을 추측해 검색하지 않았습니다. 실제 색상을 알려주세요.')
    if pending and (search_intent(question) or re.search(r'다시.*찾|다시.*검색', q)):
        if pending != 'negation':
            return response('앞서 말씀하신 복수 색상 또는 미지원 색상은 아직 검색에 반영하지 못했어요. 한 가지 표준 색상으로 조회할지 확인해주셔야 다시 검색할 수 있습니다.')
        return response('아직 실제 색상을 확인하지 못해 다시 조회하지 않았어요. 부정한 색상을 되살리지 않겠습니다. 찾는 물건의 실제 색상을 알려주세요.')
    # Complete corrections use validated canonical attributes, not a model-written query.
    if known and positive and not issue and (prior_category or negative):
        state.update(location({}, re.sub(r'(\d{1,2}호선)\s*', r'\1 ', question)))
        return {'question': known+' '+state['color']+' 찾아줘', 'context': state}
    if known and re.search(r'다시.*(?:찾|검색)|한번더.*(?:찾|검색)', q):
        return {'question': known+' '+state.get('color', '')+' 찾아줘', 'context': state}
    if known and category and re.search(r'부터|먼저', q) and not pending:
        return {'question': known+' '+state.get('color', '')+' 찾아줘', 'context': state}
    return None
