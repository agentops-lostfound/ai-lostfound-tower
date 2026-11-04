-- 005 (11/4) 가상 시연용 서면역 등록기계 KIOSK-C + 습득 장소 추천 — agents/contracts.py MACHINE_LETTERS, agents/intake.py DEMO_PLACES 와 같게
-- 디스코드 분실물 채널에 "서면역 5번 출구 앞에서 주웠어요" 를 보내는 가상 시연(docs/design/virtual_demo.md)에서 쓴다
INSERT INTO machine VALUES ('KIOSK-C', 'kiosk', '1호선', '서면', TRUE)
ON CONFLICT (machine_id) DO NOTHING;

INSERT INTO place (line, station, label) VALUES
  ('1호선', '서면', '서면역 승강장'),
  ('1호선', '서면', '대합실·개찰구 주변'),
  ('1호선', '서면', '화장실'),
  ('1호선', '서면', '엘리베이터·에스컬레이터'),
  ('1호선', '서면', '열차 안'),
  ('1호선', '서면', '출구 주변')
ON CONFLICT (line, station, label) DO NOTHING;
