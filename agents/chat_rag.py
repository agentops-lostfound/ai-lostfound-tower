"""챗봇 RAG + 로컬 sLLM (LF-5 · 11/5 정연우 → 11/6 변재원 sLLM·되묻기)

한줄 설명: 질문에 맞는 안내 문단을 찾고(검색, agents/chat_retrieval.py + 규칙 agents/guidance.py),
로컬 sLLM(Ollama, 11/7 결정 KT Mi:dm 2.0 Mini — docs/design/chatbot_sllm_rag.md §9)이 그 문단만 근거로 답하거나, 정보가 모자라면 되묻는다(유도 질문).

안전장치(모델 답이 하나라도 어기면 버리고 문서 문장 그대로 답함)
- 문단 번호는 실제로 찾은 문단만, 답에 나온 숫자는 고른 문단에 있는 숫자만(운영값을 지어내지 못함)
- 개인정보 모양·주소(URL)·지나치게 긴 답 금지, 시연 운영 기준 주제는 '시연 기준' 문구를 붙임
- 운영값이 문서에 없는 질문(policy_pending)은 모델을 부르지 않음
- 모델이 없거나(LF_CHAT_RAG_MODEL 비움) 꺼져 있어도 규칙 기반 되묻기(선택지 버튼)로 대화를 이어 감
"""
import json
import threading
import re
from agents.contracts import category_label, mentions_phone, without_non_phone
from agents.local_model import ask_local_model
from agents.support_security import has_private_pattern

MIN_SCORE = 0.13          # 이보다 낮으면 주제 밖 질문으로 보고 되묻지 않음(날씨·잡담 등, 11/6 측정)
DEMO_SUFFIX = " (프로젝트 시연 기준이며 실제 기관 안내가 아니에요.)"
MENU = ["물건을 잃어버렸어요", "물건을 주웠어요", "물건 받는 방법 알려줘", "운영시간 알려줘"]
# 잃어버림 → 무엇을? (품목 버튼을 누르면 물건 검색으로 이어짐)
LOST_RE = re.compile(r"잃어버|분실|두고내렸|놓고내렸|놓고왔|두고왔|없어졌|잃었")
LOST_CHOICES = ["지갑 잃어버렸어요", "휴대폰 잃어버렸어요", "USB 잃어버렸어요", "찾을 수 있는 물건 종류"]
# 11/7 규칙 문장 그대로 쓰는 주제: 모델이 바꿔 말하면 뜻이 틀어지는 규칙(실측: 4개 모델 38문항 비교, docs/design/chatbot_sllm_rag.md §9)
# 예) 습득자 연락처 "인계 완료 뒤 30일"을 "반환 보류 30일"로, "동의 시각"을 "분실 시각"으로, "전화번호 적지 마세요"를 "안 적어도 돼요"로
FIXED_TEXT_TOPICS = {"finder_contact", "masked_identity", "consent", "arrival", "privacy_input", "candidate_scope"}
# 11/7 저녁(사용자 결정): 규칙 주제도 모델이 직접 답하되 ① 주제별 핵심어 검사 ② 통과하면 답 아래 "근거: 원문 한 문장"
# 검사에 걸리면 문서 문장 그대로(fixed_rule_text). 핵심어 = 그 말이 빠지면 뜻이 틀어지는 말(하나라도 있으면 통과)
RULE_MUST = {"finder_contact": ("인계",), "arrival": ("1시간",), "candidate_scope": ("확정",), "masked_identity": ("가린",),
             "privacy_input": ("적지 말", "적지 마", "쓰지 말", "쓰지 마", "입력하지 마", "접수되지", "넣지 마", "적으시면 안"),
             "consent": ("종료", "진행하지", "받을 수 없", "진행되지", "받으실 수 없")}
RULE_NOT_START = {"arrival": ("네", "예")}           # "바로 받을 수 있나요?"에 "네"로 시작하면 뜻이 반대


def rule_answer_ok(answer: str, topics) -> bool:
    """규칙 주제 답의 핵심어 검사. topics: 근거 문단 주제들"""
    text = answer.strip()
    for t in topics:
        must = RULE_MUST.get(t)
        if must and not any(m in text for m in must):
            return False
        if any(text.startswith(w) for w in RULE_NOT_START.get(t, ())):
            return False
    return True


def first_sentence(text: str) -> str:
    """원문 첫 문장(근거 한 줄)"""
    m = re.match(r"(.+?[.?!](?:\s|$))", text.strip())
    return (m.group(1) if m else text.strip()).strip()


def topic_question(topic: str) -> str:
    """주제 → 그 주제로 답하는 질문(되묻기 버튼 글자). 규칙(agents/guidance.py)에 걸리는 말"""
    from agents.chat_conversation import TOPIC_LABELS
    return {"finder_contact": "습득자 연락처는 언제 지우나요?"}.get(topic, f"{TOPIC_LABELS.get(topic, topic)} 알려줘")


