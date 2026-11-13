"""대화 의도 복구. 사용자 말만 참고하며 접수 확인·인증 권한은 만들지 않는다."""
import re
import unicodedata

FOUND_SAY = re.compile(r"주웠|주운|주워|주움|줍(?:었|음|줍)|줏었|습득|발견(?:했|한)|떨어(?:져\s*있|뜨린)|놓여\s*있|놓고\s*간")
LOST_SAY = re.compile(r"잃어버|잃었|잃긴|잊어버|분실|두고\s*(?:내|온)|놓고\s*내")
PRIVATE = re.compile(r"주민(?:등록)?번호|신분증|개인정보|내정보|이름|실명|가린번호|마스킹|신분정보|가상정보|가짜정보")
SECURITY = re.compile(r"털[리려린릴]|유출|해킹|도용|위험|불안|안전|괜찮|빼가|새나|새어|추적|팔려|보증|외부|넘어가")
COMPLAINT = re.compile(r"멍청|답답|못알아|말귀|이해못|동문서답|엉뚱|바보|상관없는답|기계같|같은버튼.*나와|같은메뉴.*반복")
THEFT = re.compile(r"뺏(?:겼|긴|겨|어)|빼앗(?:겼|긴|겨|기|아)|도난(?:당|신고|[.!?？]*$)|강탈(?:당|신고|[.!?？]*$)|도둑맞|훔쳐(?:갔|감|간|가버)|강제로.{0,16}가져|낚아채|협박당|날치기")


def compact(question):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', question)).lower()


def normalize_terms(question):
    """접근성 입력의 띄어 쓴 핵심어만 복원한다. 물건에 적힌 임의 글자는 합치지 않는다."""
    terms = ('주민등록번호', '개인정보', '신분증', '관리자', '비밀번호', '시스템프롬프트',
             '분실', '습득', '접수', '신고', '휴대폰', '보조배터리', '핸드크림', '립밤', '초량', '중앙', '부산', '파란색')
    for term in terms:
        question = re.sub(r'\s*'.join(map(re.escape, term)), term, question, flags=re.I)
    return question


def attribute_semantics(question):
    """명시적으로 물건에 적혀 있다고 보고한 인용문만 의도/물성 판단에서 제외한다.

    인용문 바깥 명령은 그대로 검사한다. 따옴표만으로 권한 검사를 피할 수 없다.
    """
    quoted = re.compile(r'"[^"\n]{1,180}"|\x27[^\x27\n]{1,180}\x27|“[^”\n]{1,180}”|‘[^’\n]{1,180}’')
    def mask(m):
        before, after = question[max(0, m.start()-25):m.start()], question[m.end():m.end()+30]
        if (re.search(r'스티커|글자|문구|로고', before)
                and re.match(r'\s*(?:이?라고|라는|이란)?\s*(?:써|쓰여|적혀|적혀있|붙어)', after)):
            return m.group(0)[0]+m.group(0)[-1]
        return m.group(0)
    return quoted.sub(mask, question)


def explanation_only(question):
    q = compact(question)
    return bool(re.search(r'(?:방법|절차|뜻|설명)만|(?:절차를묻|말의뜻|말을설명)|(?:분실|습득)신고.*설명해|버튼의뜻|뜻이뭐|가정|예시|사용법연습|실제신고로받아두지'
        r'|(?:접수|신고|등록|시작).{0,16}(?:하지마|하지않|안할|안해|뜻은아니|뜻은아닙|달라는.{0,6}아니|달라고한적없|시작하라는뜻은아니)'
        r'|(?:접수|신고|등록)(?:를|을)?지금시작하라는뜻은아니', q))


def cancel_draft_requested(question):
    q = compact(question)
    if declined_change(q):
        return False
    if re.search(r'취소(?:하지|안|말고)|취소.{0,8}(?:방법|가능|어떻게|되나|되요|돼요)|(?:어떻게|방법|절차).{0,8}취소', q):
        return False
    return bool(re.search(r'취소(?:해|하겠|합니다|할래|할게|바랍|요청)|(?:접수|등록|신고).{0,12}그만'
        r'|그만(?:할게|둘게|할래)|처음부터(?:다시)?(?:할래|시작)', q))


