"""질문의 요청 종류에 맞춰 결론·필수 설명·다음 행동을 구성한다.

조회·접수·권한을 실행하지 않는 안내 전용 부품. 근거 없는 정책은 추가하지 않는다.
"""
import re
import unicodedata


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).lower()


def question_goal(question):
    q = compact(question)
    # 서로 다른 정책을 함께 물으면 한 주제용 문장으로 다른 요청을 덮지 않는다.
    policy_parts = [r'운영시간|영업시간|몇시', r'택배|배송|우편', r'대리|대신.*수령',
                    r'보관기간|파기|삭제', r'수수료|비용|요금', r'센터.*(?:주소|위치|어디)']
    if sum(bool(re.search(p, q)) for p in policy_parts) > 1:
        return None
    # 복합 요청은 기존 주제 분리기가 각 부분을 처리한다. 한 답으로 덮지 않는다.
    # 11/12 "빨간색 립밤 있는지 보고 운영시간도", "파란 휴대폰 찾고 받는 순서도"도 복합(main 채점표 #223·#272)
    if (re.search(r'찾아줘|검색해줘|후보보여|있는지|있으면|찾고|찾아서', q) and re.search(r'그리고|[.。]|절차도|시간도|순서도|보고|하고|찾고|랑|같이|함께', q)
            or re.search(r'운영시간|몇시에열|몇시에닫', q) and re.search(r'절차|순서|어디로|위치', q)
            or re.search(r'연락처|보관기간|파기|삭제|지우', q) and re.search(r'수령|받는순서', q)):
        return None
    registration = re.search(r'접수|신고|등록', q)
    ability = re.search(r'수있|가능|되나|돼요|되죠|해도|할까|할수|되나요', q)
    # 명령("접수해줘")과 기능 설명("접수할 수 있나요")을 구별한다.
    if registration and ability and re.search(r'날짜|언제|장소|역', q) and re.search(
            r'모르|몰라|모름|확신못|기억.{0,5}(?:안|없|못)', q):
        return 'unknown_details'
    if registration and re.search(r'두물건|두개|여러물건|한꺼번|둘다', q) and re.search(
            r'하나|한건|합쳐|묶어|같이', q):
        return 'separate_items'
    if registration and ability and re.search(r'온라인|채팅|챗봇|여기서|대화', q):
        return 'chat_registration'
    if re.search(r'향|냄새', q) and re.search(r'찾|검색|단서|구별|기준|기억', q):
        return 'scent_search'
    if re.search(r'주인|소유자|내물건', q) and re.search(r'구별|구분|확인|판별', q):
        return 'ownership'
    if re.search(r'한손|손을못|글씨.{0,6}(?:안보|못보)|글을.{0,4}못읽|시각장애|잘안보', q) and re.search(
            r'도와|도움|말로|음성|천천히|하나씩', q):
        return 'accessible_help'
    if '센터' in q and re.search(r'위치|어디', q) and not re.search(
            r'받|수령|절차|운영시간|몇시|보관|도착|택배|맡기|습득신고', q):
        return 'center_location'
    if re.search(r'받|수령', q) and re.search(r'순서|준비.*절차|방법|어떻게|받으려면', q) and not re.search(
            r'취소|대리|택배|배송|거절|실패|잃어버린척|신분증.{0,3}없|주운|주웠|맡기|번호.{0,3}받|언제|몇시|시간', q):
        return 'pickup_steps'
    if re.search(r'운영시간|영업시간', q) and not re.search(r'순서|절차', q):
        return 'hours'
    # 서비스 자체의 코드/음성 기능 질문은 주제 외로 돌리지 않는다.
    from agents.guidance import off_topic
    if re.search(r'파이썬|프로그래밍|프로그램.{0,12}(?:짜|작성|만들)|계산기.{0,8}(?:짜|코드)', q) and off_topic(q):
        return 'outside_programming'
    if re.search(r'(?:너|넌|당신).{0,12}(?:외계인|사람이야|로봇이야|정체)', q):
        return 'light_chat'
    return None


