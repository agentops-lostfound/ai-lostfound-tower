-- 015 (11/9) 립밤을 운영 품목에서 빼고 보관 칸을 열(탑뷰 왼쪽부터 R1~R4)마다 품목 하나로 (LF-13, 변재원) — 사용자 결정
-- 1) 립밤 제외: YOLO 탑뷰 모델이 립밤을 잘 찾지 못한다(vision/DETECTION_STATUS.md). 운영 품목 = 지갑·USB·휴대폰·핸드크림·보조배터리
--    (agents/contracts.py ACTIVE_CATEGORIES). 계약 품목(CATEGORIES)·item.category 검사에는 립밤을 남긴다(옛 기록 보존)
-- 2) 열 배정(각 열 2칸: -1 로봇 가까운 칸, -2 먼 칸)
--    R1 휴대폰 전용(45도 사선, 탑뷰에서 '/' — 상단 카메라가 오른쪽 위·충전 단자가 왼쪽 아래)
--    R2 지갑(실물은 카드지갑) · R3 보조배터리 · R4 핸드크림·USB(둘 중 무엇을 둘지 아직 미정 → 지금은 둘 다 받음)
--    014 값 그대로일 때만 바꾼다(화면·API 로 이미 바꾼 값은 보존). agents/storage.py LAYOUT 과 같게(tests/test_storage.py)
-- 3) 이미 칸에 들어 있는 물건(storage_assignment)은 옮기지 않는다. 칸이 꽉 찼을 때 칸 대기·직원 보관 선반 정책은 그대로
--    운영하지 않는 품목(립밤)은 받는 열이 없으므로 새로 들어오면 직원 보관 선반으로 간다(agents/storage.py recommend_slot → None)
--
-- 되돌리기(직접 실행):
--   UPDATE storage_section SET label = 'R2 그 밖의 물건', allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}' WHERE section_code = 'R2' AND label = 'R2 지갑';
--   UPDATE storage_section SET label = 'R3 그 밖의 물건', allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}' WHERE section_code = 'R3' AND label = 'R3 보조배터리';
--   UPDATE storage_section SET label = 'R4 그 밖의 물건', allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}' WHERE section_code = 'R4' AND label = 'R4 핸드크림·USB';
--   UPDATE storage_slot SET note = '사선 배치·간격 넓음' WHERE section_code = 'R1' AND note = '45도 사선·상단 오른쪽 위';
--   DELETE FROM schema_migration WHERE name = '015_storage_columns_no_lipbalm_1109.sql';

UPDATE storage_section SET label = 'R2 지갑', allowed_categories = '{지갑}'
 WHERE section_code = 'R2' AND allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}';
UPDATE storage_section SET label = 'R3 보조배터리', allowed_categories = '{보조배터리}'
 WHERE section_code = 'R3' AND allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}';
UPDATE storage_section SET label = 'R4 핸드크림·USB', allowed_categories = '{핸드크림,USB}'
 WHERE section_code = 'R4' AND allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}';

UPDATE storage_slot SET note = '45도 사선·상단 오른쪽 위' WHERE section_code = 'R1' AND note = '사선 배치·간격 넓음';