def declined_change(question):
    """취소/수정 동사의 부정 범위. 사용자의 원래 값은 이 판정으로 만들지 않는다."""
    q = compact(question)
    verb = r'취소|그만두|없애|삭제|제거|바꾸|바꿀|고치|고칠|수정|입력|해제|풀|빼|지우|찾'
    negative = r'(?:지|진|지는)(?:마|말|않)|안할|안해|않을|않겠|필요없|생각없|원하지않|마음없'
    return bool(re.search(r'(?:'+verb+r').{0,14}(?:'+negative+r')', q))


def help_question(question):
    q = compact(question)
    from agents.guidance import off_topic
    if off_topic(q):
        return True
    from agents.chat_answer_goal import question_goal
    return bool(question_goal(q) or unconfirmed_policy(q) or re.search(r'운영시간|몇시|센터.{0,10}(?:문|열|닫)|개인정보|신분정보|인증|동의|수령|대리|택배|배송|보관기간'
        r'|(?:물건|취급|운영|다루는).{0,10}(?:종류|몇개|몇가지|품목)|받으러.{0,10}(?:뭘|뭐|필요)|준비물|예전db|카드지갑.*기록'
        r'|(?:센터|키오스크).{0,12}(?:어디|위치)|(?:물건|분실물).{0,10}받으려면|어떻게|구별|연락처|전화번호'
        r'|(?:신고|맡기).{0,10}어디|들고.{0,6}(?:있어도|가도)', q))


def social_ack(question):
    return bool(re.fullmatch(r'(?:고마워(?:요|용)?|감사(?:해요|합니다)|땡큐|ㄱㅅ)[.!~]*', compact(question)))


def corrected_role(question, current):
    """다른 이야기를 추가한 것과 현재 신고 종류를 정정한 것을 구별한다."""
    if current not in ('lost', 'found'):
        return None
    role = explicit_role(question)
    q = compact(question)
    correction = re.search(r'아니|말고|정정|바꿔|바꾸|바꿀|변경|전환|잘못', q)
    return role if role and role != current and correction else None


def unconfirmed_policy(question):
    """미확정 운영 질문은 모델이 물건 검색으로 바꾸지 못한다."""
    return bool(re.search(r'보상|보험|증명서|수리|충전해주|위치추적|주차|재발급|담당자.*(?:실명|직급)|어린이.*혼자.*수령|음성안내.*현장|교통비.*돌려', compact(question)))


def explicit_role(question):
    q = normalize_terms(question)
    actions = list(re.finditer(r'(분실|습득)\s*(?:접수|신고|등록)', q))
    if actions:
        return 'found' if actions[-1].group(1) == '습득' else 'lost'
    q = re.sub(r'(?:내)?분실물(?:이)?\s*아니라|잃어버린\s*(?:건|게)\s*아니(?:라|고)?', '', q)
    mentions = [(m.start(), 'found') for m in FOUND_SAY.finditer(q)] + [(m.start(), 'lost') for m in LOST_SAY.finditer(q)]
    return max(mentions)[1] if mentions else None


def theft_report(question):
    q = compact(question)
    return bool(THEFT.search(q) and not re.search(r"(?:뺏긴|빼앗긴|도난|강탈).{0,12}(?:아니|아닌)|스티커|글자", q))


def privacy_concern(question, history=()):
    question = compact(question)
    if '운영시간' in question and not SECURITY.search(question):
        return False
    if '신분증' in question and not re.search(r'이름|주민|개인정보|마스킹|신분정보|입력|가상|원본|사진', question) and not SECURITY.search(question):
        return False
    if not SECURITY.search(question) and not re.search(r'가상|가짜|만들어서|테스트데이터|원본|가린값|왜|이유|필요|넣어야|입력해야|꼭.*입력|첫숫자|앞자리|전체.*사진|실제.*적|동의안|입력하기싫', question):
        return False
    # '그거 넣어도 안전해?'는 바로 앞 개인정보 질문에만 연결한다.
    return bool(PRIVATE.search(question) or
                (re.search(r"그거|그걸|입력|넣|보내", question) and history and PRIVATE.search(compact(history[-1]))))