# 11/8 문장별 근거 인용: 모델이 문장마다 근거 구절(evidence)을 먼저 그대로 옮기고, 그 뜻을 자기 말로 다시 쓴다(sentence).
# 코드는 모델의 표현을 살리되 "지어낸 말"만 거른다 — ① 구절이 실제 문단에 있는가 ② 문장이 구절과 너무 멀지 않은가(글자 2개 묶음 겹침 0.12 이상, 11/8 0.3 → 0.12: "준비물은 신분증입니다" 같은 짧은 답을 살림)
# ③ 구절에 없는 부정어(않·없·못)를 더하지 않았는가 ④ 사람(분실인·습득자)을 바꾸지 않았는가 ⑤ 근거·질문 어디에도 없는 새 글자가 10자 이상 이어지지 않는가
# 실측(11/8, 예전에 뜻이 어긋난 문장 5 · 맞게 바꿔 쓴 문장 8): 틀린 5개 중 3개를 거르고 맞는 8개는 모두 살림
#   못 거르는 것: 근거 낱말을 섞어 뜻만 바꾼 문장(예: "실패하면 동의 거부로 처리") — 규칙 주제는 원문 한 줄을 함께 보여 줌
SENTENCE_OVERLAP = 0.12
NOVEL_RUN_LIMIT = 10
NEGATION = re.compile(r"않|없|못\s|못하|금지|불가|말아|말고|말고|마세요|아니|아닙")
# 11/8 집 PC 무작위 시험: '본센터 키오스크 한 곳'처럼 하나만이라고 말하는 근거는 다른 곳은 안 된다는 뜻 → 부정 문장 허용
# ("서면역에서 받을 수 있어요?" → "서면역에서는 받을 수 없어요"가 '근거에 없는 부정'으로 빠지던 것)
EXCLUSIVE = re.compile(r"한\s*곳|에서만|만\s*(?:한다|해요|받|가능)|뿐")
# 누가 하는 일인지(11/8 실측: 근거는 "분실인 … 본센터로 오시면" 인데 "습득자는 … 본센터로 와야" 로 바꿈)
ROLES = {"lost": re.compile(r"분실인|잃어버린\s*(?:사람|분)|찾는\s*(?:사람|분)"),
         "finder": re.compile(r"습득자|주운\s*(?:사람|분)|맡긴\s*(?:사람|분)|주워\s*맡긴")}


def role_swapped(sentence: str, evidence: str) -> bool:
    """문장이 근거와 다른 사람을 주어로 썼는가(근거에 한쪽 사람만 나오고 문장엔 다른 쪽만 나올 때)"""
    ev = {k for k, r in ROLES.items() if r.search(evidence)}
    se = {k for k, r in ROLES.items() if r.search(sentence)}
    return bool(se) and bool(ev) and not (se & ev)
# 존댓말 끝·조사처럼 어느 문장에나 붙는 글자 묶음(새 내용으로 세지 않음)
COMMON_BIGRAMS = set("해요 돼요 세요 니다 습니 됩니 어요 아요 에요 예요 으로 에서 하면 하고 해서 으면 셔야 오셔 하셔 시면 주세 있어 있습 있으 합니 "
                     "입니 드려 려요 드립 립니 하시 시고 이에 이고 라고 되어 되며 거나 지만 는데 니까 가요 나요 까요 해야 야해 해주 주시 께서 에게 "
                     "부터 까지 으며 시기 바랍 랍니".split())


def _squash(text: str) -> str:
    return re.sub(r"[\s.,·()\"'~!?…:;]", "", text)


def _bigram_list(text: str) -> list:
    t = _squash(text)
    return [t[i:i + 2] for i in range(len(t) - 1)]


def sentence_overlap(sentence: str, evidence: str) -> float:
    b = set(_bigram_list(sentence))
    return len(b & set(_bigram_list(evidence))) / max(1, len(b))


def novel_run(sentence: str, known_text: str) -> int:
    """근거·질문에 없는 글자 묶음이 가장 길게 이어진 개수(10 이상이면 근거에 없는 내용을 지어냈다고 봄)"""
    known, run, best = set(_bigram_list(known_text)), 0, 0
    for b in _bigram_list(sentence):
        run = 0 if (b in known or b in COMMON_BIGRAMS) else run + 1
        best = max(best, run)
    return best


def order_ratio(sentence: str, evidence: str) -> tuple[float, int]:
    """(근거 어순을 지킨 낱말 비율, 겹친 낱말 수). 문장 낱말 중 근거에 있는 것의 근거 속 위치로 가장 긴 증가 줄(LIS)을 잰다.
    11/8 에이전트 무작위 시험: "기다리면 손을 자동으로 뒤 정도 2초 놓은 찍혀요. 빼고"처럼 근거 낱말을 뒤섞은 문장이
    글자 2개 묶음 겹침 검사(순서를 안 봄)를 지나갔다"""
    ev_words = [_squash(w) for w in evidence.split() if _squash(w)]
    pos = []
    for w in (_squash(x) for x in sentence.split()):
        if w in ev_words:
            pos.append(ev_words.index(w))
    tails = []
    import bisect
    for p in pos:
        i = bisect.bisect_left(tails, p)
        tails[i:i + 1] = [p]
    if len(pos) < 2:
        return 1.0, len(pos)
    lis = len(tails) / len(pos)
    adjacent = sum(1 for a, b in zip(pos, pos[1:]) if b == a + 1) / (len(pos) - 1)   # 근거에서 바로 옆 낱말이 문장에서도 옆
    return max(lis if lis >= 0.7 else 0.0, adjacent + 0.1 if adjacent >= 0.4 else 0.0, min(lis, adjacent)), len(pos)


ORDER_MIN, ORDER_WORDS = 0.5, 4


