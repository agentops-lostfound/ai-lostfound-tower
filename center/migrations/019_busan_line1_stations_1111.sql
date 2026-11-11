-- 019 (11/11) 시연 역 이름을 부산 1호선 중앙역 · 초량역으로 (LF-18, 변재원) — 사용자 결정
-- KIOSK-A: 2호선 해운대 → 1호선 중앙, KIOSK-C: 1호선 서면 → 1호선 초량. 본센터(CENTER)는 부산역 그대로.
-- agents/contracts.py MACHINE_STATION_NAME · agents/intake.py DEMO_PLACES · agents/sim_world.py STATIONS 와 같게(tests/test_db_decisions.py)
--
-- 1) 등록기계 번호(KIOSK-A·KIOSK-C)와 접수 번호 앞글자(A·S)는 그대로 — 지난 물건 번호와 이어진다
-- 2) 장소 행은 지우지 않고 **이름만** 바꾼다: 진짜 접수(item.place_id)가 그 장소를 가리키므로(외래 키) 행을 지울 수 없다.
--    지난 물건의 습득 장소 글(item.place_text, 예: '해운대역 승강장')은 기록이라 바꾸지 않는다
-- 3) 바꿀 이름이 이미 있으면(같은 호선·역·이름) 그 행은 건드리지 않는다(UNIQUE 충돌 방지)
--
-- 되돌리기(직접 실행):
--   UPDATE machine SET line = '2호선', station = '해운대' WHERE machine_id = 'KIOSK-A';
--   UPDATE machine SET station = '서면' WHERE machine_id = 'KIOSK-C';
--   UPDATE place SET line = '2호선', station = '해운대', label = replace(label, '중앙역', '해운대역') WHERE line = '1호선' AND station = '중앙';
--   UPDATE place SET station = '서면', label = replace(label, '초량역', '서면역') WHERE line = '1호선' AND station = '초량';
--   DELETE FROM schema_migration WHERE name = '019_busan_line1_stations_1111.sql';

UPDATE machine SET line = '1호선', station = '중앙' WHERE machine_id = 'KIOSK-A';
UPDATE machine SET line = '1호선', station = '초량' WHERE machine_id = 'KIOSK-C';

UPDATE place p SET line = '1호선', station = '중앙', label = replace(p.label, '해운대역', '중앙역')
 WHERE p.line = '2호선' AND p.station = '해운대'
   AND NOT EXISTS (SELECT 1 FROM place q WHERE q.line = '1호선' AND q.station = '중앙' AND q.label = replace(p.label, '해운대역', '중앙역'));

UPDATE place p SET station = '초량', label = replace(p.label, '서면역', '초량역')
 WHERE p.line = '1호선' AND p.station = '서면'
   AND NOT EXISTS (SELECT 1 FROM place q WHERE q.line = '1호선' AND q.station = '초량' AND q.label = replace(p.label, '서면역', '초량역'));

-- 혹시 빠진 장소가 있으면 채운다(012 의 12개와 같은 목록)
INSERT INTO place (line, station, label) VALUES
  ('1호선', '중앙', '중앙역 승강장'), ('1호선', '중앙', '대합실·개찰구 주변'), ('1호선', '중앙', '화장실'),
  ('1호선', '중앙', '엘리베이터·에스컬레이터'), ('1호선', '중앙', '열차 안'), ('1호선', '중앙', '출구 주변'),
  ('1호선', '중앙', '계단'), ('1호선', '중앙', '의자·벤치 주변'), ('1호선', '중앙', '역무실·안내센터 주변'),
  ('1호선', '중앙', '물품보관함 주변'), ('1호선', '중앙', '편의점·매점 주변'), ('1호선', '중앙', '환승 통로'),
  ('1호선', '초량', '초량역 승강장'), ('1호선', '초량', '대합실·개찰구 주변'), ('1호선', '초량', '화장실'),
  ('1호선', '초량', '엘리베이터·에스컬레이터'), ('1호선', '초량', '열차 안'), ('1호선', '초량', '출구 주변'),
  ('1호선', '초량', '계단'), ('1호선', '초량', '의자·벤치 주변'), ('1호선', '초량', '역무실·안내센터 주변'),
  ('1호선', '초량', '물품보관함 주변'), ('1호선', '초량', '편의점·매점 주변'), ('1호선', '초량', '환승 통로')
ON CONFLICT (line, station, label) DO NOTHING;