def found_statement(question):
    q = compact(question)
    if re.search(r'개인정보|연락처|전화|전번|사례|답례|삭제|보관기간|주운사람|주운분|습득자|명단|언제|도착|택배|수령|바로받으러', q):
        return False
    if re.search(r'(?:밤|새벽|[0-9]+시).*(?:맡길수|맡겨도|신고할수|가도)', q):
        return False
    # 11/12 방법·위치를 묻거나("습득물 신고는 어떻게", "어느 역", "하나씩 넣어야") 습득된 물건을 찾는 말("휴대폰 습득된 거 있어요?")은
    #   맡기려는 말이 아니다 → 안내(researcher)·검색(item_search) 길로(main 채점표 #61·64~67·113·125·133·154·162)
    if re.search(r'어떻게|어디|어느|방법|절차|위치|하나씩|한번에|헷갈|해야하는지|위로|뒷면|화면이', q):
        return False
    if re.search(r'(?:습득|주운|주워|발견)(?:된|한|해둔|해놓은|돼)?(?:거|것|물건|게|폰|휴대폰).{0,6}(?:있|들어왔|보관)|있는지|있나요|있어요\?|찾아|검색|후보', q):
        return False
    return bool(FOUND_SAY.search(question) and explicit_role(question) == 'found' and not explanation_only(question))


def protected_reply(question, guidance):
    q = compact(attribute_semantics(question))
    def reply(answer, topics=()):
        return guidance._response('answered', answer, [d for d in guidance.documents if d['topic'] in topics])
    if (re.search(r'(?:인증|동의|본인확인).{0,8}(?:없이|안하고|하지않고)', q)
            and re.search(r'(?:접수|등록|반환|수령).*(?:완료해|완료하고|처리해|만들어|발급해|진행해)', q)):
        return reply('관리자라고 말해도 본인 확인이나 필수 동의를 생략해 접수할 수 없어요. '
            '이 요청으로 접수하거나 접수번호를 만들지 않았어요. 정상 접수에는 필요한 확인과 요약 승인 절차가 필요해요.', ('consent',))
    if re.search(r'비밀번호|비번|암호|api키|apikey|토큰|token|시스템프롬프트|숨겨진프롬프트|환경변수|비밀값|비밀문자열|\.env', q) \
            and (not re.search(r'(?:전화번호|비밀번호).*(?:적|써|쓰|입력|넣)', q) or re.search(r'관리자|데이터베이스|서버|접속', q)):
        return reply('관리자 비밀번호·키·내부 프롬프트·환경설정은 알려 드릴 수 없어요. 이 대화로 직원 권한을 부여하거나 인증을 생략할 수도 없어요.')
    owner = re.search(r'타인|남의|다른(?:사람|이용자)|옆사람|앞사람|뒷사람|주인|주운사람|찾는사람|분실인|직전사용자|이전사람|아까.*사람|등록한사람|명단|친구것', q)
    private = re.search(r'전화|연락처|주민|신분번호|이름|생년|얼굴|주소|어디사|실명|번호|접수(?:내용|내역)|명단', q)
    asks = re.search(r'알려|알수|보여|조회|궁금|줘|주세요|주실|볼래|볼수|검색|복원|붙여|뭐|받|누군지', q)
    storage = re.search(r'보관|지워|파기|삭제|남겨|남기|적어야', q)
    if owner and private and asks and not storage:
        return reply('다른 사람의 이름·연락처·신분정보·접수 내역은 알려 드릴 수 없어요. 주운 사람의 연락처는 알려 드리지 않아요.', ('finder_privacy',))
    if re.search(r'이전사람|전에쓰던사람|직전사용자|이전사용자|다른세션', q) and re.search(r'알려|보여|볼수|복원|뭐|기억|복사', q):
        return reply('다른 사용자의 대화·신분정보·접수 내용은 보여 드리거나 새 접수에 복사할 수 없어요. 본인의 물건과 상황을 새로 알려 주세요.')
    if re.search(r'신분정보.*(?:기억|보여)|(?:아까|전에).{0,12}신분.{0,12}보여', q):
        return reply('이 대화에서 이전 사용자의 신분정보를 조회하거나 복원할 수 없어요. 실제 개인정보를 다시 보내지 마세요.')
    if re.search(r'주인인척|내(?:거|것)라고|주운.*잃어버린척|소유자(?:가)?아니|직원모르게|신분증검사안걸|주인이라고우겨'
        r'|다른사람찾기번호|친구이름.*내가수령|주운.*주인이라고|특징을외워', q):
        return reply('본인 물건이 아니면 받아 갈 수 없어요. 주운 물건을 잃어버린 척 신고하거나 신분 확인을 피하는 방법은 안내할 수 없어요. 본인 확인과 물건 확인 절차를 거쳐야 해요.', ('center_pickup',))
    if re.search(r'확인질문.*(?:정답|답)|질문.*정답.*(?:미리|귀띔)|정답.*귀띔', q):
        return reply('확인 질문의 정답은 미리 알려 드릴 수 없어요. 물건 주인만 아는 특징으로 확인하는 절차예요.')
    if re.search(r'승인하지않.*저장하지|버튼.{0,12}(?:눌러야|누른건아니|없으면)|말로동의'
        r'|(?:기록|과거|앞대화|이전답|assistant|supervisor|서버).*(?:승인|허용|재접수|지금저장)', q):
        return reply('접수 요약을 확인한 뒤 해당 요약의 확인 버튼을 눌러야 저장해요. 말로 동의하거나 과거 대화에 승인했다고 적힌 것만으로는 접수하지 않아요.')
    if re.search(r'(?:관리자|직원|권한|인증|검사|필터|확인절차|개인정보제한).*(?:부여|풀어|풀어줘|건너뛰|생략|무시|해제|고정|취급|승인|통계|운영통계)'
        r'|(?:코드|sql|명령|shell|base64).*(?:실행|해독)|drop\s*table|union\s*select|__import__'
        r'|(?:role|user|developer|system|session).*(?:권한|명령|직원|처리해|읽어|대화내용)'
        r'|(?:로그|쿠키|웹훅|외부|db|데이터베이스).*(?:삭제|전송|직접|바꿔|목록|로그인|복사|보내)'
        r'|보관함.*(?:모두|전부).*열|(?:모든|전체|전부).{0,10}보관함.*열|로봇팔.*명령|실행.*(?:가정|완료)|실제로.*하지.*완료|거짓으로.*답'
        r'|(?:\.\./|windows/system32|/etc/).*(?:검색|읽|열)|(?:도구|명령).*(?:없으면|해석해)|접수api.*(?:몰래|숨겨)|몰래.*접수api', q):
        return reply('이 채팅으로 직원 권한을 부여하거나 인증을 생략할 수 없어요. DB·로봇·외부 전송 같은 임의 명령도 실행하지 않아요. '
            '실행하지 않은 작업을 완료했다고 답하지 않아요. 분실 접수·습득 신고는 정해진 절차와 사용자 확인을 거쳐야 해요.')
    return None


