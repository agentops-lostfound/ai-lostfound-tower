"""저장소 지켜보기(DbWatch) — 통합 시연 화면(/showcase)의 "DB 실시간 기록" 칸 (LF-18, 11/10 변재원)

한줄 설명: 관제탑이 저장소(습득물·찾기 요청·보관 칸·반환 기록)에 쓰거나 읽을 때마다 "어느 표의 어느 칸이 어떤 값이 됐는지"를
진행 기록판(LiveBoard)의 db 사건으로 남긴다. 화면은 그 사건을 받아 표에 행이 생기고 칸이 바뀌는 모습을 그린다.

- 저장소 코드를 고치지 않는다. attach(svc) 가 저장소 객체의 함수(create·set_features·assign …)를 같은 이름의 감싼 함수로 바꿔
  원래 함수를 그대로 부르고, **성공했을 때만** 사건을 남긴다. 메모리 저장소(가상 시연)와 PostgreSQL 저장소(팀 DB) 모두 같은 방식
- 표·칸 이름은 팀 DB(db/migrations)와 같은 이름을 쓴다. 가상 시연은 메모리 저장소지만 같은 표 모양으로 보여 준다(화면에 '메모리'라고 표시)
- 쓰기(INSERT·UPDATE·DELETE)는 모두 남긴다. 읽기(SELECT)는 화면이 0.4초마다 부르는 조회까지 남기면 도배가 되므로
  ① 분실 신고 후보 검색 ② 챗봇 물건 검색 ③ 키오스크 회수·반환 흐름 안에서 일어난 읽기만 남긴다(같은 읽기는 8초 안에 한 번)
- 개인정보: 습득자 이름·전화번호, 가린 신분 번호, 비공개 특징(확인 질문 정답) **값은 사건에 넣지 않는다**(저장됐다는 사실만).
  나머지 글자 값도 observability.mask_text 로 전화번호·주민번호·이메일 모양을 한 번 더 가린다
- 기록 실패는 절대 원래 동작을 막지 않는다(사건 만들기를 모두 감싸 실패하면 조용히 넘김)
"""
from __future__ import annotations

import functools
import threading
import time

from agents.observability import mask_text

# 표 이름 → 화면에 함께 보일 쉬운 이름
TABLES = {
    "item": "습득물", "finder_contact": "습득자 연락처", "item_status_log": "상태 변경 기록",
    "claim": "찾기 요청", "quiz_attempt": "확인 질문 결과", "reservation": "방문 예약",
    "storage_assignment": "보관 칸 배정", "return_case": "반환 기록", "return_step": "반환 단계",
}
# 칸 이름 → 쉬운 이름
COLS = {
    "item_id": "접수 번호", "machine_id": "등록기계", "place_text": "발견 장소", "photo_path": "사진", "status": "상태",
    "category": "품목", "features": "공개 특징", "private_features": "비공개 특징", "name": "이름", "phone": "전화번호",
    "from_status": "이전 상태", "to_status": "바뀐 상태", "changed_by": "바꾼 주체",
    "claim_id": "찾기 번호", "name_masked": "가린 이름", "id_no_masked": "가린 신분 번호", "id_verified": "본인 확인",
    "description": "분실물 설명", "field": "질문 칸", "passed": "통과", "visit_date": "방문 날짜",
    "slot_id": "보관 칸", "assigned_by": "넣은 주체", "case_id": "사례 번호", "decision": "결정", "reason": "이유",
    "approved": "승인", "matched_object": "매칭된 물건", "seconds": "걸린 시간(초)", "step": "단계",
    "where": "찾는 조건", "rows": "찾은 행",
}
FEATURE_LABELS = {"color": "색", "shape": "모양", "mark": "표시", "visible_text": "글자", "material": "재질",
                  "category": "품목", "place": "장소", "brand": "상표"}
SELECT_QUIET_S = 8.0          # 같은 읽기(표·열쇠)는 이 시간 안에 한 번만 남김
VALUE_LIMIT = 120


