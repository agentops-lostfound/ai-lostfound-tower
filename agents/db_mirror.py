"""가상 시연 기록을 팀 DB 에도 함께 저장(DbMirror) — LF-18, 11/10 변재원

한줄 설명: 가상 시연(TOWER_SIM=1)은 물건·찾기 요청을 메모리에만 두었다. 이 부품을 붙이면 **같은 쓰기를 팀 DB(PostgreSQL)에도**
한 번 더 한다 → 키오스크에서 접수한 물건(어느 등록기계·어디서·사진 위치·상태)이 본센터 DB 의 `item` 표에 남는다.

왜 '함께 저장'인가: 가상 시연의 로봇·작업대·이야기 진행은 메모리 세계(agents/sim_world.py)가 움직인다. 그 구조는 그대로 두고,
저장소에 쓰는 순간마다 같은 내용을 팀 DB 에도 쓴다. 읽기는 계속 가상 세계에서 한다(팀 DB 가 꺼져 있어도 시연은 멈추지 않는다).

- 켜기: 환경값 `TOWER_SIM_DB=1` + `DATABASE_URL` (tools/start_tower.bat 가 기본으로 켠다, 끄려면 `start_tower.bat nodb`).
  시험·다른 도구에서는 저절로 켜지지 않는다(agents/api.py build_service 가 관제탑을 켤 때만 붙임)
- 쓰는 표: item · finder_contact · item_status_log · claim · quiz_attempt · reservation · storage_assignment · return_case · return_step
- 순서: 쓰기는 줄(queue)에 넣고 뒤에서 한 줄(스레드)이 차례로 처리한다 → 시연 화면이 DB 속도를 기다리지 않고, 순서는 지켜진다
- 번호: 가상 세계의 접수 번호·찾기 번호가 팀 DB 에 이미 있는 번호와 겹치지 않게, 날짜마다 한 번 팀 DB 의 가장 큰 순번을 읽어 맞춘다
- **실제 운영 기록을 덮지 않는다**
  · 글로 한 가상 신고·시연용 물건은 `item.object_id = 'SIM'` 으로 표시한다(키오스크 사진 접수는 진짜 접수라 표시 없음)
  · 같은 번호의 물건이 팀 DB 에 이미 있고 그것이 가상 표시가 아니면 → 건드리지 않고, 그 물건의 뒤따르는 기록도 넘긴다(skipped)
  · 보관 칸은 `assigned_by = 'system'`(이 부품이 쓴 것)만 바꾼다. 직원·관제탑이 넣은 칸('staff'·'tower')은 그대로 둔다
- 실패(팀 DB 꺼짐·제약 위반)는 세기만 하고 시연을 막지 않는다. 접속이 두 번 연달아 안 되면 20초 쉰 뒤 다시 시도한다
- DATABASE_URL(비밀번호 포함)은 출력·기록하지 않는다. 오류는 종류 이름(예: OperationalError)만 남긴다
"""
from __future__ import annotations

import functools
import json
import os
import queue
import threading
import time
from datetime import date

SIM_MARK = "SIM"                     # 가상 물건 표시(item.object_id)
LOG_BY = ("kiosk", "staff", "tower", "system")
ASSIGN_BY = "system"
DESC_KEYS = ("category", "color", "shape", "mark", "visible_text", "material")
QUIZ_FIELDS = ("mark", "visible_text", "place", "color", "shape")
COOL_S = 20.0

SQL_ITEM_UPSERT = (
    "INSERT INTO item (item_id, machine_id, place_text, photo_path, status, category, features, private_features, object_id) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) "
    "ON CONFLICT (item_id) DO UPDATE SET machine_id = EXCLUDED.machine_id, place_text = EXCLUDED.place_text, "
    "photo_path = EXCLUDED.photo_path, status = EXCLUDED.status, category = EXCLUDED.category, features = EXCLUDED.features, "
    "private_features = EXCLUDED.private_features, updated_at = now() "
    "WHERE item.object_id LIKE 'SIM%%' RETURNING (xmax = 0) AS inserted")
