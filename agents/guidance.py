"""LF-5 extractive document-grounded guidance. No LLM, item DB or external calls.

Answers are curated snippets retrieved from a versioned local corpus. Every
available snippet must have literal evidence in an allowlisted repo document.
Institution operating hours/retention policy are deliberately unavailable.
"""
import json
import re
import threading
import hashlib
from pathlib import Path
from agents.support_security import normalized_text, has_private_pattern
from agents.chat_conversation import natural_question

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/guidance/knowledge.json"
ALLOWED = {"docs/design/usecases.md", "docs/design/database.md", "docs/guidance/site-help.md", "web/README.md",
           "docs/guidance/service-guide.md"}
APPROVED_CORPUS_SHA256 = '557a386c4ee01b3267fd86eb5d82b4810ee04f34e56617357f8b538d52901760'  # 11/5 변재원: service-guide 주제 7개 추가
SUGGESTIONS = [
    ("flow", "분실물 확인은 어디서 할 수 있나요?", ["어디", "확인", "받", "본센터", "키오스크"]),
    ("found_report", "주운 물건은 어떻게 신고하나요?", ["주운", "습득", "신고", "맡기"]),
    ("categories", "어떤 물건을 찾을 수 있나요?", ["물건", "품목", "종류"]),
    ("pickup", "물건을 수령하려면 어떻게 해야 하나요?", ["수령", "찾기", "준비물", "예약"]),
    ("site_help", "사진으로 물건 설명은 어떻게 입력하나요?", ["사진", "설명", "입력", "녹음", "음성", "사용법"]),
    ("identity", "분실인 개인정보는 어떻게 저장하나요?", ["개인정보", "신분증", "정보", "저장"]),
    ("hours", "주말 운영시간은 어떻게 되나요?", ["시간", "영업", "주말", "방문"]),
    ("retention", "분실물 보관기간은 며칠인가요?", ["보관", "기간", "폐기"]),
    ("consent", "본인인증에 실패하면 어떻게 되나요?", ["동의", "인증", "실패"]),
    ("finder", "습득자 연락처는 언제 지우나요?", ["습득자", "연락처", "삭제"]),
]