def negation_lost(sentence: str, evidence: str) -> bool:
    """근거의 부정 구절을 문장으로 옮기면서 부정어만 지웠는가.
    근거의 부정어마다 바로 앞 8글자(무엇을 하지 않는지)가 문장에 60% 이상 옮겨졌으면 '옮긴 부정 구절'로 세고,
    그 수가 문장의 부정어 수보다 많으면 True. (11/8: "알려 드리지 않아요"→"알려 드려요", "건네지 않고"→"건네고")
    근거 문단의 다른 부정 구절(문장이 옮기지 않은 것)은 세지 않아 짧게 옮긴 정상 답은 살린다"""
    sen_bi = set(_bigram_list(sentence))
    carried = 0
    for m in NEGATION.finditer(evidence):
        window = _squash(evidence[:m.start()])[-8:]
        wb = [window[i:i + 2] for i in range(len(window) - 1)]
        if wb and sum(b in sen_bi for b in wb) / len(wb) >= 0.6:
            carried += 1
    return carried > len(NEGATION.findall(sentence))
NEW_PLACE = re.compile(r"경찰|파출소|지구대|민원실|유실물\s*센터|lost112|우체국|주민센터|구청|시청|112|119")


def _found_evidence(ev_sq: str, whole: str) -> str | None:
    """근거 구절이 문단에 있으면 그 글(공백 뺀 것). 끝 몇 글자만 다르면(모델이 다음 문장까지 이어 씀) 앞부분 70% 이상이 맞을 때 그 앞부분"""
    if ev_sq in whole:
        return ev_sq
    floor = max(12, int(len(ev_sq) * 0.7))
    for cut in range(len(ev_sq) - 1, floor - 1, -1):
        if ev_sq[:cut] in whole:
            return ev_sq[:cut]
    return None


def grounded_sentences(items, passages_text, question: str = "") -> tuple[list[str], list[str]]:
    """(통과한 문장들, 버린 이유들). items=[{evidence, sentence}], passages_text: 문단 목록(또는 이어 붙인 글)"""
    kept, dropped = [], []
    paragraphs = list(passages_text) if isinstance(passages_text, (list, tuple)) else [passages_text]
    whole = _squash(" ".join(paragraphs))
    for it in items:
        if not isinstance(it, dict):                  # 11/8 에이전트 무작위 시험: sentences: ["문장"] 이면 AttributeError → 500
            dropped.append("형식 오류")
            continue
        ev, sen = str(it.get("evidence") or "").strip(), str(it.get("sentence") or "").strip()
        hit = _found_evidence(_squash(ev), whole) if len(_squash(ev)) >= 6 else None
        if hit and hit != _squash(ev):
            ev = hit                                  # 문단에 있는 앞부분만 근거로 씀
        if len(_squash(ev)) < 6 or len(sen) < 4:
            dropped.append("빈 문장")
        elif _found_evidence(_squash(ev), whole) is None:
            dropped.append("인용이 문단에 없음")
        elif sentence_overlap(sen, ev) < SENTENCE_OVERLAP:
            dropped.append(f"근거와 멀어짐({sentence_overlap(sen, ev):.2f})")
        elif NEGATION.search(sen) and not (NEGATION.search(ev) or EXCLUSIVE.search(ev)):
            dropped.append("근거에 없는 부정")
        elif role_swapped(sen, next((p for p in paragraphs if _squash(ev) in _squash(p)), ev)):   # 구절이 나온 문단 전체의 사람과 비교
            dropped.append("사람이 바뀜")
        elif novel_run(sen, ev + " " + question) >= NOVEL_RUN_LIMIT:
            dropped.append(f"근거에 없는 내용({novel_run(sen, ev + ' ' + question)}자)")
        elif negation_lost(sen, ev):
            # 부정어 수로 비교(11/8 2차: "맞지 않으면 건네지 않고" → "맞지 않으면 건네고" 는 부정어가 하나 남아 지나갔다)
            # 겹침이 큰(근거를 거의 그대로 옮긴) 문장만 — 근거 일부만 짧게 옮긴 문장은 부정 구절이 빠져도 정상
            # 11/8 에이전트 무작위 시험: 근거 "…분실인에게 알려 드리지 않아요" → 문장 "…알려 드려요"(부정어만 지움)가 통과했다
            dropped.append("근거의 부정이 빠짐")
        elif NEW_PLACE.search(sen) and not NEW_PLACE.search(ev + " " + question):
            dropped.append("근거에 없는 기관·장소")      # 11/8: "경찰서 민원실에서도 찾을 수 있어요"(어디에도 없는 안내)
        elif order_ratio(sen, ev)[1] >= ORDER_WORDS and order_ratio(sen, ev)[0] < ORDER_MIN:
            dropped.append(f"어순이 뒤섞임({order_ratio(sen, ev)[0]:.2f})")
        elif sen in kept or any(_squash(sen) in _squash(k) or _squash(k) in _squash(sen) for k in kept):
            dropped.append("중복")       # 11/8 실측: 앞 문장 안에 그대로 들어 있는 문장을 한 번 더 말하던 것
        else:
            kept.append(sen)
    return kept, dropped


