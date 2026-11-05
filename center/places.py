"""LF-9 place catalog maintenance; existing intake API can read the same table."""


class Places:
    def __init__(self, connect):
        self.connect = connect

    def put(self, line, station, label):
        values = (line, station, label)
        if any(not isinstance(v, str) or not v.strip() or len(v.strip()) > n
               for v, n in zip(values, (16, 32, 64))):
            raise ValueError("호선·역·장소를 길이 제한 안에서 입력하세요")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO place(line,station,label) VALUES(%s,%s,%s) ON CONFLICT(line,station,label) DO UPDATE SET label=EXCLUDED.label RETURNING place_id", tuple(v.strip() for v in values))
            return {"place_id": cur.fetchone()[0]}

    def recommend(self, machine_id, offset=0):
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 10000:
            raise ValueError("목록 위치는 0~10000 정수여야 합니다")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT line,station FROM machine WHERE machine_id=%s AND kind='kiosk'", (machine_id,))
            machine = cur.fetchone()
            if not machine:
                raise ValueError("등록기계가 없습니다")
            # Existing intake validates both line AND station; keep recommendations compatible.
            cur.execute("SELECT place_id,line,station,label FROM place WHERE line=%s AND station=%s ORDER BY use_count DESC,place_id LIMIT 6 OFFSET %s", (machine[0], machine[1], offset))
            rows = cur.fetchall()
        return {"places": [{"place_id": r[0], "line": r[1], "station": r[2], "label": r[3]} for r in rows[:5]],
                "next_offset": offset + 5 if len(rows) > 5 else None}
