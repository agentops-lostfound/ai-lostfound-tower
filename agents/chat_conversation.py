"""Bounded user-turn context. No assistant claims, identity state or stored transcripts."""
import re
from agents.lost_input import checked_text, text_features
from agents.search_context import search_context

TOPIC_LABELS = {'finder_privacy': '습득자 연락처 공개 여부', 'kiosk_camera': '키오스크 카메라 고장', 'chat_intake': '챗봇으로 접수하기',   # 11/9 버튼에 영어 주제 이름이 나가던 것
                'consent': '본인인증', 'pickup': '수령 절차', 'masked_identity': '분실인 개인정보',
                'finder_contact': '습득자 연락처', 'site_help': '사이트 사용법',
                'flow': '분실물 확인', 'center_pickup': '본센터 받는 순서',
                'found_report': '습득 신고', 'categories': '물건 종류',
                'kiosk_places': '키오스크 위치', 'privacy_input': '개인정보 입력',
                'candidate_scope': '후보의 뜻',
                # 11/6 시연 운영 기준 주제 — 이어 묻기("그건?")가 같은 주제로 이어지게, 각 이름은 agents/guidance.py 감지 규칙에 걸리는 말
                'hours': '운영시간', 'retention': '보관 기간', 'proxy_pickup': '대리수령', 'delivery': '택배 수령',
                'fee': '수령 비용', 'id_document': '신분증 없을 때', 'reservation_change': '예약 취소',
                'center_contact': '센터 주소', 'privacy_policy': '개인정보처리 방침',
                # 11/6 자동 촬영·도착 시간
                'placement_guide': '물건 놓는 법', 'arrival': '본센터 도착 언제'}


def is_referential(q):
    # 11/9 채점표: "그 다음엔 어디로 가요?"(보관 기간 뒤), "그 전에 못 가면요?" — 앞 주제를 이어 묻는 말
    c = compact(q)
    return bool(re.fullmatch(r'(?:(?:그럼|그러면))?(?:그건|그거|실패하면|안되면|어떻게해|어떻게|왜|필수야|꼭해야돼|어떡해)(?:요)?[?？.!]*', c)
                or re.match(r'(?:그럼|그러면)?(?:그다음|그다음엔|그다음에는|그후|그후엔|그뒤|그뒤엔|그전에|그전엔|그때까지|그안에)', c))


def compact(text):
    return re.sub(r'\s+', '', text).lower()


def natural_question(question):
    replacements = [
        (r'사진\s*(첨부|업로드)', '사진 올리기'),
        (r'사진\s*(?:을\s*)?(?:(?:어디서|어디에|어떻게)\s*)?(?:넣|올리|올려|올릴|등록)', '사진 올리기'),
        (r'글로\s*(?:만\s*)?(?:적|작성)', '설명 입력'),
        (r'타이핑|텍스트|글로\s*(쓸|쓰|입력)|말\s*안\s*하고', '설명 입력'),
        (r'본인\s*확인', '본인인증'),
        (r'내\s*정보', '내 개인정보'),
        (r'받으러\s*(가|갈)|뭘\s*챙겨|뭐\s*챙겨', '수령 준비물'),
        (r'몇\s*시.*(?:끝|마감)|언제.*(?:열어|닫아)', '운영시간'),
    ]
    result = question
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    if re.search(r'뭐부터|어디서부터|처음.*(?:왔|이용)|어떻게.*시작', result) and not re.fullmatch(r'\s*(?:여기\s*)?처음\s*왔(?:어요|어|습니다|네요)[\s!.~ㅎ]*', result):
        result += ' 사이트 사용법'
    return result if len(result) <= 500 else question


def checked_history(history):
    """이전 대화 → 질문 글 목록(이어받기 판단용). 항목은 "질문" 또는 {"q": 질문, "a": 챗봇 답}(11/7 대화 기억)"""
    if history is None:
        return []
    if not isinstance(history, list) or len(history) > 4:
        raise ValueError('이전 질문은 최대 4개의 글 목록으로 보내주세요')
    return [checked_text(h.get('q') if isinstance(h, dict) else h, '이전 질문', 500) for h in history]


def checked_turns(history):
    """이전 대화 → 모델에 넘길 [{question, answer}] (답이 있는 항목만). 답은 300자까지, 개인정보 모양이면 답을 비운다.
    서버는 저장하지 않는다(브라우저가 매번 보냄) — 여러 사람 대화가 섞이지 않게"""
    from agents.support_security import has_private_pattern
    out = []
    for h in history or []:
        if isinstance(h, dict) and isinstance(h.get('a'), str):
            q = checked_text(h.get('q'), '이전 질문', 500)
            a = h['a'].strip()[:300]
            out.append({'question': q, 'answer': '' if has_private_pattern(a) else a})
    return out