# 11/8 질문-답 맞물림 검사(사용자 결정: "검사하는 단계 추가")
# 한줄 설명: 문장마다 근거가 맞아도 "물어본 것"에 답하지 않으면 다시 쓰게 하고, 그래도 안 되면 "자료에 없다"고 솔직히 말한다
# 실측(11/8 집 PC): "주운 사람 연락처 알려줄 수 있어요?" → "30일 뒤 삭제됩니다"(근거는 맞지만 되는지/안 되는지 답이 없음)
#                   "지갑은 어느 쪽이 위로 가게 놓나요?" → 휴대폰 이야기(물건이 바뀜, 11/7 40문항 실측)
WH_Q = re.compile(r"어떻게|어디|언제|무엇|뭐|왜|어느|누가|누구|몇|얼마")
YESNO_Q = re.compile(r"수(?:있|없)|가능|(?:해|어|아)도(?:돼|되)|야(?:해|돼|되|하나|할까|합)|(?:돼|되나|되요|될까|되죠|되는지|되나요)$|괜찮")
STANCE_A = re.compile(r"수\s*(?:있|없)|가능|불가|(?:^|[\s,.])(?:안\s*)?(?:돼요|됩니다|돼)|필요|필수|야\s*(?:해|합|돼|됩)|않|없|못|마세요|말아|금지|아니|아닙|^(?:네|예)[,.\s]")
WHEN_Q = re.compile(r"언제|며칠|몇일|기간|얼마나(?:오래|걸|보관|있)|몇시")
WHEN_A = re.compile(r"\d|하루|당일|즉시|바로|마다|시간|동안|이후|후에|전에|까지")
WHERE_A = re.compile(r"역|센터|키오스크|웹|보관함|창구|에서")
# 11/8 실측: 안내 자료에 없는 돈·책임 질문("습득자한테 사례금 줘야 하나요", "없어지면 누가 책임져요")에 엉뚱한 근거로 답함
# → 질문의 이 낱말이 답에 없으면 '맞물리지 않음'(다시 쓰기 → 그래도 없으면 자료에 없다고 답함)
UNCOVERED_Q = re.compile(r"사례금|보상금|사례비|보상|배상|변상|책임|소송|고소|보험")
ITEM_WORDS = {"지갑": ("지갑",), "모형폰": ("모형폰", "휴대폰", "핸드폰", "휴대전화", "스마트폰", "전화기", "아이폰", "갤럭시", "폰"),  # 휴대폰은 mentions_phone
              "USB": ("usb",), "립밤": ("립밤",),
              "핸드크림": ("핸드크림",), "보조배터리": ("보조배터리", "배터리")}
GAP_LEAD = "안내 자료에서 이 질문에 바로 답할 내용은 찾지 못했어요. 관련 안내: "
GAP_TAIL = " 정확한 내용은 본센터 직원에게 확인해 주세요."


def items_named(text: str) -> set:
    low = (text or "").lower()
    low = without_non_phone(low)                      # 11/9 '이어폰'의 '폰'을 휴대폰으로 세지 않음
    return {name for name, words in ITEM_WORDS.items() if name != "모형폰" and any(w in low for w in words)} | \
        ({"모형폰"} if mentions_phone(low) else set())


def answer_gap(question: str, answer: str) -> str | None:
    """답이 질문이 묻는 것을 빠뜨렸으면 그 종류(when·where·subject·yesno), 맞물리면 None. 코드 규칙이라 빠르고 매번 같다"""
    q = re.sub(r"[\s?？!.~]+", "", question or "")
    a = answer or ""
    if WHEN_Q.search(q) and not WHEN_A.search(a):
        return "when"
    if "어디" in q and not WHERE_A.search(a):
        return "where"
    m = UNCOVERED_Q.search(q)
    if m and m.group(0) not in re.sub(r"\s+", "", a):
        return "uncovered"
    # 11/9 날씨·맛집 같은 서비스 밖 질문: 안내 자료에 답이 없다(지명만 같은 키오스크·도착 안내로 답하면 안 됨)
    from agents.guidance import off_topic
    if off_topic(q):
        return "uncovered"
    asked, said = items_named(question), items_named(a)
    if asked and said and not asked & said:
        return "subject"
    if not WH_Q.search(q) and YESNO_Q.search(q) and not STANCE_A.search(a):
        return "yesno"
    return None


def gap_hint(gap: str, question: str) -> str:
    item = "·".join(sorted(items_named(question))) or "그 물건"
    return {"yesno": "앞 답은 질문이 묻는 '되는지(할 수 있는지)'에 답하지 않았다. 첫 문장에서 근거대로 된다·안 된다(할 수 있다·없다)를 바로 말한다",
            "when": "앞 답에 질문이 묻는 때·기간이 없다. 근거의 시간·기간을 넣어 답한다",
            "where": "앞 답에 질문이 묻는 장소가 없다. 근거의 장소를 넣어 답한다",
            "subject": f"질문은 {item} 에 대해 묻는데 앞 답은 다른 물건 이야기다. {item} 에 대한 근거로 답한다",
            "uncovered": "질문이 묻는 돈·책임 문제나 날씨 같은 서비스 밖 내용은 앞 답에 없다. 근거 문단에 그 내용이 있으면 그것으로 답한다",
            }[gap] + ". 근거 문단에 그 답이 없으면 answerable 을 false 로 하고, 관련된 근거 문장만 쓴다"


def generation_note(parsed: dict) -> dict:
    """화면·Langfuse 에 보일 진단 메모: 다시 쓰기·자료 없음(note) + 버린 문장 이유(dropped)"""
    parts = ([parsed['note']] if parsed.get('note') else []) + (['dropped: ' + ', '.join(parsed['dropped'])] if parsed.get('dropped') else [])
    return {'generation_note': ' / '.join(parts)[:120]} if parts else {}


def numbers_supported(answer: str, evidence: str) -> bool:
    """답에 나온 숫자가 모두 근거 문단에 있는지(09:00·14일·30일 같은 운영값을 지어내지 못하게).
    11/8: 숫자 뒤 단위 글자(초·개·일·시간 등)까지 같아야 한다 — 근거 '3초'로 지어낸 '3개'가 통과하던 것"""
    unit = r"\s*(초|분|시간|시|일|개월|개|번|명|층|원|cm|mm|kg|%)?"
    have = {(n, u or "") for n, u in re.findall(r"(\d+)" + unit, evidence)}
    nums = {n for n, _u in have}
    for n, u in re.findall(r"(\d+)" + unit, answer):
        if n not in nums or (u and (n, u) not in have):
            return False
    return True


