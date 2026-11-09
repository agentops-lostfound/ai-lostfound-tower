"""Non-actionable dialogue acts and unknown item names; never invent a product category."""
import re
from agents.chat_conversation import compact, search_intent
from agents.lost_input import text_features
from agents.chat_communication import communication_response, scope_violation

SUPPORTED = '지갑·휴대폰·USB·립밤·핸드크림·보조배터리'


def unknown_loss(question):
    features, _ = text_features(question)
    return (features.get('category') == '확인 불가'
            and bool(re.search(r'잃어버(?:림|렸|려|린|리)|분실했', question)))


def dialogue_response(guidance, question, history):
    q = compact(question)
    actionable = ((text_features(question)[0].get('category') != '확인 불가' and search_intent(question))
                  or guidance.ask(question)['status'] in ('answered', 'partial', 'policy_pending'))
    if re.search(r'시발|씨발|씨바|ㅅㅂ|\u1109\u1107|새끼|병신|좆|답답|말귀.*못|못알아듣', q) and not actionable:
        return {**communication_response(guidance, 'acknowledgement'),
                'answer': '제 답변이 답답하셨겠어요. 같은 인사나 질문을 반복하기보다, 말씀하신 내용에서 무엇을 처리하지 못했는지 짧게 설명드릴게요.'}
    if re.fullmatch(r'(?:아|어|음|흠|하|휴|아하|으음)[.!?？~…]*', q):
        repeated = bool(history and compact(history[-1]) == q)
        return {**communication_response(guidance, 'acknowledgement'),
                'answer': '네.' if repeated else '네, 듣고 있어요. 이어서 말씀해주세요.', 'context_used': bool(history)}
    if re.fullmatch(r'(?:그래|그래요|그런가|그런가요|진짜|정말)[?？]+', q):
        answer = '어떤 부분이 궁금하신가요? 그 부분만 짧게 설명드릴게요.'
        if history and scope_violation(history[-1]):
            answer = '네. 이 챗봇은 일반 정보보다 분실물 찾기와 사이트 이용 방법을 안내하는 용도예요.'
        return {**communication_response(guidance, 'acknowledgement'), 'answer': answer, 'context_used': bool(history)}
    if unknown_loss(question) and guidance.ask(question)['status'] == 'not_found':
        repeated = any(unknown_loss(turn) for turn in history)
        answer = ('말씀하신 이름만으로는 어떤 품목인지 판단하지 못했어요. 현재 검색할 수 있는 품목은 '+SUPPORTED+
                  '입니다. 이 중 어떤 종류인지 알려주시면 검색할 수 있어요. 해당하지 않으면 이 시연에서는 조회를 지원하지 않습니다.')
        if repeated:
            intro = '구매처를 알려주셔도 ' if re.search(r'cu|씨유|편의점|구매|샀|에서산', q) else ''
            answer = (intro+'그 이름을 지원 품목으로 연결하지 못해 조회하지 않았어요. '+SUPPORTED+
                      '만 검색할 수 있으며, 목록 밖 물건 조회는 이 시연에서 지원하는 기능이 아닙니다.')
        result = communication_response(guidance, 'clarification')
        return {**result, 'answer': answer, 'status': 'unsupported' if repeated else 'clarification_needed',
                'context_used': repeated}
    return None