def _text(v) -> str:
    """값 → 화면 글자(가리고 자름). True/False 는 예/아니오"""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, dict):
        v = " · ".join(f"{FEATURE_LABELS.get(k, k)}={x}" for k, x in v.items() if x not in (None, "", []) and k != "confidence") or "-"
    elif isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v) or "-"
    s = mask_text(str(v))
    return s if len(s) <= VALUE_LIMIT else s[:VALUE_LIMIT - 1] + "…"


def col(name: str, value, changed: bool = False, hidden: bool = False) -> dict:
    """사건의 칸 하나. hidden=True 면 값 대신 '저장됨(가림)' 같은 설명만 넣는다(호출하는 쪽이 설명을 value 로 줌)"""
    return {"name": name, "label": COLS.get(name, name), "value": _text(value), "changed": bool(changed), "hidden": bool(hidden)}


class DbWatch:
    def __init__(self, board):
        self.board = board
        self._local = threading.local()
        self._lock = threading.Lock()
        self._seen: dict[tuple, float] = {}
        self.source = "memory"          # memory(가상 시연·시험) | postgres(팀 DB) — 화면 머리말에 표시

    # ----- 사건 보내기 -----
    def emit(self, table: str, op: str, key: str = "", cols: list[dict] | None = None, by: str = "", note: str = "") -> None:
        if getattr(self._local, "quiet", 0):
            return
        try:
            if op == "SELECT":
                mark, now = (table, key, note), time.monotonic()
                with self._lock:
                    if now - self._seen.get(mark, -1e9) < SELECT_QUIET_S:
                        return
                    self._seen[mark] = now
                    if len(self._seen) > 500:
                        self._seen.clear()
            self.board.db(table, op, key=key, cols=cols or [], by=by, note=mask_text(note), label=TABLES.get(table, table))
        except Exception:
            pass

    # ----- 문맥: 읽기를 남길 구간 · 조용히 할 구간 -----
    def reading(self, label: str, fn):
        """fn 을 부르는 동안 일어난 저장소 읽기를 '무엇을 하다가 읽었는지'(label)와 함께 남긴다"""
        @functools.wraps(fn)
        def run(*a, **k):
            prev = getattr(self._local, "reading", None)
            self._local.reading = prev or label
            try:
                return fn(*a, **k)
            finally:
                self._local.reading = prev
        return run

    def _reading(self) -> str | None:
        return getattr(self._local, "reading", None)

    def quietly(self, fn, after=None):
        """fn 을 부르는 동안 사건을 남기지 않는다(가상 세계 초기화처럼 한꺼번에 여러 칸을 다시 채울 때). 끝나면 after() 한 번"""
        @functools.wraps(fn)
        def run(*a, **k):
            self._local.quiet = getattr(self._local, "quiet", 0) + 1
            try:
                out = fn(*a, **k)
            finally:
                self._local.quiet -= 1
            if after is not None:
                try:
                    after(out)
                except Exception:
                    pass
            return out
        return run

    # ----- 감싸기 도구 -----
    def _wrap(self, obj, name: str, after):
        """obj.name 을 감싼다: 원래 함수를 부르고, 예외 없이 끝나면 after(결과, 인자들) 로 사건을 만든다. 두 번 감싸지 않는다"""
        fn = getattr(obj, name, None)
        if not callable(fn) or getattr(fn, "_dbwatch", False):
            return

        @functools.wraps(fn)
        def run(*a, **k):
            out = fn(*a, **k)
            try:
                after(out, *a, **k)
            except Exception:
                pass
            return out
        run._dbwatch = True
        try:
            setattr(obj, name, run)
        except Exception:
            pass

    # ----- 습득물 접수 저장소(intake) -----
    def watch_intake(self, store) -> None:
        def created(row, intake, today=None):
            iid = row.get("item_id", "")
            machine = row.get("machine_id") or intake.get("machine_id")
            self.emit("item", "INSERT", iid, [
                col("item_id", iid, True), col("machine_id", machine, True),
                col("place_text", row.get("place_text") or intake.get("place_text"), True),
                col("photo_path", "사진 파일 저장됨" if intake.get("photo_path") else "없음", True),
                col("status", row.get("status") or "등록기계 보관", True),
                col("category", "아직 모름 — 사진 분석 대기" if intake.get("photo_path") else "아직 모름", False),
            ], by=f"등록기계 {machine}", note="습득물 접수 → 접수 번호 발급")
            if intake.get("finder"):
                self.emit("finder_contact", "INSERT", iid, [
                    col("item_id", iid, True), col("name", "저장됨(가림)", True, hidden=True),
                    col("phone", "저장됨(가림)", True, hidden=True),
                ], by=f"등록기계 {machine}", note="연락처는 저장만 — 화면·응답에 나가지 않음")
            self.emit("item_status_log", "INSERT", iid, [
                col("item_id", iid, True), col("from_status", None), col("to_status", row.get("status") or "등록기계 보관", True),
                col("changed_by", "kiosk", True)], by=f"등록기계 {machine}", note="첫 상태 기록")

        def features(ok, item_id, feats, *a, **k):
            if not ok:
                return
            from agents.intake import split_features
            cat, pub, priv = split_features(feats)
            row = (getattr(store, "items", None) or {}).get(item_id) if isinstance(getattr(store, "items", None), dict) else None
            photo = True if row is None else bool(row.get("photo_path"))       # 메모리 저장소면 사진 접수인지 확인(DB 저장소는 사진 접수로 봄)
            self.emit("item", "UPDATE", item_id, [
                col("category", cat, True), col("features", pub, True),
                col("private_features", f"{len(priv)}개 저장(값은 가림 — 확인 질문 정답)", True, hidden=True),
            ], by="Qwen 사진 분석" if photo else "가상 분석(글 신고)",
                note="사진에서 읽은 특징을 채움(공개/비공개로 나눠 저장)" if photo else "신고 글에서 읽은 특징을 채움(가상 시연 — 사진 없음)")

        self._wrap(store, "create", created)
        self._wrap(store, "set_features", features)

    # ----- 찾기 요청 저장소(claims) -----
    def watch_delete(self, world) -> None:
        """11/10 접수 취소(가상 세계 delete_item): item 행과 딸린 기록이 지워진다"""
        fn = getattr(world, "delete_item", None)
        if not callable(fn):
            return

        @functools.wraps(fn)
        def run(item_id, *a, **k):
            out = fn(item_id, *a, **k)
            if out is not None:
                try:
                    self.emit("item", "DELETE", item_id, [col("item_id", item_id, True), col("status", out.get("status"), False)],
                              by="직원(접수 취소)", note="실수로 접수한 물건을 지움 — 상태 기록·연락처도 함께(사진 파일은 남음)")
                except Exception:
                    pass
            return out
        world.delete_item = run

        purge = getattr(world, "purge_item", None)
        if callable(purge):
            @functools.wraps(purge)
            def run_purge(item_id, *a, **k):
                out = purge(item_id, *a, **k)
                if out is not None:
                    try:
                        self.emit("item", "DELETE", item_id, [col("item_id", item_id, True), col("status", out.get("status"), False)],
                                  by="직원(기록 삭제)", note="물건에 딸린 기록을 모두 지움 — 상태 기록·연락처·보관 칸·찾기 요청·반환 기록(사진 파일은 남음)")
                    except Exception:
                        pass
                return out
            world.purge_item = run_purge

    def watch_claims(self, store) -> None:
        def created(row, claim, today=None):
            cid, iid = row.get("claim_id", ""), row.get("item_id", "")
            self.emit("claim", "INSERT", cid, [
                col("claim_id", cid, True), col("item_id", iid, True), col("name_masked", row.get("name_masked"), True),
                col("id_no_masked", "가린 값만 저장됨(화면에 안 냄)", True, hidden=True),
                col("id_verified", row.get("id_verified"), True), col("description", row.get("description") or {}, True),
            ], by="분실인 웹", note="찾기 요청 저장 → 찾기 번호 발급")
            for q in row.get("quiz") or []:
                self.emit("quiz_attempt", "INSERT", cid, [
                    col("claim_id", cid, True), col("item_id", iid, True),
                    col("field", FEATURE_LABELS.get(q.get("field"), q.get("field")), True), col("passed", q.get("passed"), True),
                ], by="분실인 웹", note="확인 질문 결과(정답 자체는 저장하지 않음)")
            self.emit("reservation", "INSERT", cid, [
                col("claim_id", cid, True), col("item_id", iid, True), col("visit_date", row.get("visit_date"), True),
                col("status", row.get("status") or "booked", True)], by="분실인 웹", note="본센터 방문 예약")

        def got(row, claim_id, *a, **k):
            why = self._reading()
            if not why or not row:
                return
            from agents.claims import web_gates
            g = web_gates(row)
            self.emit("claim", "SELECT", claim_id, [
                col("where", f"claim_id = {claim_id}"), col("item_id", row.get("item_id")),
                col("status", row.get("status")), col("id_verified", g["id_verified"]),
                col("passed", g["quiz_passed"]),
                col("id_no_masked", "입력한 번호와 저장된 가린 값을 비교(값은 화면에 안 냄)", hidden=True),
            ], by=why, note="찾기 번호로 요청을 읽어 본인 확인")

        def visited(_out, claim_id, *a, **k):
            self.emit("reservation", "UPDATE", claim_id, [col("claim_id", claim_id), col("status", "visited", True)],
                      by="본센터", note="방문 확인")

        self._wrap(store, "create", created)
        self._wrap(store, "get", got)
        def cancelled(out, claim_id, *a, **k):
            if out:                                          # 실제로 취소된 것만(이미 방문·취소된 요청은 바뀌지 않음)
                self.emit("reservation", "UPDATE", claim_id, [col("claim_id", claim_id), col("status", "cancelled", True)],
                          by="직원·분실인", note="찾기 요청·방문 예약 취소 — 물건은 계속 보관")

        self._wrap(store, "mark_visited", visited)
        if callable(getattr(store, "cancel", None)):
            self._wrap(store, "cancel", cancelled)

    # ----- 보관함 정답지(storage) -----
    def watch_storage(self, store) -> None:
        def assigned(out, item_id, slot_id, *a, **k):
            if not (out or {}).get("ok"):
                return
            by = k.get("by") or (a[1] if len(a) > 1 else "staff")
            self.emit("storage_assignment", "INSERT", item_id, [
                col("slot_id", out.get("slot_id") or slot_id, True), col("item_id", item_id, True),
                col("assigned_by", by, True)], by="본센터 보관함", note="물건을 보관 칸에 배정")

        def released(out, *a, **k):
            if not (out or {}).get("ok") or not out.get("item_id") or not out.get("slot_id"):
                return
            self.emit("storage_assignment", "DELETE", out["item_id"], [
                col("slot_id", out["slot_id"], True), col("item_id", out["item_id"])],
                by="본센터 보관함", note="보관 칸 비움")

        def shelved(out, item_id, *a, **k):
            if not (out or {}).get("ok", True) or not (out or {}).get("slot_id"):
                return
            self.emit("storage_assignment", "INSERT", item_id, [
                col("slot_id", out["slot_id"], True), col("item_id", item_id, True),
                col("assigned_by", k.get("by") or "staff", True)], by="본센터 직원", note="칸이 꽉 차 직원 보관 선반으로")

        self._wrap(store, "assign", assigned)
        self._wrap(store, "release", released)
        self._wrap(store, "move_to_shelf", shelved)

    # ----- 반환 기록(recorder) -----
    def watch_recorder(self, rec) -> None:
        def saved(_out, item_id, outcome, *a, **k):
            cid = outcome.get("case_id", "")
            self.emit("return_case", "INSERT", cid, [
                col("case_id", cid, True), col("item_id", item_id, True), col("claim_id", outcome.get("claim_id"), True),
                col("decision", outcome.get("decision"), True), col("reason", outcome.get("reason"), True),
                col("approved", bool(outcome.get("approved")), True), col("matched_object", outcome.get("matched_object"), True),
                col("seconds", outcome.get("seconds", 0.0), True)], by="관제탑", note="반환 한 건의 결과 저장")
            steps = [str(s) for s in outcome.get("steps") or []]
            if steps:
                self.emit("return_step", "INSERT", cid, [col("case_id", cid, True), col("step", " → ".join(steps), True)],
                          by="관제탑", note=f"지나온 단계 {len(steps)}개 저장")
        self._wrap(rec, "save", saved)

    # ----- DB 부품(물건 상태 읽기·바꾸기) -----
    @staticmethod
    def _peek_status(part, item_id: str):
        """바꾸기 전 상태를 부작용 없이 엿본다(메모리 저장소만 — 가짜 부품의 호출 기록·DB 조회를 늘리지 않게). 모르면 None"""
        for attr in ("items", "db"):
            rows = getattr(part, attr, None)
            if isinstance(rows, dict) and isinstance(rows.get(item_id), dict):
                return rows[item_id].get("status")
        return None

    def watch_db_part(self, part) -> None:
        fn = getattr(part, "db_set_status", None)
        if callable(fn) and not getattr(fn, "_dbwatch", False):
            @functools.wraps(fn)
            def set_status(item_id, status, changed_by="tower"):
                before = self._peek_status(part, item_id)
                out = fn(item_id, status, changed_by=changed_by)
                try:
                    if (out or {}).get("ok") and before != status:       # 같은 상태로 다시 쓴 것은 바뀐 게 없어 남기지 않음
                        self.emit("item", "UPDATE", item_id, [col("status", status, True)], by=str(changed_by),
                                  note=f"상태 변경{f' ({before} → {status})' if before and before != status else ''}")
                        self.emit("item_status_log", "INSERT", item_id, [
                            col("item_id", item_id, True), col("from_status", before), col("to_status", status, True),
                            col("changed_by", changed_by, True)], by=str(changed_by), note="상태가 바뀔 때마다 한 줄")
                        if status == "인계 완료":
                            # 11/11 팀 DB 는 트리거(storage_release_on_handover)가, 메모리 저장소는 읽을 때 걸러서 칸이 빈다 —
                            # 코드가 직접 지우지 않아 사건이 없었고, 발표 화면 item 카드에 칸이 그대로 남아 보였다
                            self.emit("storage_assignment", "DELETE", item_id, [col("item_id", item_id)],
                                      by="DB 트리거", note="인계 완료 → 보관 칸이 저절로 빔(storage_release_on_handover)")
                except Exception:
                    pass
                return out
            set_status._dbwatch = True
            try:
                part.db_set_status = set_status
            except Exception:
                pass

        def got(rec, item_id, *a, **k):
            why = self._reading()
            if not why or not rec:
                return
            feats = dict(rec.get("features") or {})
            self.emit("item", "SELECT", item_id, [
                col("where", f"item_id = {item_id}"), col("status", rec.get("status")),
                col("category", rec.get("category") or feats.get("category")),
                col("features", f"특징 {len(feats)}칸 읽음(매칭·확인에 사용)", hidden=True)],
                by=why, note="물건 기록을 읽어 반환해도 되는 상태인지 확인")
        self._wrap(part, "db_get_item", got)

    def watch_backend_factory(self, svc) -> None:
        """요청마다 새로 만들어지는 부품 묶음(가짜 부품 포함)의 DB 부품도 감싼다"""
        make = svc.backend_factory
        if getattr(make, "_dbwatch", False):
            return

        @functools.wraps(make)
        def factory(*a, **k):
            be = make(*a, **k)
            try:
                route = getattr(be, "_route", None)
                part = (route or {}).get("db_set_status") if isinstance(route, dict) else None
                self.watch_db_part(part if part is not None else getattr(be, "fallback", be))
            except Exception:
                pass
            return be
        factory._dbwatch = True
        svc.backend_factory = factory

    # ----- 가상 시연: 후보 검색 · 챗봇 물건 검색 · 초기화 -----
    def watch_sim(self, svc) -> None:
        world, sim = getattr(svc, "world", None), getattr(svc, "sim", None)
        if sim is not None:
            def cands(out, desc, station=None, *a, **k):
                where = " · ".join(f"{FEATURE_LABELS.get(key, key)}={v}" for key, v in (desc or {}).items() if v) or "조건 없음"
                if station:
                    where += f" · 역={station}"
                found = ", ".join(f"{c['item_id']}({c['score']})" for c in out or []) or "없음"
                self.emit("item", "SELECT", "", [
                    col("where", f"{where} · 상태가 보관 중인 물건만"), col("rows", f"{len(out or [])}건: {found}", bool(out)),
                    col("private_features", "읽지 않음 — 공개 특징만으로 닮은 순서를 매김", hidden=True)],
                    by="분실 신고 후보 검색", note="분실인이 말한 특징과 닮은 습득물을 찾음")
            self._wrap(sim, "candidates", cands)
            reset = getattr(sim, "reset", None)
            if callable(reset) and not getattr(reset, "_dbwatch", False):
                def after_reset(_out):
                    n = len(getattr(world, "items", {}) or {})
                    self.emit("item", "INSERT", "", [col("rows", f"시연 물건 {n}개를 보관 칸에 다시 채움", True)],
                              by="가상 세계 초기화", note="처음 상태로 되돌림")
                wrapped = self.quietly(reset, after_reset)
                wrapped._dbwatch = True
                sim.reset = wrapped
        if world is not None:
            def chat(out, *a, **k):
                self.emit("item", "SELECT", "", [
                    col("where", "공개 칸만: 품목 · 색 · 상태 · 등록기계 · 접수 시각"), col("rows", f"{len(out or [])}건 읽음"),
                    col("private_features", "읽지 않음(비공개 특징·연락처는 챗봇에 주지 않음)", hidden=True)],
                    by="챗봇 item_search", note="챗봇이 물건 후보를 찾으려고 읽음(읽기 전용)")
            self._wrap(world, "chat_items", chat)


def attach(svc):
    """관제탑 서비스의 저장소에 지켜보기를 붙인다(기록판이 없으면 아무것도 안 함, 두 번 불러도 한 번만). 붙인 DbWatch 를 돌려줌"""
    board = getattr(svc, "board", None)
    if board is None or not callable(getattr(board, "db", None)):
        return None
    done = getattr(svc, "db_watch", None)
    if done is not None:
        return done
    w = DbWatch(board)
    try:
        w.source = "postgres" if "Postgres" in type(svc.intake).__name__ else "memory"
        w.watch_intake(svc.intake)
        w.watch_claims(svc.claims)
        w.watch_storage(svc.storage)
        w.watch_recorder(svc.recorder)
        world = getattr(svc, "world", None)
        if world is not None:
            w.watch_db_part(world)
            w.watch_delete(world)
        w.watch_backend_factory(svc)
        w.watch_sim(svc)
        for name, label in (("kiosk_return", "본센터 키오스크 회수"), ("start_return", "반환 흐름")):
            fn = getattr(svc, name, None)
            if callable(fn):
                setattr(svc, name, w.reading(label, fn))
    except Exception:
        pass
    svc.db_watch = w
    return w


__all__ = ["DbWatch", "attach", "TABLES", "COLS", "col"]