class Guidance:
    def __init__(self, corpus=CORPUS):
        self._suggestion_counts = {key: 0 for key, _, _ in SUGGESTIONS}
        self._count_lock = threading.Lock()
        with Path(corpus).open('rb') as file:
            raw = file.read(65_537)
        if len(raw) > 65_536:
            raise ValueError('안내 문서 크기가 제한을 초과했습니다')
        self.documents = json.loads(raw)
        digest = hashlib.sha256(json.dumps(self.documents, sort_keys=True, ensure_ascii=False,
                                          separators=(',', ':')).encode()).hexdigest()
        if digest != APPROVED_CORPUS_SHA256:
            raise ValueError('검증된 안내 자료와 내용이 다릅니다. 답변·근거·출처를 함께 검토해주세요')
        if not isinstance(self.documents, list):
            raise ValueError("안내 문서 목록이 올바르지 않습니다")
        for doc in self.documents:
            if doc["path"] not in ALLOWED or not doc["evidence"]:
                raise ValueError("허용된 근거 문서가 필요합니다")
            source = (ROOT / doc["path"]).resolve()
            if ROOT not in source.parents or doc["evidence"] not in source.read_text(encoding="utf-8"):
                raise ValueError("안내 근거가 원본 문서와 일치하지 않습니다")

    def suggestions(self):
        with self._count_lock:
            items = [{"id": key, "text": text, "keywords": words, "count": self._suggestion_counts[key]}
                     for key, text, words in SUGGESTIONS]
        items.sort(key=lambda row: -row["count"])
        return {"items": items, "ranking": "추천 질문 선택 횟수 · 현재 서버 실행 중 집계", "personal_questions_saved": False}

    def record_suggestion(self, suggestion_id, question):
        # Count only exact predefined FAQ choices, never store free-form questions.
        if any(key == suggestion_id and text == question for key, text, _ in SUGGESTIONS):
            with self._count_lock:
                self._suggestion_counts[suggestion_id] = min(1_000_000, self._suggestion_counts[suggestion_id] + 1)

    def ask(self, question):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
            raise ValueError("질문은 1~500자로 입력하세요")
        q = normalized_text(question).lower()
        if not q or len(q) > 500:
            raise ValueError("질문은 1~500자로 입력하세요")
        q = re.sub(r"[\u200b-\u200d\ufeff]", "", q)
        if has_private_pattern(q):
            raise ValueError("이름·연락처·신분번호를 제외하고 안내 사항만 질문해주세요")
        q = natural_question(q)
        q = re.sub(r"\s+", "", q)
        if re.fullmatch(r'(?:안녕(?:하세요|하세용)?|ㅎㅇ|하이|hello|hi|고마워(?:요)?|감사(?:해요|합니다)?)[!?.~ㅋㅎ]*', q):
            return self._response('answered', '안녕하세요! 물건 설명 입력, 후보 검색, 수령 절차를 도와드려요. 예를 들어 “검정 지갑 찾아줘”, “사진은 어떻게 올려요?”라고 물어보세요.', [])
        if re.search(r'뭐할수|무엇을할수|무슨일|기능.*(?:알려|있)|도와줘', q):
            return self._response('answered', '물건 설명 정리·후보 검색·사이트 이용 안내를 도와드려요. 찾는 물건을 적거나, 사진 입력·본인인증·수령 절차 중 궁금한 것을 물어보세요. 현재 가상 DB 시연 결과는 실제 습득물이 아니며 실제 검색에는 인증 연결이 필요해요.', [])
        if (re.search(r"찾아\s*줘|찾아주세요|검색해|후보.*보여|내\s*물건.*있|접수번호.*조회", q)
                and not re.search(r"방법|절차|안내|운영|보관|수령|어떻게|사용법|이용법|설명확인|버튼", q)):
            return self._response("item_search_not_supported", "이 안내 챗봇에서는 물건을 검색하지 않습니다. 위의 분실물 설명 입력과 기존 찾기 절차를 이용해주세요.", [])
        topics, gaps = set(), []
        if re.search(r"몇시|운영시간|운영시각|영업|주말|토요일|일요일|평일|공휴일|휴일|open|오픈|문.*(?:열|닫)|센터.*(?:열|닫)|키오스크.*(?:열|닫)|[0-9]+시간|방문.*시간", q):
            gaps.append("운영시간")
        finder = bool(re.search(r"습득자|주운\s*사람|주워|맡긴\s*사람", q))
        claimant = bool(re.search(r"분실인|잃어버린사람|내(?:개인)?정보|내신분", q))
        # "보관함"(로봇팔이 꺼내는 상자)은 보관 기간 질문이 아니다
        period = bool(re.search(r"보관|며칠|몇일|기간|파기|폐기|삭제|지워|지우|30일|언제까지|한달|한개월|[0-9]+(?:일|개월|달|년)(?:뒤|후)|맡아", q.replace("보관함", "")))
        if period:
            if finder and re.search(r"연락처|전화|이름|개인정보", q):
                topics.add("finder_contact")
            if not finder or claimant:
                gaps.append("분실물 또는 분실인 개인정보의 보관·파기 기간")
        for pattern, label in (
            (r"대리|대신.*(?:받|수령)|가족.*(?:받|수령)", "대리수령 허용 조건"),
            (r"택배|우편|배송", "배송·우편 수령 정책"),
            (r"수수료|요금|비용|얼마|무료", "수령 비용"),
            (r"신분증.*(?:없|분실)|여권|학생증|사진.*대신", "신분증 대체·미지참 처리"),
            (r"예약.*(?:취소|변경)|취소.*예약", "예약 취소·변경 절차"),
            (r"주소|전화번호|연락할|센터위치|어디.*(?:가|받)", "실제 센터 위치·연락처"),
        ):
            if re.search(pattern, q):
                if label == "실제 센터 위치·연락처" and finder and period:
                    continue
                gaps.append(label)
        if re.search(r"수령|돌려받|받으려면|찾으려면|찾는\s*방법|방문|예약|준비물|신분증.*가져", q):
            topics.add("pickup")
        if re.search(r"동의|인증", q):
            topics.add("consent")
        if re.search(r"사용법|이용법|설명입력|설명정리|설명확인|후보검색버튼|조건지우|사진.*(?:올|입력|첨부)|음성|녹음|마이크|사이트.*(?:사용|이용)|검색.*방법|찾는방법", q):
            topics.add("site_help")
        # 11/5 service-guide 주제(docs/guidance/service-guide.md) — 저장소에 정해진 사실만, 미정 운영값은 위 gaps 로
        if re.search(r"어디서.*(?:확인|찾|조회|알아)|(?:확인|조회).*어디서|분실(?:물)?확인|어디서받|받는곳|찾는곳|키오스크.*(?:확인|조회)|(?:웹|챗봇)에서도", q):
            topics.add("flow")
        if re.search(r"로봇|회수|본센터.*(?:받|가|절차|순서)|받는(?:순서|과정|절차)|수령대|보관함", q):
            topics.add("center_pickup")
        if re.search(r"주웠|주운물건|습득신고|습득물.*(?:신고|맡|어디|어떻게)|신고하(?:려|고|는|면)|맡기(?:려|고|는|면)|맡길(?:래|게|수)", q):
            topics.add("found_report")
        if re.search(r"어떤물건|무슨물건|품목|종류|몇종|6종|다루는물건|취급|찾을수있|맡길수있", q):
            topics.add("categories")
        if re.search(r"키오스크.*(?:어디|위치|있는역|몇개|어느)|어느역|등록기계.*(?:어디|위치)", q):
            topics.add("kiosk_places")
        privacy_input = bool(re.search(r"(?:전화번호|주민번호|이메일|연락처|개인정보).*(?:적|써|쓰|입력|넣)", q))
        if privacy_input:
            topics.add("privacy_input")
            if not re.search(r"센터|주소|위치", q):       # 입력 규칙 질문은 센터 연락처 질문이 아니다
                gaps = [g for g in gaps if g != "실제 센터 위치·연락처"]
        if re.search(r"후보.*(?:뭐|무슨|뜻|의미|확정|내물건|맞)|후보가", q):
            topics.add("candidate_scope")
        if re.search(r"개인정보|신분정보|신분증.*저장|신분증.*보관", q) and (not finder or claimant) and not privacy_input:
            topics.add("masked_identity")
            if "개인정보처리" in q:
                gaps.append("운영기관의 전체 개인정보 처리방침")
        # Availability/fees/proxy questions are not answered by an unrelated procedure.
        process_question = re.sub(r"대리수령|택배수령|우편수령", "", q)
        if gaps and not re.search(r"(?:수령|반환|찾는)(?:절차|방법)|준비물", process_question):
            topics.discard("pickup")
        docs = [d for d in self.documents if d["topic"] in topics]
        # Closed-topic lexical retrieval; unknown questions never get a nearest but unrelated answer.
        if not docs and not gaps:
            return self._response("not_found", "질문의 뜻을 정확히 잡지 못했어요. 물건을 찾으시나요, 사이트 사용이 궁금하신가요? ‘검정 지갑 찾아줘’, ‘사진 올리는 법’, ‘수령 준비물’처럼 적어주시면 이어서 도와드릴게요. 운영 문서에 없는 내용은 확인이 필요해요.", [])
        chunks = [d["answer"] for d in docs]
        if gaps:
            chunks.append("현재 확인된 자료에는 " + ", ".join(dict.fromkeys(gaps)) + "의 확정 운영값이 없어 안내할 수 없습니다. 운영 담당자의 확정 안내 문서가 필요합니다.")
        return self._response("partial" if gaps and docs else "policy_pending" if gaps else "answered", "\n\n".join(chunks), docs)

    @staticmethod
    def _response(status, answer, docs):
        return {"status": status, "answer": answer,
                "sources": [{"topic": d["topic"], "title": d["title"], "path": d["path"], "url": d["url"], "evidence": d["evidence"]} for d in docs],
                "scope": "프로젝트 설계 기준 시연 안내 · 운영기관 확정 안내 아님",
                "method": "closed_topic_document_retrieval_and_curated_excerpt",
                "item_search_performed": False}
