"""Synthetic station-scoped place catalog; no production place table is accessed."""
import re
from agents.lost_input import checked_text
from agents.search_context import normalize_station

MACHINES = {'KIOSK-A': ('1호선', '중앙'), 'KIOSK-C': ('1호선', '초량')}


class DemoPlaces:
    def __init__(self, store):
        self.store = store

    def recommend(self, machine_id, offset=0):
        if not isinstance(machine_id, str) or machine_id not in MACHINES:
            raise ValueError('가상 등록기계 A·B·C 중에서 선택해주세요')
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('목록 위치는 0~10000 정수여야 합니다')
        line, station = MACHINES[machine_id]
        with self.store.connection() as db:
            rows = db.execute('SELECT place_id,line,station,label FROM demo_place WHERE line=? AND station=? ORDER BY place_id LIMIT 6 OFFSET ?', (line, station, offset)).fetchall()
            total = db.execute('SELECT count(*) FROM demo_place WHERE line=? AND station=?', (line, station)).fetchone()[0]
            return {'places': [dict(r) for r in rows[:5]], 'next_offset': offset + 5 if len(rows) > 5 else None,
                    'offset': offset, 'total': total, 'line': line, 'station': station,
                    'revision': self.store._check_revision(db, None), 'mode': 'demo_sqlite'}

    def put(self, line, station, label, *, revision=None):
        line = checked_text(line, '호선', 16)
        station = normalize_station(station)
        label = checked_text(label, '장소', 64)
        if not re.fullmatch(r'[1-9][0-9]?호선', line) or (line, station) not in MACHINES.values():
            raise ValueError('현재 가상 등록기계가 있는 호선·역만 추가할 수 있습니다')
        with self.store.connection(write=True) as db:
            current = self.store._check_revision(db, revision)
            old = db.execute('SELECT place_id FROM demo_place WHERE line=? AND station=? AND label=?', (line, station, label)).fetchone()
            iid = old[0] if old else db.execute('INSERT INTO demo_place(line,station,label) VALUES(?,?,?)', (line, station, label)).lastrowid
            position = db.execute('SELECT count(*) FROM demo_place WHERE line=? AND station=? AND place_id<?', (line, station, iid)).fetchone()[0]
            return {'place_id': iid, 'created': old is None, 'page_offset': position // 5 * 5, 'revision': current}