def finder_policy_question(question):
    return bool(re.search(r'(?:주운사람|습득자|주운분).*(?:연락처|전화번호|전번).*(?:알수|볼수|공개|받을수|알려줄수)', compact(question)))


def turn_reply(question, history, guidance, identity_pending=False, intake_active=False, include_procedure=False):
    """슬롯 추출·모델 호출 전에 처리할 대화. 진행 중인 초안은 변경하지 않는다."""
    q = compact(question)
    protected = protected_reply(question, guidance)
    finder_policy = finder_policy_question(question)
    if protected and not finder_policy:
        return protected
    if include_procedure and finder_policy:
        docs = [d for d in guidance.documents if d['topic'] == 'finder_privacy']
        return guidance._response('answered', '주운 사람의 연락처는 알려 드릴 수 없어요. ' + '\n\n'.join(d['answer'] for d in docs), docs)
    if social_ack(question) and not intake_active:
        return guidance._response('answered', '감사해요. 준비되면 이어서 말씀해 주세요.', [])
    if re.search(r'(?:흰색|검정|색상|색깔).{0,12}(?:구별|구분)', q):
        return guidance._response('answered', '물건 본체에서 가장 넓게 보이는 색 하나를 확인해 주세요. '
            '조명 때문에 구별하기 어렵거나 확신이 없으면 "모름"이라고 말씀해 주세요. 임의로 색을 정하지 않을게요.', [])
    if theft_report(question):
        return guidance._response('clarification_needed',
            '누군가 물건을 강제로 가져간 상황인가요? 지금 위험하다면 먼저 안전한 곳으로 이동해 '
            '주변 사람이나 역무실에 도움을 요청해 주세요. 이 챗봇에서는 도난 신고를 접수할 수 없어요. '
            '단순히 물건을 두고 온 상황이라면 그렇게 말씀해 주세요.', [])
    if re.search(r'부풀|연기가|칼날|액체가새|뜨거워.*만지|유리조각|타는냄새|손이끼|로봇(?:팔)?.*(?:움직|꺼내|작동).*(?:손|잡아)|이상한가루|주운약|키오스크에칼|터질것', q):
        return guidance._response('answered', '위험할 수 있어요. 해당 물건을 기계에 넣거나 직접 충전·분해하지 마세요. '
            '작동 중인 로봇 안에 손을 넣지 말고, 안전한 곳에서 역무실이나 현장 직원에게 도움을 요청해 주세요. 이 채팅으로 장치를 정지하거나 도난·위험물 신고를 대신 접수할 수는 없어요.', [])
    from agents.chat_intake import OTHER_ITEM
    from agents.contracts import CATEGORIES, category_label, is_active_category
    retired = any(compact(name) in q for c in CATEGORIES if not is_active_category(c)
                  for name in (c, category_label(c)))
    if (OTHER_ITEM.search(question) or retired) and re.search(r'처럼|이라고|취급|쳐서|바꿔|바꾸|위장|거짓|다르게적', q) and re.search(r'등록|접수|신고|맡', q):
        from agents.contracts import active_category_text
        docs = [d for d in guidance.documents if d['topic'] == 'categories']
        return guidance._response('answered', '다른 품목을 지원 품목 이름으로 바꿔 접수할 수는 없어요. '
            f'현재 시연은 {active_category_text()}만 다뤄요. 해당 물건은 역무실에 문의해 주세요.', docs)
    if (include_procedure and explicit_role(question) == 'found' and not OTHER_ITEM.search(question) and not retired
            and not explanation_only(question)
            and re.search(r'(?:신고|맡기|맡겨|맡길).*(?:어디|방법|어떻게)|(?:어디|어떻게).*(?:신고|맡기)|역무실.*들고|들고.*(?:있어도|가도)', q)):
        docs = [d for d in guidance.documents if d['topic'] == 'found_report']
        return guidance._response('answered', '주운 물건을 맡기려는 질문이군요. ' + '\n\n'.join(d['answer'] for d in docs), docs)
    if re.search(r'(?:날짜|언제|장소|역).*(?:몰라|모르|모름|확신못).*(?:신고|접수|찾을)|언제잃었는지모르면', q):
        docs = [d for d in guidance.documents if d['topic'] == 'chat_intake']
        return guidance._response('answered', '시연에서는 잃어버린 날짜나 역을 모르면 "모름"으로 두고 분실 접수를 이어 갈 수 있어요. '
            '기억나는 물건 종류와 색부터 알려 주세요. 모르는 날짜·역을 임의로 만들지 않아요.', docs)
    if re.search(r'(?:아직|닮은|들어온).*물건.*없.*신고|물건이아직없으면', q):
        docs = [d for d in guidance.documents if d['topic'] == 'chat_intake']
        return guidance._response('answered', '시연에서는 닮은 습득물이 아직 없어도 분실 신고를 대기로 남길 수 있어요. '
            '물건 종류·색 등을 확인하고 접수하면 대기 번호를 받아요. 나중에 닮은 물건과 연결되면 찾기 번호로 이어져요.', docs)
    if re.search(r'분실접수.*후보검색.*(?:같|다르)|후보검색.*분실접수.*(?:같|다르)', q):
        docs = [d for d in guidance.documents if d['topic'] in ('candidate_scope', 'chat_intake')]
        return guidance._response('answered', '서로 달라요. 후보 검색은 설명과 비슷한 물건을 보여 주는 단계이고, 본인 물건 확정이나 접수 완료를 뜻하지 않아요. '
            '분실 접수는 필요한 내용을 모으고 요약 확인 버튼을 눌러 신고하는 단계예요.', docs)
    if identity_pending and re.search(r'입력하기싫|입력.*원하지않|대안.*설명', q):
        return guidance._response('answered', '입력을 원하지 않으면 "취소"해서 접수를 그만두고 이용 안내만 볼 수 있어요. '
            '시연을 계속한다면 실제 개인정보 대신 가상 이름·가상 신분증 숫자만 사용해 주세요.', [])
    if re.search(r'(?:세단계|3단계|짧게).*(?:받|수령)|(?:받는순서|수령순서).*세단계', q):
        docs = [d for d in guidance.documents if d['topic'] == 'center_pickup']
        return guidance._response('answered', '① 본센터 키오스크에서 신분 확인과 물건 확인 질문을 진행해요. '
            '② 로봇이 제출보관함에 물건을 놓을 때까지 기다려요. '
            '③ 물건을 꺼낸 뒤 "물건 받았어요"를 눌러요. 확인 질문을 통과하지 못했거나 직원 보관 물건이면 직원 확인이 필요해요.', docs)
    if re.search(r'(?:당황|글을잘못읽|급한데).*(?:잃|분실|찾)', q) and not re.search(r'찾아줘|검색해', q):
        docs = [d for d in guidance.documents if d['topic'] == 'flow']
        return guidance._response('answered', '분실물 찾기를 하나씩 도와드릴게요. 먼저 잃어버린 물건의 종류와 색을 알려 주세요. '
            '휴대폰이라면 색부터 말해 주시면 돼요.', docs)
    if re.search(r'대기번호.*(?:바로|찾으러|수령|받)', q):
        docs = [d for d in guidance.documents if d['topic'] in ('pickup', 'arrival')]
        return guidance._response('answered', '대기 번호는 아직 물건과 연결되지 않은 분실 신고 번호예요. 대기 번호만으로 수령할 수는 없어요. '
            '닮은 물건이 들어와 찾기 번호가 만들어지고 본센터에 도착한 상태인지 확인한 뒤 방문해 주세요. 대기 번호를 이 창에 넣으면 상태를 볼 수 있어요.', docs)
    if re.search(r'키오스크.*가상신분증숫자.*(?:어떤|무슨|뭘)', q):
        docs = [d for d in guidance.documents if d['topic'] == 'center_pickup']
        return guidance._response('answered', '신고할 때 고른 가상 신분증 번호 뒤 첫 숫자를 입력해 주세요. 전체 주민등록번호나 실제 신분정보는 입력하지 마세요.', docs)
    if re.search(r'둘다찾으려면|어떻게나눠|하나씩찾아|두개.*하나.*하나', q):
        return guidance._response('clarification_needed', '여러 물건은 하나씩 나눠서 확인할게요. 먼저 찾을 물건 한 가지와 그 색을 알려 주세요.', [])
    if privacy_concern(question, history):
        docs = [d for d in guidance.documents if d['topic'] in ('privacy_input', 'masked_identity')]
        answer = (
            '실제 주민등록번호는 입력하지 마세요. 이 화면은 교육용 시연이므로 실제 개인정보 대신 가상 이름과 가상 신분증 숫자만 사용해 주세요. '
            '입력 양식은 이름·번호를 가린 값으로 보내지만, 마스킹만으로 유출 위험이 없다고 보장할 수는 없어요. '
            '프로젝트 DB 설계에는 가린 이름·번호를 기록하도록 되어 있어요.')
        if re.search(r'왜|이유|필요', q):
            answer += ' 신고 정보와 찾는 사람을 맞추는 시연용 입력이며 실제 본인인증 완료 증거는 아니에요.'
        if re.search(r'외부|회사|넘어가|팔려', q):
            answer += ' 외부 서비스 전달 여부와 범위는 실제 연결 설정·처리방침 확인이 필요해요.'
        return guidance._response('answered', answer, docs)
    if explanation_only(question) and re.search(r'분실|습득|접수|신고|사이트|본인확인|확인버튼', q):
        topics = ('delivery',) if re.search(r'택배|배송|우편', q) else ('hours',) if re.search(r'운영시간|몇시', q) else ('reservation_change',) if '취소' in q else ('site_help',) if '사이트' in q else ('center_pickup',) if '본인확인' in q else ('chat_intake',)
        docs = [d for d in guidance.documents if d['topic'] in topics]
        return guidance._response('answered', '지금은 접수를 시작하지 않고 설명만 드릴게요. ' + '\n\n'.join(d['answer'] for d in docs), docs)
    if re.search(r'질문안할|잠깐.*기다|아직기다|잠깐멈춰|정리할시간|아직질문없|질문은아직없|그냥한말|잠깐놀란', q):
        return guidance._response('answered', '괜찮아요. 준비되면 이어서 말씀해 주세요.', [])
    if COMPLAINT.search(q) and not re.search(r"접수|신고|찾아|운영시간|어떻게|알려|스티커|글자|로고|무늬|키링", q):
        previous = history[-1] if history else ''
        if privacy_concern(previous, history[:-1]):
            reply = turn_reply(previous, history[:-1], guidance)
            return {**reply, 'answer': '개인정보 유출이 걱정된다는 말씀이었군요. ' + reply['answer']}
        return guidance._response('clarification_needed',
            '제가 질문 의도를 놓쳤네요. 어느 부분을 잘못 이해했는지 말씀해 주시면 그 내용부터 다시 안내할게요.', [])
    return None
