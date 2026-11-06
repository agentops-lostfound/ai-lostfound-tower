-- 003 (11/3) 등록기계 습득 장소 추천 목록(시연용) — agents/intake.py DEMO_PLACES 와 같은 목록
-- 등록기계 화면 2번(어디서 주웠나요?)이 GET /places 로 읽는다. 고른 장소는 use_count 가 늘어 다음에 앞에 나온다
INSERT INTO place (line, station, label) VALUES
  ('2호선', '해운대', '해운대역 승강장'),
  ('2호선', '해운대', '대합실·개찰구 주변'),
  ('2호선', '해운대', '화장실'),
  ('2호선', '해운대', '엘리베이터·에스컬레이터'),
  ('2호선', '해운대', '열차 안'),
  ('2호선', '해운대', '출구 주변')
ON CONFLICT (line, station, label) DO NOTHING;
