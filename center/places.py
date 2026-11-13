"""LF-9 place catalog maintenance; existing intake API can read the same table."""
import re
from agents.lost_input import checked_text
from agents.search_context import normalize_station


class Places:
    def __init__(self, connect):
        self.connect = connect

    def put(self, line, station, label):
        line = checked_text(line, '호선', 16)
        station = normalize_station(station)
        label = checked_text(label, '장소', 64)
        if not re.fullmatch(r'[1-9][0-9]?호선', line):
            raise ValueError('호선은 1호선처럼 입력해주세요')
        with self.connect() as conn, conn.cursor() as cur:
            # Match the existing machine's spelling; do not add unreachable places
            # or assume every DB stores the optional Korean station suffix alike.
            cur.execute("SELECT DISTINCT line,station FROM machine WHERE kind='kiosk' AND line=%s AND station IN (%s,%s)", (line, station, station + '역'))
            scopes = cur.fetchall()
            if len(scopes) != 1:
                raise ValueError('등록기계가 있는 호선·역을 확인해주세요. 같은 역의 표기가 여러 개면 담당자 확인이 필요합니다')
            cur.execute("INSERT INTO place(line,station,label) VALUES(%s,%s,%s) ON CONFLICT(line,station,label) DO UPDATE SET label=EXCLUDED.label RETURNING place_id", (*scopes[0], label))
            return {"place_id": cur.fetchone()[0]}

    def recommend(self, machine_id, offset=0):
        checked_text(machine_id, '등록기계', 16)
        if not isinstance(machine_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,16}', machine_id):
            raise ValueError('등록기계 번호를 확인해주세요')
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 10000:
            raise ValueError("목록 위치는 0~10000 정수여야 합니다")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT line,station FROM machine WHERE machine_id=%s AND kind='kiosk'", (machine_id,))
            machine = cur.fetchone()
            if not machine:
                raise ValueError("등록기계가 없습니다")
            if not all(isinstance(v, str) and v.strip() for v in machine):
                raise ValueError('등록기계의 호선·역 정보가 없습니다. 담당자에게 확인해주세요')
            # Existing intake validates both line AND station; keep recommendations compatible.
            cur.execute("SELECT place_id,line,station,label FROM place WHERE line=%s AND station=%s ORDER BY use_count DESC,place_id LIMIT 6 OFFSET %s", (machine[0], machine[1], offset))
            rows = cur.fetchall()
        return {"places": [{"place_id": r[0], "line": r[1], "station": r[2], "label": r[3]} for r in rows[:5]],
                "next_offset": offset + 5 if len(rows) > 5 else None}