SQL_CONTACT = "INSERT INTO finder_contact (item_id, name, phone) VALUES (%s, %s, %s) ON CONFLICT (item_id) DO NOTHING"
SQL_LOG = "INSERT INTO item_status_log (item_id, from_status, to_status, changed_by) VALUES (%s, %s, %s, %s)"
SQL_FEATURES = ("UPDATE item SET category = %s, features = %s::jsonb, private_features = %s::jsonb, updated_at = now() "
                "WHERE item_id = %s")
SQL_STATUS = "UPDATE item SET status = %s, updated_at = now() WHERE item_id = %s AND status IS DISTINCT FROM %s"
SQL_CLAIM = (
    "INSERT INTO claim (claim_id, consented_at, name_masked, id_no_masked, id_verified, description, lost_line, lost_station, lost_date) "
    "VALUES (%s, now(), %s, %s, %s, %s::jsonb, %s, %s, %s) ON CONFLICT (claim_id) DO NOTHING RETURNING claim_id")
SQL_QUIZ = "INSERT INTO quiz_attempt (claim_id, item_id, field, passed) VALUES (%s, %s, %s, %s)"
SQL_RESERVATION = ("INSERT INTO reservation (claim_id, item_id, visit_date) VALUES (%s, %s, %s) "
                   "ON CONFLICT (claim_id) DO NOTHING")
SQL_VISITED = "UPDATE reservation SET status = 'visited' WHERE claim_id = %s"
SQL_SHELF_SLOT = ("INSERT INTO storage_slot (slot_id, section_code, slot_no, note) SELECT %s, %s, %s, '직원 보관 선반' "
                  "WHERE EXISTS (SELECT 1 FROM storage_section WHERE section_code = %s) ON CONFLICT DO NOTHING")
SQL_SLOT_MOVE_OUT = "DELETE FROM storage_assignment WHERE item_id = %s AND slot_id <> %s AND assigned_by = 'system'"
SQL_SLOT_CLEAR_OLD = "DELETE FROM storage_assignment WHERE slot_id = %s AND item_id <> %s AND assigned_by = 'system'"
SQL_SLOT_ASSIGN = ("INSERT INTO storage_assignment (slot_id, item_id, assigned_by) VALUES (%s, %s, 'system') "
                   "ON CONFLICT DO NOTHING RETURNING slot_id")
SQL_SLOT_RELEASE = "DELETE FROM storage_assignment WHERE item_id = %s AND assigned_by = 'system'"
SQL_SLOT_NOW = "SELECT item_id FROM storage_assignment WHERE slot_id = %s"
SQL_CASE = ("INSERT INTO return_case (case_id, item_id, claim_id, decision, reason, approved, matched_object, seconds) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (case_id) DO NOTHING RETURNING case_id")
SQL_STEP = "INSERT INTO return_step (case_id, step) VALUES (%s, %s)"
SQL_MAX_ITEM = "SELECT COALESCE(MAX(CAST(RIGHT(item_id, 4) AS INTEGER)), 0) FROM item WHERE item_id LIKE %s"
SQL_MAX_CLAIM = "SELECT COALESCE(MAX(CAST(RIGHT(claim_id, 4) AS INTEGER)), 0) FROM claim WHERE claim_id LIKE %s"
# 화면용 조회(개인정보 칸은 읽지 않는다): 최근 접수 + 어느 등록기계(역) + 보관 칸 + 상태 기록 수
SQL_RECENT = (
    "SELECT i.item_id, i.machine_id, m.station, m.kind, i.place_text, i.status, i.category, (i.photo_path IS NOT NULL), "
    "i.received_at, a.slot_id, (SELECT count(*) FROM item_status_log l WHERE l.item_id = i.item_id), "
    "(i.object_id LIKE 'SIM%%') IS TRUE "
    "FROM item i JOIN machine m USING (machine_id) LEFT JOIN storage_assignment a USING (item_id) "
    "ORDER BY i.received_at DESC, i.item_id DESC LIMIT %s")
SQL_COUNTS = ("SELECT (SELECT count(*) FROM item), (SELECT count(*) FROM item_status_log), (SELECT count(*) FROM claim), "
              "(SELECT count(*) FROM reservation), (SELECT count(*) FROM storage_assignment), (SELECT count(*) FROM return_case)")
SQL_ONE = ("SELECT i.item_id, i.machine_id, m.station, i.place_text, i.status, i.category, (i.photo_path IS NOT NULL), "
           "i.received_at, i.updated_at FROM item i JOIN machine m USING (machine_id) WHERE i.item_id = %s")