SPLIT_RE = re.compile(r'이랑|랑|하고|그리고|인지|아니면|또는|혹은|[,，/]')


def split_targets(question):
    """11/9 채점표: "파란 폰이랑 흰 보조배터리", "아마 갈색, 아니면 검정" — 물건(품목·색) 여러 개를 나눠 [(품목, 색|None)].
    둘 이상일 때만 돌려줌(하나면 []). 품목이 빠진 조각은 문장 전체에 품목이 하나뿐일 때만 그 품목으로 채움"""
    if not isinstance(question, str) or not question.strip():
        return []
    from agents.lost_input import ALIASES
    from agents.contracts import mentions_phone
    text = question.lower()
    cats = {c for c, terms in ALIASES.items() if c != '모형폰' and any(t in text for t in terms)} | ({'모형폰'} if mentions_phone(text) else set())
    out = []
    for seg in SPLIT_RE.split(question):
        if not seg.strip():
            continue
        try:
            f, _ = text_features(seg)
        except ValueError:
            continue
        cat = f.get('category') if f.get('category') not in (None, '확인 불가', '없음') else None
        col = f.get('color')
        if not cat and col and len(cats) == 1:
            cat = next(iter(cats))
        if cat and (cat, col) not in out:
            out.append((cat, col))
    if len({c for c, _ in out}) == 1 and any(col is None for _, col in out):
        out = [x for x in out if x[1] is not None]          # "지갑 … 갈색, 검정" → 색 있는 조각만
    return out if len(out) >= 2 else []


def search_intent(question):
    q = compact(question)
    features, _ = text_features(question)
    item = features.get('category') not in (None, '확인 불가', '없음') or bool(split_targets(question))
    direct = bool(re.search(r'찾아(?:줘|주|줄|봐)|찾고|검색해|후보.*보여', q))
    # 11/9 '지갑 찾아요'도 검색 — 단 "어떻게 찾아요?", "찾는 거 웹으로도 돼요?" 같은 방법 질문은 아님
    direct = direct or bool(re.search(r'찾아(?:요|용)|찾는(?:데|중)|찾습니다', q) and not re.search(r'어떻게|어디서|어디|방법|웹|챗봇|키오스크|되나|돼요|되요', q))
    # 11/9 채점표: "지갑 안에 신분증이 다 들어 있어서 없는데요" 는 신분증 이야기 — 물건 검색 아님
    implicit = item and not re.search(r'신분증|면허증|여권', q) and bool(re.search(r'잃어버|잃었|분실했|분실한|두고\s?내|놓고\s?내|두고\s?온|있나요|있어|있나|있니|있습니까|있는지|있을까|있으면|어딨|들어왔|보관\s?중|보관하고', q))
    return direct or implicit


# 이어서 찾기로 바꾸면 안 되는 말(절차 질문·습득 신고). 11/7 '주웠·맡겨·어디' 추가 — "지갑 주웠는데 어디에 맡겨요?"가 검색으로 바뀌던 허점
NOT_SEARCH = r'어떻게|방법|절차|기간|운영|인증|수령|사진|보관|개인정보|날씨|예약|맡겨|맡기|주웠|주운|주움|습득|뺏|빼앗|도난|어디'


def corrected_question(question):
    """11/9 채점표: "아니 파란색이요", "지갑 말고 보조배터리요. 흰색" → 고쳐 말한 뒤쪽(새 조건)만. 조건이 없으면 그대로"""
    from agents.lost_input import correction_tail
    tail = correction_tail(question.lower()) if isinstance(question, str) else None
    if not tail:
        return question
    try:
        f, _ = text_features(question, corrected=True)
    except ValueError:
        return question
    keep = [v for k, v in f.items() if k in ('color', 'category') and v not in (None, '확인 불가', '없음')]
    if not keep:
        return question
    names = {'모형폰': '휴대폰'}
    cat = f.get('category') if f.get('category') not in (None, '확인 불가', '없음') else ''
    core = ' '.join(x for x in (f.get('color') or '', names.get(cat, cat)) if x)
    return core + (' 찾아줘' if re.search(r'찾아|검색|잃어버|잃었', tail) else '')


