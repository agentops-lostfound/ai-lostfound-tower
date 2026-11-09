"""Bounded user-turn context. No assistant claims, identity state or stored transcripts."""
import re
import unicodedata
from agents.lost_input import checked_text, text_features, ALIASES, COLORS
from agents.search_context import search_context

TOPIC_LABELS = {'consent': '본인인증', 'pickup': '수령 절차', 'masked_identity': '분실인 개인정보',
                'finder_contact': '습득자 연락처', 'site_help': '사이트 사용법',
                'flow': '분실물 확인', 'center_pickup': '본센터 받는 순서',
                'found_report': '습득 신고', 'categories': '물건 종류',
                'kiosk_places': '키오스크 위치', 'privacy_input': '개인정보 입력',
                'candidate_scope': '후보의 뜻'}


def is_referential(q):
    return bool(re.fullmatch(r'(?:(?:그럼|그러면))?(?:(?:그건|그거)(?:못하면|안되면|실패하면|어떻게)?|실패하면|안되면|어떻게해|어떻게|왜|필수야|꼭해야돼|어떡해)(?:요)?[?？.!]*', compact(q)))


def compact(text):
    return re.sub(r'\s+', '', text).lower()


def brief_reaction(question):
    """Only complete, non-actionable reactions; never absorb a new search request."""
    q = compact(unicodedata.normalize('NFKC', question))
    suffix = r'[ㅋㅎㅠㅜ\u1100-\u11ff!?？.~…]*'
    if re.fullmatch(r'(?:까비|아쉽(?:다|네|네요|군|군요)?|아깝(?:다|네|네요)?|쩝|힝|에휴|허탈하네)' + suffix, q):
        return 'disappointment'
    if re.fullmatch(unicodedata.normalize('NFKC', r'(?:ㅇㅋ|ㅇㅇ|오케이|알겠(?:어|어요|다|습니다)|그렇구나|그렇군요|넵|네|응)') + suffix, q):
        return 'acknowledgement'
    return None


def natural_question(question):
    replacements = [
        (r'사진\s*(첨부|업로드)', '사진 올리기'),
        (r'사진\s*(?:을\s*)?(?:(?:어디서|어디에|어떻게)\s*)?(?:넣|올리|올려|올릴|등록)', '사진 올리기'),
        (r'글로\s*(?:만\s*)?(?:적|작성)', '설명 입력'),
        (r'타이핑|텍스트|글로\s*(쓸|쓰|입력)|말\s*안\s*하고', '설명 입력'),
        (r'본인\s*확인', '본인인증'),
        (r'신원\s*(?:검사|확인)|신분\s*확인', '본인인증'),
        (r'내\s*정보', '내 개인정보'),
        (r'받으러\s*(가|갈)|뭘\s*챙겨|뭐\s*챙겨', '수령 준비물'),
        (r'몇\s*시.*(?:끝|마감)|언제.*(?:열어|닫아)', '운영시간'),
    ]
    result = question
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    if re.search(r'뭐부터|어디서부터|처음.*(?:왔|이용)|어떻게.*시작', result):
        result += ' 사이트 사용법'
    return result if len(result) <= 500 else question


def checked_history(history):
    if history is None:
        return []
    if not isinstance(history, list) or len(history) > 4:
        raise ValueError('이전 질문은 최대 4개의 글 목록으로 보내주세요')
    return [checked_text(q, '이전 질문', 500) for q in history]


def search_intent(question):
    q = compact(question)
    features, _ = text_features(question)
    item = features.get('category') not in (None, '확인 불가', '없음')
    direct = bool(re.search(r'찾아(?:줘|주|줄)|검색해|후보.*보여', q))
    implicit = item and bool(re.search(r'잃어버|분실했|분실한|있나요|있어|있나|있니|있습니까|어딨', q))
    # Short descriptions are useful search requests even without "찾아줘".
    terms = [term.replace(' ', '') for aliases in (*ALIASES.values(), *COLORS.values()) for term in aliases]
    terms += ['반지갑', '장지갑', '가죽', '직사각형', '원통형', '원형']
    tokens = '|'.join(re.escape(term) for term in sorted(set(terms), key=len, reverse=True))
    description = item and bool(re.fullmatch(
        r'(?:(?:' + tokens + r'|[가-힣]{1,6}색))+(?:이요|이에요|입니다|인데요|요)?[?？.!]*', q))
    return direct or implicit or description


def resolve_turn(question, history, context, guidance):
    """Resolve only an elliptical follow-up; unrelated/new questions stay independent."""
    question = natural_question(question)
    previous, inherited = None, {}
    for turn in history:
        if brief_reaction(turn):
            continue
        current = natural_question(turn)
        if previous and is_referential(current) and guidance.ask(current)['status'] == 'not_found':
            topics = [s['topic'] for s in guidance.ask(previous)['sources']]
            if len(topics) == 1 and topics[0] in TOPIC_LABELS:
                current = TOPIC_LABELS[topics[0]] + ' ' + current
        previous = current
        previous_features, _ = text_features(previous)
        attribute_turn = any(previous_features.get(k) not in (None, '확인 불가', '없음') for k in ('category', 'color'))
        if search_intent(previous) or (inherited and attribute_turn and re.search(r'(?:은|는|으로)[?？.!\s]*$', previous)):
            inherited, warnings = search_context(previous, inherited)
            if warnings:
                inherited = {}
        else:
            inherited = {}
    q = compact(question)
    features, warnings = text_features(question)
    fragment = bool(re.fullmatch(r'(?:그럼|그러면|이번엔|이번에는|그건|그거|아니)?[가-힣a-z0-9 ]{0,24}[?？.!]*', q))
    has_attribute = any(features.get(k) not in (None, '확인 불가', '없음') for k in ('category', 'color'))
    elliptical = bool(re.match(r'^(그럼|그러면|그건|그거|이번엔|이번에는)', q) or (has_attribute and re.fullmatch(r'.{1,20}(?:은|는|으로)[?？.!]*', q)))
    inherited = inherited or context
    retry_search = bool(re.fullmatch(r'(?:그럼|그러면)?(?:다시|한번더)(?:찾아줘|찾아주세요|검색해줘)[?？.!]*', q))
    fragment_search = (fragment and has_attribute) or (search_intent(question) and features.get('category') == '확인 불가') or retry_search
    if inherited.get('category') and fragment_search and not warnings:
        # A fragment such as “USB는?” continues search, but a new how-to question does not.
        if not re.search(r'어떻게|방법|절차|기간|운영|인증|수령|사진|보관|개인정보|날씨|예약', q):
            return question + ' 찾아줘', {**context, **inherited}, True
    referential = is_referential(q)
    if referential and previous and not has_attribute:
        current = guidance.ask(question)
        if current['status'] == 'not_found':
            prior = guidance.ask(previous)
            topics = [s['topic'] for s in prior['sources']]
            if len(topics) == 1 and topics[0] in TOPIC_LABELS:
                resolved = TOPIC_LABELS[topics[0]] + ' ' + question
                return resolved, context, True
    if elliptical and not search_intent(question) and guidance.ask(question)['status'] == 'not_found':
        return question, context, None
    return question, context, False