def _default_connect(dsn: str):
    import psycopg   # 설치 안 된 PC 에서도 이 파일 import 는 되게 안에서 부른다
    return psycopg.connect(dsn, connect_timeout=3)


def _iso(v):
    return v.isoformat(timespec="seconds") if hasattr(v, "isoformat") else v


def _cut(v, n: int):
    return None if v is None else str(v)[:n]


class DbMirror:
    def __init__(self, dsn: str, connect=None):
        if not dsn:
            raise ValueError("DATABASE_URL 이 비었습니다(.env 확인)")
        self._dsn = dsn
        self._connect = connect or _default_connect
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._skip: set[str] = set()           # 팀 DB 의 실제 기록과 번호가 겹쳐 건드리지 않기로 한 물건
        self._numbers_day: dict[str, float] = {}   # 날짜 → 번호를 맞춘 시각(실패하면 60초 뒤 다시)
        self._cool_until = 0.0
        self._conn_fails = 0
        self.ok = self.fail = self.skipped = 0
        self.last_error = ""
        self.connected: bool | None = None       # None = 아직 써 보지 않음
        self._thread = threading.Thread(target=self._run, daemon=True, name="db-mirror")
        self._thread.start()

    def __repr__(self) -> str:   # 비밀번호가 찍히지 않게
        return "DbMirror(dsn=***)"

    # ----- 줄(queue) · 처리 -----
    def _put(self, label: str, fn, item_id: str | None = None) -> None:
        self._q.put((label, fn, item_id))

    def _run(self) -> None:
        while True:
            label, fn, item_id = self._q.get()
            try:
                self._do(label, fn, item_id)
            except Exception:      # 어떤 일이 있어도 처리 줄은 멈추지 않는다
                pass
            finally:
                self._q.task_done()

    def _do(self, label: str, fn, item_id: str | None) -> None:
        if item_id is not None and item_id in self._skip:
            with self._lock:
                self.skipped += 1
            return
        if time.monotonic() < self._cool_until:            # 팀 DB 가 꺼져 있는 동안은 기다리지 않고 넘긴다
            with self._lock:
                self.fail += 1
            return
        try:
            with self._connect(self._dsn) as conn, conn.cursor() as cur:
                done = fn(cur)
        except Exception as e:
            name = type(e).__name__
            with self._lock:
                self.fail += 1
                self.last_error = f"{label}: {name}"
                if self.ok == 0:                   # 한 번도 못 썼으면(드라이버 없음 포함) 화면에 '연결 안 됨'으로
                    self.connected = False
                if "Operational" in name or "Connection" in name or "Timeout" in name:
                    self.connected = False
                    self._conn_fails += 1
                    if self._conn_fails >= 2:
                        self._cool_until, self._conn_fails = time.monotonic() + COOL_S, 0
            return
        with self._lock:
            self.connected, self._conn_fails = True, 0
            if done is False:
                self.skipped += 1
            else:
                self.ok += 1

    def wait(self, timeout: float = 10.0) -> bool:
        """줄에 넣은 쓰기가 모두 처리될 때까지 기다린다(시험·점검용)"""
        end = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.01)
        return not self._q.unfinished_tasks

    def stats(self) -> dict:
        with self._lock:
            return {"on": True, "connected": self.connected, "ok": self.ok, "fail": self.fail, "skipped": self.skipped,
                    "pending": self._q.unfinished_tasks, "last_error": self.last_error,
                    "resting": time.monotonic() < self._cool_until}

    # ----- 번호 맞추기(날짜마다 한 번, 접수·찾기 번호를 만들기 직전에 부름) -----
    def sync_numbers(self, world, claims, day: date | None = None) -> bool:
        from agents.contracts import MACHINE_LETTERS
        d = day or getattr(world, "today", None) or date.today()
        key = f"{d:%Y%m%d}"
        at = self._numbers_day.get(key)
        if at is not None and (at > 0 or time.monotonic() < -at):     # 맞췄거나, 실패 뒤 쉬는 중
            return at > 0
        try:
            with self._connect(self._dsn) as conn, conn.cursor() as cur:
                tops = {}
                for letter in sorted(set(MACHINE_LETTERS.values())):
                    cur.execute(SQL_MAX_ITEM, (f"{letter}-{key}-%",))
                    tops[f"{letter}-{key}-"] = int(cur.fetchone()[0])
                cur.execute(SQL_MAX_CLAIM, (f"C-{key}-%",))
                top_claim = int(cur.fetchone()[0])
        except Exception as e:
            with self._lock:
                self.last_error, self.connected = f"번호 맞추기: {type(e).__name__}", False
            self._numbers_day[key] = -(time.monotonic() + 60)          # 60초 뒤 다시 시도
            return False
        seqs = getattr(world, "_seq", None)
        if isinstance(seqs, dict):
            lock = getattr(world, "_lock", None) or threading.Lock()
            with lock:
                for prefix, top in tops.items():
                    seqs[prefix] = max(seqs.get(prefix, 0), top)
        floor = getattr(claims, "seq_floor", None)
        if isinstance(floor, dict):
            floor[key] = max(floor.get(key, 0), top_claim)
        self._numbers_day[key] = time.monotonic() or 1.0
        with self._lock:
            self.connected = True
        return True

    # ----- 쓰기 하나하나 -----
    @staticmethod
    def _row_args(row: dict, mark: str | None) -> tuple:
        feats = {k: v for k, v in (row.get("features") or {}).items() if k not in ("mark", "visible_text")}
        priv = {k: v for k, v in (row.get("private_features") or {}).items() if k not in ("color", "shape", "material")}
        return (row["item_id"], row["machine_id"], _cut(row.get("place_text") or "-", 128), _cut(row.get("photo_path"), 256),
                row.get("status") or "등록기계 보관", _cut(row.get("category") or "확인 불가", 16),
                json.dumps(feats, ensure_ascii=False), json.dumps(priv, ensure_ascii=False), mark)

    def item_new(self, row: dict, finder: dict | None = None, mark: str | None = SIM_MARK, log: bool = True) -> None:
        """새 물건(또는 가상 물건 다시 채움). 팀 DB 에 같은 번호의 실제 기록이 있으면 건드리지 않고 그 물건은 넘긴다"""
        args, iid, status = self._row_args(row, mark), row["item_id"], row.get("status") or "등록기계 보관"
        name, phone = _cut((finder or {}).get("name"), 32), _cut((finder or {}).get("phone"), 20)

        def run(cur):
            cur.execute(SQL_ITEM_UPSERT, args)
            got = cur.fetchone()
            if got is None:                       # 번호가 겹치는 실제 기록 → 손대지 않는다
                self._skip.add(iid)
                return False
            if got[0]:                            # 새로 넣은 행일 때만 연락처·첫 상태 기록
                if name or phone:
                    cur.execute(SQL_CONTACT, (iid, name, phone))
                if log:
                    cur.execute(SQL_LOG, (iid, None, status, "kiosk"))
            return True
        self._put("item", run)                    # 건너뛸지는 이 쓰기가 정한다

    def item_features(self, item_id: str, category: str, pub: dict, priv: dict) -> None:
        args = (_cut(category or "확인 불가", 16), json.dumps(pub, ensure_ascii=False), json.dumps(priv, ensure_ascii=False), item_id)
        self._put("item 특징", lambda cur: cur.execute(SQL_FEATURES, args) and None, item_id)

    def item_status(self, item_id: str, before: str | None, status: str, by: str = "tower") -> None:
        who = by if by in LOG_BY else "system"

        def run(cur):
            cur.execute(SQL_STATUS, (status, item_id, status))
            if cur.rowcount:
                cur.execute(SQL_LOG, (item_id, _cut(before, 16), status, who))
        self._put("item 상태", run, item_id)

    def claim_new(self, row: dict) -> None:
        cid, iid = row["claim_id"], row["item_id"]
        desc = {k: v for k, v in (row.get("description") or {}).items() if k in DESC_KEYS}
        quiz = [(q.get("field"), bool(q.get("passed"))) for q in row.get("quiz") or [] if q.get("field") in QUIZ_FIELDS]
        args = (cid, _cut(row.get("name_masked") or "*", 32), _cut(row.get("id_no_masked") or "*", 32), bool(row.get("id_verified")),
                json.dumps(desc, ensure_ascii=False), _cut(row.get("lost_line"), 16), _cut(row.get("lost_station"), 32),
                row.get("lost_date"))
        visit = row.get("visit_date")

        def run(cur):
            cur.execute(SQL_CLAIM, args)
            if cur.fetchone() is None:
                return False                      # 같은 찾기 번호가 이미 있음 → 그대로 둠
            for field, passed in quiz:
                cur.execute(SQL_QUIZ, (cid, iid, field, passed))
            cur.execute(SQL_RESERVATION, (cid, iid, visit))
            return True
        self._put("claim", run, iid)

    def claim_visited(self, claim_id: str) -> None:
        self._put("reservation", lambda cur: cur.execute(SQL_VISITED, (claim_id,)) and None)

    def slot_assign(self, slot_id: str, item_id: str) -> None:
        section, _, no = slot_id.partition("-")

        def run(cur):
            if section == "S" and no.isdigit():   # 직원 보관 선반 자리는 필요할 때 생긴다
                cur.execute(SQL_SHELF_SLOT, (slot_id, section, int(no), section))
            cur.execute(SQL_SLOT_MOVE_OUT, (item_id, slot_id))
            cur.execute(SQL_SLOT_CLEAR_OLD, (slot_id, item_id))
            cur.execute(SQL_SLOT_ASSIGN, (slot_id, item_id))
            if cur.fetchone() is not None:
                return True
            cur.execute(SQL_SLOT_NOW, (slot_id,))  # 이미 같은 물건이 그 칸에 있으면 된 것, 직원·관제탑이 넣은 다른 물건이면 그대로 둠(False)
            now = cur.fetchone()
            return bool(now and now[0] == item_id)
        self._put("보관 칸", run, item_id)

    def slot_release(self, item_id: str) -> None:
        self._put("보관 칸 비움", lambda cur: cur.execute(SQL_SLOT_RELEASE, (item_id,)) and None, item_id)

    def return_case(self, item_id: str, outcome: dict) -> None:
        cid = outcome.get("case_id")
        args = (cid, item_id, outcome.get("claim_id"), outcome.get("decision"), str(outcome.get("reason") or ""),
                bool(outcome.get("approved")), _cut(outcome.get("matched_object"), 32), float(outcome.get("seconds") or 0))
        steps = [_cut(s, 64) for s in outcome.get("steps") or []]

        def run(cur):
            cur.execute(SQL_CASE, args)
            if cur.fetchone() is None:
                return False
            for s in steps:
                cur.execute(SQL_STEP, (cid, s))
            return True
        self._put("return_case", run, item_id)

    # ----- 화면용 읽기(관리자 API) -----
    def recent(self, limit: int = 8) -> dict:
        """팀 DB 에서 최근 접수와 표별 행 수를 읽는다(이름·연락처·신분 번호·비공개 특징은 읽지 않음)"""
        limit = max(1, min(int(limit), 30))
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_RECENT, (limit,))
            cols = ("item_id", "machine_id", "station", "kind", "place_text", "status", "category", "has_photo", "received_at",
                    "slot_id", "status_logs", "virtual")
            items = [{k: _iso(v) for k, v in zip(cols, r)} for r in cur.fetchall()]
            cur.execute(SQL_COUNTS)
            c = cur.fetchone()
        counts = dict(zip(("item", "item_status_log", "claim", "reservation", "storage_assignment", "return_case"), map(int, c)))
        return {"items": items, "counts": counts}

    def photo_path(self, item_id: str) -> str | None:
        """팀 DB 에 저장된 접수 사진의 상대 경로(없으면 None)"""
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT photo_path FROM item WHERE item_id = %s", (item_id,))
            r = cur.fetchone()
        return r[0] if r else None

    def find(self, item_id: str) -> dict | None:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_ONE, (item_id,))
            r = cur.fetchone()
        cols = ("item_id", "machine_id", "station", "place_text", "status", "category", "has_photo", "received_at", "updated_at")
        return None if r is None else {k: _iso(v) for k, v in zip(cols, r)}


