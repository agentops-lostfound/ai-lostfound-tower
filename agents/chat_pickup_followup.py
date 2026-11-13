"""접수 뒤의 짧은 말을 다음 행동으로 연결한다. 번호는 인증·수령 준비의 증거가 아니다."""
import re

from agents.chat_turn import compact


NUMBER = re.compile(r'\b([CLS])-\d{8}-\d{4}\b', re.I)


def number_kind(text):
    matches = list(NUMBER.finditer(text))
    if matches:
        return matches[-1].group(1).upper()
    q = compact(text)
    for label, kind in (('찾기번호', 'C'), ('대기번호', 'L'), ('습득접수번호', 'S')):
        if label in q:
            return kind
    return None


def pickup_reply(question, history, guidance, receipt=None):
    q = compact(question)
    trusted = (receipt or {}).get('intake') or {}
    known_receipt = bool(trusted.get('claim_id') or trusted.get('wait_id') or
                         (trusted.get('kind') == 'found' and trusted.get('item_id')))
    if known_receipt and re.search(r'고칠|고치|수정|바꿀|바꾸|정정', q):
        return {**guidance._response('answered', '이미 접수된 내역은 이 대화에서 수정하지 않았어요. 받은 번호로 본센터 직원에게 처리 내용을 확인해 주세요. 같은 신고를 새로 접수하지 마세요.', []),
                'method': 'receipt_next_step_guidance'}
    if any(m.group(1).upper() == 'L' for m in NUMBER.finditer(question)):
        return None  # L- 번호 자체는 기존의 실제 상태 조회 창구로 보낸다.
    # 별도 정책·신고·취소 질문을 수령 안내로 덮지 않는다.
    if re.search(r'취소|철회|분실|습득신고|접수해|신고해|날씨|운영시간|몇시|택배|대리|신분증.*없|정답|남의|다른사람'
                 r'|번호.*(?:없|못받|안받|받지않|받은적없)|(?:못|안)받|검색|찾아줘'
                 r'|인증|신분|동의|개인정보|이름|전화|연락|유효|만료|기간|삭제|지워|로봇|정지|멈춰|고장|위험|비용|수수료|보관료', q):
        return None
    received = bool(re.search(r'번호(?:는|를|도|이미|벌써)*(?:받았|받음|있어|있는데|받은)', q)
                    and not re.search(r'못받|안받|없|아직.*안', q))
    next_step = bool(re.search(r'찾으러(?:가|갈|오)|받으러(?:가|갈|오)|수령하러|다음(?:엔|은|에|뭐|어떻게|단계)|이제(?:뭐|어디|가도|가면)|그다음', q)
                     or re.match(r'^(?:그럼|그러면)?(?:가도(?:돼|되)|가면(?:돼|되)|어디로가|뭐하면|뭘하면)', q))
    short_ack = bool(re.fullmatch(r'(?:응|네|이미|벌써|아까|그거)*(?:받았어(?:요)?|받았습니다|있어(?:요)?)[.!?~]*', q))
    bare_number = bool(NUMBER.fullmatch(question.strip()))
    kind = number_kind(question)
    if not kind:
        if trusted.get('claim_id'):
            kind = 'C'
        elif trusted.get('wait_id') and trusted.get('state') != 'unknown':
            kind = 'L'
        elif trusted.get('kind') == 'found' and trusted.get('item_id'):
            kind = 'S'
    if not kind:
        # 브라우저의 assistant 답은 믿지 않는다. 사용자 말은 의도 해석에만 쓴다.
        for previous in reversed(history or []):
            kind = number_kind(previous)
            if kind:
                break
    contextual_followup = known_receipt and bool(re.search(
        r'그(?:거|번호)|이번호|입력|넣는|넣는데|넣어|적어|누르|꺼내|뭘하면|뭘해야|뭐하면|뭐해야|아직|들어왔|도착|보관중|상태|기다|다시확인|내가뭘', q))
    if not (received or bare_number or ((next_step or short_ack) and kind) or contextual_followup):
        return None
    if kind == 'C':
        if re.search(r'도착|보관중|현재상태|실시간', q) and re.search(r'지금|현재|했|한거|됐|됐어|인지|상태|실시간', q):
            answer = ('이 답변에서는 물건의 실시간 도착·보관 상태를 조회한 것이 아니에요. 찾기 번호가 있어도 지금 도착했다고 단정할 수는 없어요. '
                      '분실인 웹의 진행 상황이나 본센터 키오스크에서 상태를 확인해 주세요. 수령 준비가 확인되면 본인·물건 확인 절차를 진행해요. (교육용 시연 기준)')
        elif re.search(r'어디.*(?:입력|넣|누르|적어)|(?:입력|넣).*(?:곳|어디)', q):
            answer = ('본센터 도착·보관 상태가 확인되면 부산역 본센터 키오스크의 [물건 찾으러 왔어요]에서 입력해요. '
                      '찾기 번호와 신고 때 고른 가상 신분증 뒤 첫 숫자를 넣고, 화면의 본인·물건 확인 절차를 진행해 주세요. (교육용 시연 기준)')
        elif re.search(r'(?:입력|넣|번호).*(?:바로|끝|꺼내)|바로.*꺼내', q):
            answer = ('번호 입력만으로 바로 물건을 꺼내지는 않아요. 본센터 도착·보관 상태와 본인·물건 확인을 거쳐야 해요. '
                      '부산역 본센터 키오스크에서 확인을 마치고 로봇이 제출보관함에 놓을 때까지 기다린 뒤, '
                      '물건을 꺼내고 [물건 받았어요]를 눌러요. 확인 질문을 통과하지 못하면 직원 확인이 필요해요. (교육용 시연 기준)')
        else:
            answer = ('찾기 번호를 이미 받으셨다면 본센터 도착·보관 상태를 먼저 확인해 주세요. '
                  '번호만으로 즉시 수령 가능하다고 확정할 수는 없어요.\n'
                  '준비가 끝나면 부산역 본센터 키오스크에서:\n'
                  '① [물건 찾으러 왔어요] → 찾기 번호와 신고 때 고른 가상 신분증 뒤 첫 숫자 입력\n'
                  '② 본인·물건 확인 → 로봇이 제출보관함에 놓을 때까지 대기\n'
                  '③ 물건을 꺼낸 뒤 [물건 받았어요]\n'
                      '확인 질문을 통과하지 못하면 직원 확인이 필요해요. (교육용 시연 기준)')
        status = 'answered'
    elif kind == 'L':
        answer = ('대기 신고의 연결 상태를 다시 확인하려는 거군요. 받은 대기 번호(L-)를 이 창에 보내 주세요. '
                  '새로 조회하기 전에는 물건이 들어왔는지 단정할 수 없어요. 대기 번호만으로 바로 수령할 수는 없어요. '
                  'C- 찾기 번호로 연결되고 본센터 도착·보관이 확인된 뒤 수령 절차를 진행해요.')
        status = 'answered'
    elif kind == 'S':
        answer = ('습득 접수 번호(S-)는 주운 물건을 맡긴 기록이고, 내 물건을 받는 찾기 번호(C-)가 아니에요. '
                  '주운 물건은 신고한 역의 키오스크 상자에 넣어 주세요. '
                  '본인이 잃어버린 물건을 찾는 중이라면 찾기 번호를 받았는지 알려 주세요.')
        status = 'answered'
    else:
        answer = ('받은 번호가 C-로 시작하는 찾기 번호인가요, L-로 시작하는 대기 번호인가요, '
                  'S-로 시작하는 습득 접수 번호인가요? 번호 종류에 따라 다음 단계가 달라요. 실제 신분정보는 보내지 마세요.')
        status = 'clarification_needed'
    docs = [d for d in guidance.documents if d['topic'] in ('center_pickup', 'arrival')]
    return {**guidance._response(status, answer, docs), 'method': 'receipt_next_step_guidance'}
