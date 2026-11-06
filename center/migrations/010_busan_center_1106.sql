-- 010 (11/6) 역 정리 (LF-13, 변재원) — 본센터 = 1호선 부산역, 등록기계는 해운대(KIOSK-A)·서면(KIOSK-C) 두 곳만
-- 중앙역(KIOSK-B)은 시연에서 빼기로 함(11/6). agents/contracts.py MACHINE_LETTERS, agents/intake.py DEMO_PLACES 와 같게
-- 안전: 중앙역 기록을 가리키는 물건·회수가 남아 있으면 지우지 않고 NOTICE 만 남긴다(기록 보존)

UPDATE machine SET line = '1호선', station = '부산' WHERE machine_id = 'CENTER';

INSERT INTO place (line, station, label) VALUES
  ('1호선', '부산', '부산역 승강장'),
  ('1호선', '부산', '대합실·개찰구 주변'),
  ('1호선', '부산', '화장실'),
  ('1호선', '부산', '엘리베이터·에스컬레이터'),
  ('1호선', '부산', '열차 안'),
  ('1호선', '부산', '출구 주변')
ON CONFLICT (line, station, label) DO NOTHING;

DELETE FROM place p WHERE p.line = '1호선' AND p.station = '중앙'
  AND NOT EXISTS (SELECT 1 FROM item i WHERE i.place_id = p.place_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM item WHERE machine_id = 'KIOSK-B')
       OR EXISTS (SELECT 1 FROM collection WHERE machine_id = 'KIOSK-B') THEN
        RAISE NOTICE 'KIOSK-B 를 가리키는 물건·회수 기록이 있어 등록기계 행은 남김(화면·코드에서는 이미 빠짐)';
    ELSE
        DELETE FROM machine WHERE machine_id = 'KIOSK-B';
    END IF;
END $$;
