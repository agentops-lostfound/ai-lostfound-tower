-- 008 (11/6) 보관함 사진 확인 반영 (LF-8, 변재원) — 007 시작 배치를 실제 판에 맞춤
-- 1) 모형폰 행(R1): 가로로 두면 인식이 잘 안 돼 폰을 사선으로 둔다(11/6 결정). 화면에서 메모를 바꾼 칸은 그대로 둔다
-- 2) R1 은 다른 행보다 칸 간격이 넓다(판 끝 ArUco ID0 쪽, R2 와의 간격도 큼) → 저장 자세·비전 영역을 R1 만 따로 잡는다
-- 3) 인계 구역 H-1(제출보관함 20×20cm)은 로봇팔 받침 반대쪽 긴 변 바깥, 대략 R2~R3 옆
-- agents/storage.py LAYOUT 과 같게 유지한다(tests/test_storage.py 가 확인)
UPDATE storage_slot SET note = '사선 배치·간격 넓음' WHERE section_code = 'R1' AND note = '가로 배치';
UPDATE storage_slot SET note = '20×20cm·로봇팔 반대쪽' WHERE slot_id = 'H-1' AND note = '20×20cm';