# ---------- 가상 시연 서비스에 붙이기 ----------
def _peek_status(world, item_id: str):
    row = (getattr(world, "items", None) or {}).get(item_id)
    return row.get("status") if isinstance(row, dict) else None


def attach(svc, mirror: DbMirror):
    """가상 시연 서비스(svc.world 가 있는 것)의 저장소 함수에 '팀 DB 에도 쓰기'를 붙인다. 원래 함수가 성공한 뒤에만 쓴다"""
    world = getattr(svc, "world", None)
    if world is None or getattr(svc, "db_mirror", None) is not None:
        return getattr(svc, "db_mirror", None)
    claims, storage, recorder = svc.claims, svc.storage, svc.recorder

    def after(obj, name, hook, before=None):
        fn = getattr(obj, name, None)
        if not callable(fn):
            return

        @functools.wraps(fn)
        def run(*a, **k):
            pre = None
            if before is not None:
                try:
                    pre = before(*a, **k)
                except Exception:
                    pre = None
            out = fn(*a, **k)
            try:
                hook(out, pre, *a, **k)
            except Exception:
                pass
            return out
        setattr(obj, name, run)

    # 접수: 번호를 팀 DB 와 맞춘 뒤 원래 접수 → 팀 DB 에도 저장. 사진이 있으면 키오스크의 진짜 접수(표시 없음), 없으면 가상 물건
    after(world, "create",
          lambda row, _pre, intake, today=None: mirror.item_new(
              {**row, "features": {}, "private_features": {}}, intake.get("finder"),
              mark=None if intake.get("photo_path") else SIM_MARK),
          before=lambda intake, today=None: mirror.sync_numbers(world, claims, today))

    def features(ok, _pre, item_id, feats, *a, **k):
        if ok:
            from agents.intake import split_features
            cat, pub, priv = split_features(feats)
            mirror.item_features(item_id, cat, pub, priv)
    after(world, "set_features", features)

    def status(out, before, item_id, new, changed_by="tower"):
        if (out or {}).get("ok") and before != new:
            mirror.item_status(item_id, before, new, changed_by)
    after(world, "db_set_status", status, before=lambda item_id, *a, **k: _peek_status(world, item_id))

    after(claims, "create", lambda row, _pre, *a, **k: mirror.claim_new(row),
          before=lambda claim, today=None: mirror.sync_numbers(world, claims, today))
    after(claims, "mark_visited", lambda _out, _pre, claim_id, *a, **k: mirror.claim_visited(claim_id))

    def assigned(out, _pre, item_id, slot_id, *a, **k):
        if (out or {}).get("ok"):
            mirror.slot_assign(out.get("slot_id") or slot_id, item_id)
    after(storage, "assign", assigned)

    def shelved(out, _pre, item_id, *a, **k):
        if (out or {}).get("slot_id"):
            mirror.slot_assign(out["slot_id"], item_id)
    after(storage, "move_to_shelf", shelved)

    def released(out, _pre, *a, **k):
        if (out or {}).get("item_id") and (out or {}).get("slot_id"):
            mirror.slot_release(out["item_id"])
    after(storage, "release", released)

    after(recorder, "save", lambda _out, _pre, item_id, outcome, *a, **k: mirror.return_case(item_id, outcome))

    # 지금 가상 세계에 이미 있는 물건(시연용 물건 5개)과 그 칸을 팀 DB 에 맞춘다
    mirror.sync_numbers(world, claims)
    try:
        rows = [dict(r) for r in list(world.items.values())]
    except Exception:
        rows = []
    for r in rows:
        mirror.item_new(r, None, mark=SIM_MARK, log=False)
    try:
        for sec in storage.layout()["sections"]:
            for sl in sec["slots"]:
                if sl.get("item"):
                    mirror.slot_assign(sl["slot_id"], sl["item"]["item_id"])
    except Exception:
        pass
    svc.db_mirror = mirror
    return mirror


def from_env(env=None) -> DbMirror | None:
    """TOWER_SIM_DB=1 이고 DATABASE_URL 이 있을 때만 만든다(없으면 None = 메모리만)"""
    env = os.environ if env is None else env
    if str(env.get("TOWER_SIM_DB") or "0").strip().lower() not in ("1", "true", "yes", "on"):
        return None
    dsn = (env.get("DATABASE_URL") or "").strip()
    if not dsn:
        return None
    return DbMirror(dsn)


__all__ = ["DbMirror", "attach", "from_env", "SIM_MARK"]