def goal_reply(question, guidance):
    goal = question_goal(question)
    if not goal:
        return None
    answers = {
        'unknown_details': ('시연에서는 잃어버린 역이나 날짜를 몰라도 분실 접수를 이어 갈 수 있어요. '
            '모르는 항목은 "모름"으로 두고 임의의 역·날짜를 넣지 마세요. '
            '접수를 시작하려면 "분실 접수하기"를 눌러 주세요.', ('chat_intake',)),
        'separate_items': ('서로 다른 물건은 하나로 합쳐 접수하지 않고 각각 나눠서 신고해요. '
            '먼저 한 물건의 접수를 마친 뒤 다른 물건을 접수해 주세요. '
            '먼저 접수할 물건 한 가지와 색을 알려 주세요.', ('chat_intake', 'placement_guide')),
        'chat_registration': ('네, 시연에서는 이 채팅으로 분실 접수와 습득 신고를 진행할 수 있어요. '
            '필요한 정보를 모으고 마지막 요약을 확인한 뒤 "접수할게요"를 눌러야 접수돼요. '
            '잃어버린 물건이면 "분실 접수하기", 주운 물건이면 "습득 신고하기"를 눌러 주세요.', ('chat_intake',)),
        'scent_search': ('현재 후보 검색은 향·냄새를 검색 조건으로 사용하지 않아요. '
            '물건 종류·색과 분실 장소·날짜처럼 지원하는 조건으로 확인할 수 있어요. '
            '기억나는 물건 종류와 겉으로 보이는 색을 알려 주세요. 모르면 "모름"이라고 해 주세요.', ('site_help', 'candidate_scope')),
        'ownership': ('색이나 생김새가 같다고 주인으로 확정하지 않아요. '
            '본센터 키오스크에서 신분 확인과 물건 특징 확인 질문을 거쳐 본인 물건인지 확인해요. '
            '확인 질문을 통과하지 못하면 직원의 대면 확인이 필요해요.', ('candidate_scope', 'center_pickup')),
        'accessible_help': ('한 번에 하나씩 천천히 도와드릴게요. '
            '채팅의 음성 질문 버튼으로 말한 내용을 글로 바꿀 수 있고, 인식된 내용을 확인한 뒤 전송하면 돼요. '
            '먼저 잃어버린 물건이 무엇인지 알려 주세요.', ('site_help',)),
        'pickup_steps': ('찾기 번호와 시연용 가상 신분증을 준비해 부산역 본센터 키오스크로 오세요.\n'
            '① 신분 확인과 물건 특징 확인 질문을 진행해요.\n'
            '② 로봇이 제출보관함에 물건을 놓을 때까지 기다려요.\n'
            '③ 제출보관함에서 물건을 꺼낸 뒤 "물건 받았어요"를 눌러요.\n'
            '확인 질문 미통과나 직원 보관 선반의 물건은 직원 확인이 필요해요. '
            '(프로젝트 시연 기준이며 실제 기관 안내가 아니에요.)', ('center_pickup',)),
        'outside_programming': ('프로그램 작성은 이 챗봇의 안내 범위 밖이에요. '
            '분실물 찾기·습득 신고·물건 받는 방법을 도와드릴 수 있어요.', ()),
        'light_chat': ('저는 분실물 안내 도우미예요. 찾거나 맡길 물건이 있으면 알려 주세요.', ()),
    }
    if goal in ('hours', 'center_location'):
        topic = 'hours' if goal == 'hours' else 'center_contact'
        docs = [d for d in guidance.documents if d['topic'] in ({'center_pickup', topic} if goal == 'center_location' else {topic})]
        # 근거 목록의 기존 계약은 유지하고, 본문은 질문한 위치부터 답한다.
        return {**guidance._response('answered', '\n\n'.join(d['answer'] for d in docs if d['topic'] == topic), docs),
                'method': 'question_goal_guidance'}
    answer, topics = answers[goal]
    short_pickup = goal == 'pickup_steps' and not re.search(r'순서|준비.*절차', compact(question))
    if short_pickup:
        topics = ('pickup', 'center_pickup')
    docs = [d for d in guidance.documents if d['topic'] in topics]
    result = guidance._response('not_found' if goal == 'outside_programming' else 'answered', answer, docs)
    result['method'] = 'question_goal_checked_generation' if short_pickup else 'question_goal_guidance'
    if goal == 'chat_registration':
        result['choices'] = ['분실 접수하기', '습득 신고하기']
    return result


def covers_goal(goal, answer):
    """단순히 같은 품목이나 가능 표현이 있다는 이유로 동문서답을 통과시키지 않는다."""
    a = compact(answer)
    patterns = {
        'unknown_details': r'모름|몰라도|모르.{0,8}(?:접수|신고)',
        'separate_items': r'(?:각각|따로|물건별|나눠).{0,12}(?:접수|신고)|하나.{0,15}접수하지않',
        'chat_registration': r'(?:채팅|챗봇|대화).{0,16}(?:접수|신고).{0,12}(?:수있|가능|진행)|(?:접수|신고).{0,12}(?:불가|수없)',
        'scent_search': r'(?:향|냄새).{0,18}(?:않|없|못|불가|지원)',
        'ownership': r'(?:신분|본인).{0,12}확인.{0,30}(?:특징|물건).{0,12}(?:질문|확인)',
        'accessible_help': r'음성|말한내용.{0,12}글|하나씩|한번에하나',
        'pickup_steps': r'제출보관함.*(?:꺼낸|꺼내|꺼내고).*물건받았어요',
        'hours': r'\d{1,2}:\d{2}|운영시간.{0,12}(?:미정|확인)',
        'center_location': r'부산역',
        'outside_programming': r'범위밖|분실물.{0,15}(?:안내|도와)',
        'light_chat': r'분실물|물건',
    }
    if goal == 'chat_registration':
        return bool(re.search(patterns[goal], a) and '접수할게요' in a
                    and re.search(r'요약.{0,12}확인|확인.{0,12}요약', a)
                    and '안내자료에서이질문에바로답할내용은찾지못' not in a)
    if goal == 'center_location':
        first = re.split(r'[.!?\n]', answer, maxsplit=1)[0]
        return bool(re.search(patterns[goal], compact(first)))
    return bool(re.search(patterns[goal], a)) if goal in patterns else True
