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

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/guidance/knowledge.json"
ALLOWED = {"docs/design/usecases.md", "docs/design/database.md", "docs/guidance/site-help.md"}
APPROVED_CORPUS_SHA256 = 'fea3d43ea8819cd8e3b428c89a6a122923a5eeaee52c2e4698c2d3ca073ff3b7'
SUGGESTIONS = [
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
        q = re.sub(r"\s+", "", q)
        if (re.search(r"찾아\s*줘|찾아주세요|검색해|후보.*보여|내\s*물건.*있|접수번호.*조회", q)
                and not re.search(r"방법|절차|안내|운영|보관|수령|어떻게|사용법|이용법|설명확인|버튼", q)):
            return self._response("item_search_not_supported", "이 안내 챗봇에서는 물건을 검색하지 않습니다. 위의 분실물 설명 입력과 기존 찾기 절차를 이용해주세요.", [])
        topics, gaps = set(), []
        if re.search(r"몇시|운영시간|운영시각|영업|주말|토요일|일요일|평일|공휴일|휴일|open|오픈|문.*(?:열|닫)|센터.*(?:열|닫)|방문.*시간", q):
            gaps.append("운영시간")
        finder = bool(re.search(r"습득자|주운\s*사람|주워|맡긴\s*사람", q))
        claimant = bool(re.search(r"분실인|잃어버린사람|내(?:개인)?정보|내신분", q))
        period = bool(re.search(r"보관|며칠|몇일|기간|파기|폐기|삭제|지워|지우|30일|언제까지|한달|한개월|[0-9]+(?:일|개월|달|년)(?:뒤|후)|맡아", q))
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
        if re.search(r"사용법|이용법|설명입력|설명정리|설명확인|후보검색버튼|조건지우|사진.*(?:올|입력)|음성|녹음|마이크|사이트.*(?:사용|이용)|검색.*방법|찾는방법", q):
            topics.add("site_help")
        if re.search(r"개인정보|신분정보|신분증.*저장|신분증.*보관", q) and (not finder or claimant):
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
            return self._response("not_found", "현재 안내 문서에서 답을 찾지 못했습니다. 수령 절차·동의·신분정보 저장 방식 중 궁금한 내용을 구체적으로 질문해주세요.", [])
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
