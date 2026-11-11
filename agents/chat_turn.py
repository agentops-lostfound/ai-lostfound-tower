"""대화 의도 복구. 사용자 말만 참고하며 접수 확인·인증 권한은 만들지 않는다."""
import re

FOUND_SAY = re.compile(r"주웠|주운|주워|주움|줍(?:었|음)|습득|발견했|떨어져\s*있|놓여\s*있")
LOST_SAY = re.compile(r"잃어버|잃었|잊어버|분실|두고\s*내|놓고\s*내")
PRIVATE = re.compile(r"주민(?:등록)?번호|신분증|개인정보|이름|가린\s*번호")
SECURITY = re.compile(r"털리|털려|유출|해킹|도용|위험|불안|안전|괜찮|빼가|새나|새어")
COMPLAINT = re.compile(r"멍청|답답|못\s*알아|말귀|이해\s*못|동문서답|엉뚱|바보")
THEFT = re.compile(r"뺏(?:겼|긴|겨)|빼앗(?:겼|긴|겨)|도난(?:당|신고|[.!?？]*$)|강탈(?:당|신고|[.!?？]*$)|도둑맞|훔쳐(?:갔|감|간|가버)")


def theft_report(question):
    q = re.sub(r"\s+", "", question)
    return bool(THEFT.search(q) and not re.search(r"(?:뺏긴|빼앗긴|도난|강탈).{0,4}(?:아니|아닌)", q))


def privacy_concern(question, history=()):
    if not SECURITY.search(question):
        return False
    # '그거 넣어도 안전해?'는 바로 앞 개인정보 질문에만 연결한다.
    return bool(PRIVATE.search(question) or
                (re.search(r"그거|그걸|입력|넣|보내", question) and history and PRIVATE.search(history[-1])))


def found_statement(question):
    return bool(FOUND_SAY.search(question) and re.search(
        r"(?:주움|줍음|주웠(?:어요|어|다고|는데)?|습득했(?:어요|어)|습득함)[.!~\s]*$", question))


def turn_reply(question, history, guidance):
    """슬롯 추출·모델 호출 전에 처리할 대화. 진행 중인 초안은 변경하지 않는다."""
    if theft_report(question):
        return guidance._response('clarification_needed',
            '누군가 물건을 강제로 가져간 상황인가요? 지금 위험하다면 먼저 안전한 곳으로 이동해 '
            '주변 사람이나 역무실에 도움을 요청해 주세요. 이 챗봇에서는 도난 신고를 접수할 수 없어요. '
            '단순히 물건을 두고 온 상황이라면 그렇게 말씀해 주세요.', [])
    if privacy_concern(question, history):
        docs = [d for d in guidance.documents if d['topic'] in ('privacy_input', 'masked_identity')]
        return guidance._response('answered',
            '실제 주민등록번호는 입력하지 마세요. 이 화면은 교육용 시연이므로 가상 이름과 가상 신분증 숫자만 사용해 주세요. '
            '입력 양식은 이름·번호를 가린 값으로 보내지만, 마스킹만으로 유출 위험이 없다고 보장할 수는 없어요. '
            '프로젝트 DB 설계에는 가린 이름·번호를 기록하도록 되어 있어요.', docs)
    if COMPLAINT.search(question) and not re.search(r"접수|신고|찾아|운영시간|어떻게|알려|스티커|글자|로고|무늬|키링", question):
        previous = history[-1] if history else ''
        if privacy_concern(previous, history[:-1]):
            reply = turn_reply(previous, history[:-1], guidance)
            return {**reply, 'answer': '개인정보 유출이 걱정된다는 말씀이었군요. ' + reply['answer']}
        return guidance._response('clarification_needed',
            '제가 질문 의도를 놓쳤네요. 어느 부분을 잘못 이해했는지 말씀해 주시면 그 내용부터 다시 안내할게요.', [])
    return None