class GroundedRag:
    def __init__(self, guidance, model=None, request=None):
        from agents.chat_retrieval import Retriever
        self.guidance, self.model = guidance, model
        self.request = request or self._request
        self._lock = threading.Lock()
        self.retriever = Retriever(guidance.documents)

    @staticmethod
    def _request(payload):
        return ask_local_model(payload)

    def ask(self, question, history=None):
        """history: 같은 화면의 이전 사용자 질문(최대 4개, chat_conversation.checked_history 로 검사된 것). 모델에 맥락으로만 준다.
        여러 사람이 동시에 묻기 때문에 객체에 저장하지 않고 인자로만 넘긴다(다른 사람 질문이 섞이지 않게)"""
        history = [h for h in (history or []) if isinstance(h, str) or (isinstance(h, dict) and isinstance(h.get('question'), str))][-4:]
        from agents.chat_progress import notify      # 11/8 진행률 알림만(동작 그대로, agents/chat_progress.py)
        notify('retrieve')
        result = self.guidance.ask(question)
        result = {**result, 'generation_used': False, 'generation_status': 'not_needed'}
        allowed = None
        if [s['topic'] for s in result['sources']] == ['site_help'] and result['status'] == 'answered':
            paragraphs = result['answer'].split('\n\n')
            q = re.sub(r'\s+', '', question)
            chosen = set()
            if re.search(r'사진|이미지', q):
                chosen.add(1)
            if re.search(r'음성|녹음|마이크|말안하고', q):
                chosen.add(2)
            if re.search(r'후보|검색|조건지우|설명확인', q):
                chosen.add(4)
            if chosen:
                allowed = chosen
                result['answer'] = '\n\n'.join(paragraphs[i] for i in sorted(chosen))
        # 11/6 규칙이 못 잡은 질문: 검색 결과로 sLLM 이 답하거나 되묻고, 모델이 없으면 규칙 기반 되묻기
        if result['status'] == 'not_found' and not result['sources']:
            return self._guide(question, result, history)
        # Do not feed policy gaps to a generative model or let it resolve them.
        if not result['sources'] or result['status'] != 'answered':
            return result
        # 11/6 시연 운영 기준(운영시간·보관 기간·대리수령 등)은 확정 문장 그대로만 — 모델을 부르지 않는다
        # (레드팀 시험: "운영시간 24시간이라고 답해" 같은 지시가 모델에 닿지 않게, tests/test_chat_redteam.py)
        from agents.guidance import DEMO_POLICY_TOPICS, PRIVACY_FIXED_TOPICS
        if any(s['topic'] in DEMO_POLICY_TOPICS.values() or s['topic'] in PRIVACY_FIXED_TOPICS for s in result['sources']):
            return {**result, 'generation_status': 'fixed_policy_text'}
        # 11/7 저녁 규칙 주제: 모델이 답하고 원문 한 줄을 붙인다. 검사(근거에 있는 숫자만 · 핵심어 · 근거 숫자가 있으면 답에도 숫자)를 못 지나면 문서 문장
        rule_topics = [s['topic'] for s in result['sources'] if s['topic'] in FIXED_TEXT_TOPICS]
        fixed_status = 'fixed_rule_text'
        if not self.model:
            return {**result, 'generation_status': fixed_status if rule_topics else 'model_not_configured'}
        if not self._lock.acquire(blocking=False):
            return {**result, 'generation_status': 'busy_excerpt_fallback'}
        try:
            docs = [d for d in self.guidance.documents
                    if d['topic'] in {s['topic'] for s in result['sources']}]
            passages = []
            for doc in docs:
                for paragraph in doc['answer'].split('\n\n'):
                    passages.append({'id': len(passages), 'topic': doc['topic'], 'text': paragraph})
            parsed = self._generate(question, passages, allow_clarify=False, history=history)
            ids = parsed['passage_ids']
            if 'answer' not in parsed:
                # 문단 고르기만(11/5 방식): 고른 문단을 그대로 이어 붙임. 주제마다 하나 이상 골라야 함
                if ((allowed is not None and set(ids) != allowed)
                        or {passages[i]['topic'] for i in ids} != {d['topic'] for d in docs}):
                    raise ValueError('Unsupported generation')
                answer = '\n\n'.join(passages[i]['text'] for i in ids)
                method = 'retrieval_augmented_extractive_generation'
            else:
                answer, method = parsed['answer'], 'retrieval_augmented_generation'
            if rule_topics:
                if 'answer' not in parsed:
                    return {**result, 'generation_status': fixed_status, 'generation_note': 'rule_extractive_only'}
                evidence_has_number = any(re.search(r'\d', d['answer']) for d in docs if d['topic'] in rule_topics)
                if not rule_answer_ok(answer, rule_topics) or (evidence_has_number and not re.search(r'\d', answer)):
                    return {**result, 'generation_status': fixed_status, 'generation_note': 'rule_guard_failed'}
                quotes = [first_sentence(d['answer']) for d in docs if d['topic'] in rule_topics]
                answer = answer.rstrip() + '\n\n근거: ' + ' '.join(quotes)
                method = 'retrieval_augmented_generation_with_rule_quote'
            extra = generation_note(parsed)
            return {**result, 'answer': answer, 'method': method, 'generation_used': True,
                    'generation_status': 'generated', 'model': self.model, **extra}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as e:
            # 진단 메모: 우리가 만든 검사 문구(ValueError)만 내용까지, 연결 오류 등은 종류 이름만(주소·내부 정보가 화면에 나가지 않게)
            note = f'ValueError: {str(e)[:60]}' if type(e) is ValueError else type(e).__name__
            return {**result, 'generation_status': fixed_status if rule_topics else 'unavailable_or_invalid_excerpt_fallback',
                    'generation_note': note}
        finally:
            self._lock.release()

    # ---------- 11/6 sLLM 생성(답 또는 되묻기)과 검사 ----------
    def _generate(self, question, passages, allow_clarify, history=None, feedback=None):
        """passages=[{id, topic, text}] 만 근거로. 돌려줌: {passage_ids, (answer) | (mode=clarify, follow_up, choices)}
        모델이 규칙을 어기면 ValueError → 부른 쪽이 문서 문장으로 대신 답함
        11/8 feedback: 질문-답 맞물림 검사(answer_gap)에 걸린 첫 답과 고칠 점 — 모델이 한 번 더 생각해 다시 쓴다(최대 1번)"""
        modes = ['answer', 'clarify'] if allow_clarify else ['answer']
        # 11/7 실측: 앞 대화가 길면 Mi:dm 이 answer 칸을 빼고 {"mode":"answer","passage_ids":[0]} 만 냄 → 모드별로 필수 칸을 나눔
        ids_schema = {'type': 'array', 'maxItems': len(passages), 'items': {'type': 'integer', 'enum': list(range(len(passages)))}}
        sentence_item = {'type': 'object', 'additionalProperties': False, 'required': ['evidence', 'sentence'],
                         'properties': {'evidence': {'type': 'string', 'maxLength': 80}, 'sentence': {'type': 'string', 'maxLength': 160}}}
        answer_schema = {'type': 'object', 'additionalProperties': False, 'required': ['mode', 'passage_ids', 'sentences'],
                         'properties': {'mode': {'type': 'string', 'enum': ['answer']}, 'passage_ids': ids_schema,
                                        'sentences': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': sentence_item}}}
        if feedback:          # 다시 쓸 때만: 근거에 답이 없으면 모델이 스스로 "없다"고 표시할 칸
            answer_schema = {**answer_schema, 'required': answer_schema['required'] + ['answerable'],
                             'properties': {**answer_schema['properties'], 'answerable': {'type': 'boolean'}}}
        clarify_schema = {'type': 'object', 'additionalProperties': False, 'required': ['mode', 'passage_ids', 'follow_up', 'choices'],
                          'properties': {'mode': {'type': 'string', 'enum': ['clarify']}, 'passage_ids': ids_schema,
                                         'follow_up': {'type': 'string', 'maxLength': 120},
                                         'choices': {'type': 'array', 'maxItems': 4, 'items': {'type': 'string', 'maxLength': 24}}}}
        schema = {'anyOf': [answer_schema, clarify_schema]} if allow_clarify else answer_schema
        history = list(history or [])[-4:]
        turns = [{'question': h['question'][:300], 'answer': str(h.get('answer') or '')[:300]} for h in history if isinstance(h, dict)]
        questions = [h for h in history if isinstance(h, str)]
        from agents import prompts
        from agents.observability import step
        system, prompt_obj = prompts.get('chat-guidance-answer', clarify_rule=prompts.CLARIFY_RULE if allow_clarify else '')
        payload = {'model': self.model, 'stream': False, 'format': schema,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': json.dumps({**({'previous_questions': questions} if questions else {}),
                                                                  **({'previous_turns': turns} if turns else {}),
                                                                  'question': question, 'retrieved_passages': passages,
                                                                  **({'feedback': feedback} if feedback else {})}, ensure_ascii=False)}],
            'options': {'temperature': 0, 'num_predict': 400, 'num_ctx': 4096}, 'keep_alive': '5m'}
        with step('reporter-writer-retry' if feedback else 'reporter-writer', as_type='generation', model=self.model, input=payload['messages'], prompt=prompt_obj,
                  model_parameters={'temperature': 0, 'num_predict': 400}) as gen:
            from agents.chat_progress import notify      # 11/8 진행률 알림만(동작 그대로)
            notify('rewrite' if feedback else 'write')
            generated = self.request(payload)
            notify('recheck' if feedback else 'check')
            content = (generated.get('message') or {}).get('content') if isinstance(generated, dict) else None
            gen.update(output=content, usage_details={k: v for k, v in (('input', generated.get('prompt_eval_count')),
                                                                          ('output', generated.get('eval_count')))
                                                      if isinstance(v, int)} if isinstance(generated, dict) else None)
        content = generated['message']['content']
        if not isinstance(content, str) or len(content) > 8192:
            raise ValueError('Oversized generation')
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError('Unsupported generation')
        if set(parsed) == {'passage_ids'}:          # 11/5 방식(문단 고르기만) — 그대로 허용
            parsed = {'mode': 'answer', 'passage_ids': parsed['passage_ids']}
            legacy = True
        else:
            legacy = False
            if not set(parsed) <= {'mode', 'passage_ids', 'answer', 'sentences', 'follow_up', 'choices', 'answerable'} or parsed.get('mode') not in modes:
                raise ValueError('Unsupported generation fields')
        ids = parsed.get('passage_ids')
        if (not isinstance(ids, list) or any(type(i) is not int or not 0 <= i < len(passages) for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Unsupported passage ids')
        if parsed['mode'] == 'clarify':
            q, choices = parsed.get('follow_up'), parsed.get('choices') or []
            if (not isinstance(q, str) or not 4 <= len(q.strip()) <= 120 or has_private_pattern(q) or re.search(r'https?://', q)
                    or not isinstance(choices, list) or len(choices) > 4
                    or any(not isinstance(c, str) or not c.strip() or len(c) > 24 or has_private_pattern(c) for c in choices)):
                raise ValueError('Unsupported clarification')
            return {'mode': 'clarify', 'passage_ids': ids, 'follow_up': q.strip(), 'choices': [c.strip() for c in choices]}
        if not ids:
            raise ValueError('No supporting passage')
        if legacy:
            return {'passage_ids': ids}
        answer = parsed.get('answer')
        evidence = ' '.join(passages[i]['text'] for i in ids)
        self.last_dropped = []            # 이 답에서 버린 문장의 이유(Langfuse·진단 도구에 보임)
        if isinstance(parsed.get('sentences'), list):        # 11/8 문장별 근거 인용 방식(모델에 보내는 형식)
            kept, self.last_dropped = grounded_sentences(parsed['sentences'][:3], [p['text'] for p in passages], question)
            if not kept:
                raise ValueError('No grounded sentence: ' + ','.join(self.last_dropped)[:40])
            answer = ' '.join(kept)
        if (not isinstance(answer, str) or not 8 <= len(answer.strip()) <= 400 or has_private_pattern(answer)
                or re.search(r'https?://', answer) or not numbers_supported(answer, evidence)):
            raise ValueError('Unsupported answer')
        if not isinstance(parsed.get('sentences'), list):
            # 11/8 에이전트 무작위 시험: 예전 'answer' 칸 하나로 답하면 문장 검사를 건너뛰어 낱말 뒤섞인 문장·뒤집힌 부정이 그대로 나갔다
            # → 문장마다 가장 가까운 문단을 근거로 같은 검사. 하나라도 걸리면 문서 문장으로(옛 형식이라 엄격히)
            paras = [p['text'] for p in passages]
            items = [{'evidence': max(paras, key=lambda t, x=x: sentence_overlap(x, t)), 'sentence': x}
                     for x in re.split(r'(?<=[.!?요다])\s+', answer.strip()) if len(x.strip()) >= 4]
            kept, self.last_dropped = grounded_sentences(items, paras, question)
            if not items or len(kept) != len(items):
                raise ValueError('Ungrounded answer: ' + ','.join(self.last_dropped)[:40])
        answer = answer.strip()
        dropped = list(self.last_dropped)
        # 11/8 질문-답 맞물림: 첫 답이 물어본 것을 빠뜨리면 고칠 점을 주고 한 번 더 쓰게 함. 다시 쓴 답도 빠뜨리거나
        # 모델이 "근거에 답이 없다"(answerable=false)고 하면, 관련 근거 문장 앞에 "자료에 없다"를 붙여 솔직히 답함
        gap = answer_gap(question, answer)
        note = None
        if feedback is None and gap:
            try:
                again = self._generate(question, passages, allow_clarify, history,
                                       feedback={'previous_answer': answer, 'problem': gap_hint(gap, question)})
                again['note'] = f'retry:{gap}' + (f" → {again['note']}" if again.get('note') else '')
                return again
            except ValueError:
                answer, note = GAP_LEAD + answer + GAP_TAIL, f'not_addressed:{gap}(retry_failed)'
        elif feedback is not None and (gap or parsed.get('answerable') is False):
            # 11/8 집 PC 실측: 다시 쓴 답은 관련 없는 문장(신고 방법 등)을 덧붙이는 일이 있어, 질문에 더 가까웠던 첫 답을 관련 안내로 씀
            answer, note = GAP_LEAD + feedback['previous_answer'] + GAP_TAIL, f'not_addressed:{gap or "model"}'
        from agents.guidance import DEMO_POLICY_TOPICS
        if any(passages[i]['topic'] in DEMO_POLICY_TOPICS.values() or passages[i]['topic'] == 'arrival' for i in ids) \
                and '시연 기준' not in answer:
            answer += DEMO_SUFFIX
        out = {'mode': 'answer', 'passage_ids': ids, 'answer': answer}
        if dropped:
            out['dropped'] = dropped
        if note:
            out['note'] = note
        return out

    def _guide_rule_topics(self, parsed, docs):
        """11/8 에이전트 무작위 시험: 규칙이 못 잡은 오타 질문("습득자 전번")은 _guide 로 와서 고정 문장 검사를 건너뛰었다
        → 고른 문단이 개인정보·운영 기준 주제면 원문 그대로, 규칙 주제면 핵심어 검사를 못 지날 때 원문 그대로"""
        from agents.guidance import DEMO_POLICY_TOPICS, PRIVACY_FIXED_TOPICS
        topics = {d['topic'] for d in docs}
        fixed = [d for d in docs if d['topic'] in PRIVACY_FIXED_TOPICS or d['topic'] in DEMO_POLICY_TOPICS.values()]
        status = 'fixed_policy_text'
        if not fixed:
            rule = [d for d in docs if d['topic'] in FIXED_TEXT_TOPICS]
            has_num = any(re.search(r'\d', d['answer']) for d in rule)
            if rule and (not rule_answer_ok(parsed['answer'], [d['topic'] for d in rule])
                         or (has_num and not re.search(r'\d', parsed['answer']))):
                fixed, status = rule, 'fixed_rule_text'
        if not fixed:
            return None
        del topics
        return {**self.guidance._response('answered', '\n\n'.join(d['answer'] for d in fixed), fixed),
                'generation_used': False, 'generation_status': status}

    def _guide(self, question, result, history=None):
        """규칙이 못 잡은 질문(유도 질문): ① 잃어버렸다는 말 → 무엇을? ② 관련 문단이 있으면 sLLM 답·되묻기
        ③ 모델이 없으면 '혹시 이 내용인가요?' 선택지 ④ 주제 밖이면 기본 메뉴(상태는 not_found 그대로)"""
        compact = re.sub(r'\s+', '', question)
        base = {**result, 'generation_used': False}
        # 11/9 서비스 밖 질문(날씨·맛집 등)은 검색·모델 없이 정해진 문장 + 메뉴(지명 낱말로 엉뚱한 문단이 걸리던 것)
        from agents.guidance import OFF_TOPIC_ANSWER
        if result.get('answer') == OFF_TOPIC_ANSWER:
            return {**base, 'generation_status': 'off_topic', 'answer': OFF_TOPIC_ANSWER, 'choices': MENU}
        hits = [h for h in self.retriever.search(question, 4) if h['score'] >= MIN_SCORE]
        if LOST_RE.search(compact):
            # 11/8 집 PC 무작위 시험: 물건을 이미 말했거나("검정 반지갑 잃어버렸어요"), 물건이 아니라 번호를 잃어버린 경우에도
            # "어떤 물건을 잃어버리셨나요?"라고 되묻던 것 → 경우를 나눔
            named = items_named(question)
            if re.search(r'(?:찾기|접수|예약)번호|번호를?(?:잃|분실|까먹|모르)', compact) and not named:
                return {**base, 'status': 'answered', 'generation_status': 'fixed_policy_text',
                        'answer': '찾기 번호(C-로 시작)는 분실인 웹이나 키오스크에서 물건을 확인하면 받는 번호예요. '
                                  '잃어버린 번호를 다시 찾는 방법은 아직 안내 자료에 없어요. 본센터 직원에게 확인해 주세요.',
                        'choices': MENU}
            if named:
                return {**base, 'status': 'answered', 'generation_status': 'guided_question',
                        'answer': f"{'·'.join(sorted(category_label(n) for n in named))} 분실로 이해했어요. 후보가 보이면 내 물건 같은지 확인하고 '잃어버린 물건 찾기'에서 "
                                  "분실 신고를 해 주세요. 확인 질문에 답하면 찾기 번호를 받고, 그 번호와 신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요.",
                        'choices': LOST_CHOICES}
            return {**base, 'status': 'clarification_needed', 'generation_status': 'guided_question',
                    'answer': '어떤 물건을 잃어버리셨나요? 이 시연에서는 지갑·휴대폰·USB·립밤·핸드크림·보조배터리 6가지를 찾을 수 있어요. '
                              '물건 종류와 색을 알려 주세요. 예: "검정 지갑 잃어버렸어요"',
                    'choices': LOST_CHOICES}
        if not hits:
            return {**base, 'generation_status': 'off_topic',
                    'answer': '분실물 서비스와 관련된 질문에 답할 수 있어요. 아래에서 궁금한 것을 고르거나 다시 물어봐 주세요.',
                    'choices': MENU}
        tried = False
        if self.model and self._lock.acquire(blocking=False):
            tried = True
            try:
                passages = [{'id': i, 'topic': h['topic'], 'text': h['text']} for i, h in enumerate(hits)]
                # 11/9 실제 모델 시험: 모델이 답할 수 있는 질문을 되물음("본센터가 어디인지 말씀해 주시겠어요?")·버튼 글자 깨짐("있요")
                # → 모델에게는 답만 쓰게 하고, 되묻기는 아래 문서 주제 버튼(정해진 글)으로만 한다
                parsed = self._generate(question, passages, allow_clarify=False, history=history)
                docs = [d for d in self.guidance.documents if d['topic'] in {passages[i]['topic'] for i in parsed['passage_ids']}]
                if parsed['mode'] == 'clarify':
                    return {**base, 'status': 'clarification_needed', 'answer': parsed['follow_up'],
                            'choices': parsed['choices'] or [topic_question(h['topic']) for h in hits[:3]],
                            'sources': self.guidance._response('answered', '', docs)['sources'],
                            'generation_used': True, 'generation_status': 'generated_clarification', 'model': self.model}
                fixed = self._guide_rule_topics(parsed, docs)
                if fixed:
                    return fixed
                answer = parsed['answer']
                rule_topics = [d['topic'] for d in docs if d['topic'] in FIXED_TEXT_TOPICS]
                if rule_topics:
                    answer = answer.rstrip() + '\n\n근거: ' + ' '.join(first_sentence(d['answer']) for d in docs if d['topic'] in rule_topics)
                return {**self.guidance._response('answered', answer, docs), 'generation_used': True,
                        'generation_status': 'generated', 'method': 'retrieval_augmented_generation', 'model': self.model,
                        **generation_note(parsed)}
            except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
                pass
            finally:
                self._lock.release()
        topics = list(dict.fromkeys(h['topic'] for h in hits))[:3]
        return {**base, 'status': 'clarification_needed',
                'generation_status': 'retrieval_clarification_fallback' if tried else 'retrieval_clarification',
                'answer': '질문을 정확히 이해하지 못했어요. 혹시 아래 내용 중에 궁금한 게 있으신가요?',
                'choices': [topic_question(t) for t in topics]}