def resolve_turn(question, history, context, guidance):
    """Resolve only an elliptical follow-up; unrelated/new questions stay independent."""
    question = corrected_question(natural_question(question))
    previous, inherited = None, {}
    for turn in history:
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
    # 11/9 채점표: "아 잘못 말했어요, 갈색이에요"·"아니 파란색이요" — 쉼표·고쳐 말하기가 있어도 짧은 조건 말이면 이어서 찾기
    from agents.lost_input import CORRECTION
    correction = bool(CORRECTION.search(question)) or bool(re.search(r'잘못말', q))
    bare = re.sub(r'[,，~]', '', q)
    fragment = bool(re.fullmatch(r'(?:그럼|그러면|이번엔|이번에는|그건|그거|아니|아)?[가-힣a-z0-9 ]{0,24}[?？.!]*', bare)) \
        or (correction and len(bare) <= 32 and not re.search(r'[?？]', bare))
    has_attribute = any(features.get(k) not in (None, '확인 불가', '없음') for k in ('category', 'color'))
    elliptical = bool(re.match(r'^(그럼|그러면|그건|그거|이번엔|이번에는)', q) or (has_attribute and re.fullmatch(r'.{1,20}(?:은|는|으로)(?:요)?[?？.!]*', q)))   # 11/9 '지갑은요?'
    inherited = inherited or context
    retry_search = bool(re.fullmatch(r'(?:그럼|그러면)?(?:다시|한번더)(?:찾아줘|찾아주세요|검색해줘)[?？.!]*', q))
    fragment_search = (fragment and has_attribute) or (search_intent(question) and features.get('category') == '확인 불가') or retry_search
    if inherited.get('category') and fragment_search and not warnings:
        # A fragment such as “USB는?” continues search, but a new how-to question does not.
        if not re.search(NOT_SEARCH, q):
            return question + ' 찾아줘', {**context, **inherited}, True
    if inherited.get('category') and features.get('category') in (None, '확인 불가') and not warnings:
        # 11/7: "파란 휴대폰 잃어버렸어" 다음 "중앙역에서 어제 잃어버렸어요"처럼 장소·날짜만 덧붙이면 앞 물건으로 이어서 찾는다
        extra, _ = search_context(question, {})
        if (extra.get('lost_station') or extra.get('lost_date') or extra.get('lost_line')) \
                and not re.search(NOT_SEARCH, q):
            return question + ' 찾아줘', {**context, **inherited}, True
    referential = is_referential(q)
    if referential and previous and not has_attribute:
        current = guidance.ask(question)
        sequel = bool(re.match(r'(?:그럼|그러면)?(?:그다음|그후|그뒤|그전|그때까지|그안에)', q))   # 앞 주제의 다음·이전 단계를 묻는 말은 답이 있어도 앞 주제로
        if current['status'] == 'not_found' or sequel:
            prior = guidance.ask(previous)
            topics = [s['topic'] for s in prior['sources']]
            if len(topics) == 1 and topics[0] in TOPIC_LABELS:
                resolved = TOPIC_LABELS[topics[0]] + ' ' + question
                return resolved, context, True
    # 11/11 "립밤은요?"(물건 놓는 법 뒤): 립밤이 '다루는 물건' 문서에도 있어 그 답이 나왔다 — 물건 이름 하나 + '은요?' 뿐이면
    # 앞 주제(하나일 때)로 먼저 이어 묻는다. 앞 주제로 답이 없으면 아래 원래 길로
    bare_item = has_attribute and bool(re.fullmatch(r'[가-힣a-z0-9]{1,10}(?:은|는)요?[?？.!]*', q.replace(' ', '')))
    if bare_item and previous and not search_intent(question):
        topics = [s['topic'] for s in guidance.ask(previous)['sources']]
        if len(topics) == 1 and topics[0] in TOPIC_LABELS:
            resolved = TOPIC_LABELS[topics[0]] + ' ' + question
            if guidance.ask(resolved)['status'] != 'not_found':
                return resolved, context, True
    if elliptical and not search_intent(question) and guidance.ask(question)['status'] == 'not_found':
        # 11/9 채점표: "그럼 다시 시도할 수는 있어요?"(본인인증 뒤), "지갑은요?"(물건 놓는 법 뒤) — 앞 주제가 하나면 그 주제로 이어 묻기
        if previous:
            topics = [s['topic'] for s in guidance.ask(previous)['sources']]
            if len(topics) == 1 and topics[0] in TOPIC_LABELS:
                resolved = TOPIC_LABELS[topics[0]] + ' ' + question
                if guidance.ask(resolved)['status'] != 'not_found':
                    return resolved, context, True
        return question, context, None
    return question, context, False
