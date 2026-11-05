"""LF-9: transactional kiosk pickup, partial arrival and durable alert queue."""
import re
from agents.contracts import ITEM_ID_RE


class CollectionError(ValueError):
    pass


def item_ids(value, allow_empty=False):
    if (not isinstance(value, list) or not (0 if allow_empty else 1) <= len(value) <= 200
            or any(not isinstance(v, str) or not ITEM_ID_RE.fullmatch(v) for v in value)
            or len(set(value)) != len(value)):
        raise CollectionError("물건 번호 1~200개를 중복 없이 입력하세요")
    return sorted(value)


class CollectionStore:
    def __init__(self, connect):
        self.connect = connect

    @staticmethod
    def _view(cur, cid):
        cur.execute("SELECT machine_id, picked_at, arrived_at FROM collection WHERE collection_id=%s", (cid,))
        row = cur.fetchone()
        if row is None:
            raise CollectionError("회수 기록이 없습니다")
        cur.execute("SELECT item_id, arrived FROM collection_item WHERE collection_id=%s ORDER BY item_id", (cid,))
        return {"collection_id": cid, "machine_id": row[0], "picked_at": row[1].isoformat(),
                "arrived_at": row[2].isoformat() if row[2] else None,
                "items": [{"item_id": i, "arrived": a} for i, a in cur.fetchall()]}

    def get(self, cid):
        with self.connect() as conn, conn.cursor() as cur:
            return self._view(cur, cid)

    def pickup(self, machine_id, ids, request_id):
        ids = item_ids(ids)
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", request_id):
            raise CollectionError("request_id는 재시도에도 동일한 영문·숫자 식별자(8~64자)를 쓰세요")
        if not isinstance(machine_id, str) or not re.fullmatch(r"KIOSK-[A-Z0-9-]{1,10}", machine_id):
            raise CollectionError("등록기계 번호를 확인하세요")
        with self.connect() as conn, conn.cursor() as cur:
            # Serialize the same retry key, including simultaneous initial requests.
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (request_id,))
            cur.execute("SELECT collection_id FROM collection WHERE request_id=%s", (request_id,))
            old = cur.fetchone()
            if old:
                result = self._view(cur, old[0])
                if result["machine_id"] != machine_id or sorted(i["item_id"] for i in result["items"]) != ids:
                    raise CollectionError("같은 request_id에 다른 회수 내용을 사용할 수 없습니다")
                return result
            cur.execute("SELECT item_id, machine_id, status FROM item WHERE item_id=ANY(%s) ORDER BY item_id FOR UPDATE", (ids,))
            rows = cur.fetchall()
            if len(rows) != len(ids) or any(m != machine_id or s != "등록기계 보관" for _, m, s in rows):
                raise CollectionError("모든 물건이 해당 등록기계 보관 상태여야 합니다")
            cur.execute("INSERT INTO collection(machine_id,request_id) VALUES(%s,%s) RETURNING collection_id", (machine_id, request_id))
            cid = cur.fetchone()[0]
            for iid in ids:
                cur.execute("INSERT INTO collection_item(collection_id,item_id) VALUES(%s,%s)", (cid, iid))
                cur.execute("UPDATE item SET status='회수 중',updated_at=now() WHERE item_id=%s", (iid,))
                cur.execute("INSERT INTO item_status_log(item_id,from_status,to_status,changed_by) VALUES(%s,'등록기계 보관','회수 중','staff')", (iid,))
            return self._view(cur, cid)

    def arrive(self, cid, ids):
        ids = item_ids(ids, allow_empty=True)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT collection_id FROM collection WHERE collection_id=%s FOR UPDATE", (cid,))
            if not cur.fetchone():
                raise CollectionError("회수 기록이 없습니다")
            cur.execute("SELECT item_id,arrived FROM collection_item WHERE collection_id=%s ORDER BY item_id", (cid,))
            members = dict(cur.fetchall())
            if not set(ids) <= members.keys():
                raise CollectionError("이 회수에 포함되지 않은 물건입니다")
            pending = [i for i in ids if not members[i]]
            if pending:
                cur.execute("SELECT item_id,status FROM item WHERE item_id=ANY(%s) ORDER BY item_id FOR UPDATE", (pending,))
                if any(s != "회수 중" for _, s in cur.fetchall()):
                    raise CollectionError("도착 전 물건 상태가 변경됐습니다. 직원 확인이 필요합니다")
            for iid in pending:
                cur.execute("UPDATE collection_item SET arrived=true WHERE collection_id=%s AND item_id=%s", (cid, iid))
                cur.execute("UPDATE item SET status='본센터 보관',updated_at=now() WHERE item_id=%s", (iid,))
                cur.execute("INSERT INTO item_status_log(item_id,from_status,to_status,changed_by) VALUES(%s,'회수 중','본센터 보관','staff')", (iid,))
                cur.execute("UPDATE collection_alert SET resolved_at=now() WHERE collection_id=%s AND item_id=%s AND resolved_at IS NULL", (cid, iid))
                members[iid] = True
            missing = [i for i, arrived in members.items() if not arrived]
            for iid in missing:
                cur.execute("INSERT INTO collection_alert(collection_id,item_id) VALUES(%s,%s) ON CONFLICT(collection_id,item_id) DO NOTHING", (cid, iid))
            if not missing:
                cur.execute("UPDATE collection SET arrived_at=COALESCE(arrived_at,now()) WHERE collection_id=%s", (cid,))
            result = self._view(cur, cid)
            result["missing_item_ids"] = missing
            result["alert_status"] = "queued" if missing else "none"
            return result

    def overdue(self, before):
        """Caller supplies an explicit deadline; no invented business cutoff."""
        if before.tzinfo is None:
            raise CollectionError("기준시각에 시간대가 필요합니다")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO collection_alert(collection_id,item_id) SELECT c.collection_id,ci.item_id FROM collection c JOIN collection_item ci USING(collection_id) WHERE c.picked_at<%s AND NOT ci.arrived ON CONFLICT(collection_id,item_id) DO NOTHING", (before,))
            return cur.rowcount

    def dispatch(self, reporter):
        """Explicit invocation only. Dry run never marks real delivery complete."""
        sent = 0
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT collection_id,item_id FROM collection_alert WHERE sent_at IS NULL AND resolved_at IS NULL ORDER BY collection_id,item_id FOR UPDATE SKIP LOCKED")
            for cid, iid in cur.fetchall():
                ok = reporter.alert(f"collection-{cid}", "본센터 미도착", iid)
                if ok and not reporter.dry_run:
                    cur.execute("UPDATE collection_alert SET sent_at=now() WHERE collection_id=%s AND item_id=%s", (cid, iid))
                    sent += 1
        return sent
