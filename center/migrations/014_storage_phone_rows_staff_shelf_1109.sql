-- 014 (11/9) 보관 칸 규칙 실제 판에 맞춤 + 직원 보관 선반 S (LF-13, 변재원) — 사용자 실측·결정(docs/design/storage_slots.md)
-- 1) R1(왼쪽 두 칸)은 휴대폰을 사선으로 두어 간격이 넓다 → 휴대폰('모형폰') 전용
--    R2~R4(나머지 6칸)는 휴대폰 밖 5종(지갑·USB·립밤·핸드크림·보조배터리)을 모두 받는다(행마다 품목 제한 없음)
--    009 시작값 그대로일 때만 바꾼다(화면·API 로 이미 바꾼 값은 보존). agents/storage.py LAYOUT 과 같게(tests/test_storage.py)
-- 2) 제출보관함 H-1 은 보관판 위쪽(로봇 반대쪽) 긴 변 가운데에 붙어 있다 → 칸 메모만 고침(008 값 그대로일 때만)
-- 3) 직원 보관 선반 S: 맞는 빈 칸이 없을 때 넘치는 물건 자리. 로봇이 집지 않고 비전 내보내기에도 넣지 않는다
--    칸(S-1, S-2 …)은 직원이 선반으로 옮길 때 관제탑이 하나씩 만든다(agents/storage.py move_to_shelf) → 여기서는 구역만
--    구역 종류에 'staff' 를 더하려고 007 의 kind 검사 규칙을 바꾼다
-- 계약 상태(contracts.ITEM_STATUS)는 바꾸지 않는다: 선반 물건은 상태 '본센터 보관' + 칸 S-n(위치 정보)로 구별
--
-- 되돌리기(직접 실행, 선반에 물건이 없을 때만):
--   DELETE FROM storage_slot WHERE section_code = 'S';           -- 선반에 물건이 있으면 먼저 칸으로 옮기거나 칸 비우기
--   DELETE FROM storage_section WHERE section_code = 'S';
--   ALTER TABLE storage_section DROP CONSTRAINT IF EXISTS storage_section_kind_check;
--   ALTER TABLE storage_section ADD CONSTRAINT storage_section_kind_check CHECK (kind IN ('shelf', 'handover'));
--   UPDATE storage_section SET label = '1행 모형폰' WHERE section_code = 'R1' AND label = 'R1 휴대폰 전용';
--   UPDATE storage_section SET label = '2행 USB·핸드크림·보조배터리', allowed_categories = '{USB,핸드크림,보조배터리}' WHERE section_code = 'R2' AND label = 'R2 그 밖의 물건';
--   UPDATE storage_section SET label = '3행 립밤', allowed_categories = '{립밤}' WHERE section_code = 'R3' AND label = 'R3 그 밖의 물건';
--   UPDATE storage_section SET label = '4행 지갑', allowed_categories = '{지갑}' WHERE section_code = 'R4' AND label = 'R4 그 밖의 물건';
--   UPDATE storage_slot SET note = '20×20cm·로봇팔 반대쪽' WHERE slot_id = 'H-1' AND note = '20×20cm·보관판 위쪽 가운데';
--   DELETE FROM schema_migration WHERE name = '014_storage_phone_rows_staff_shelf_1109.sql';

UPDATE storage_section SET label = 'R1 휴대폰 전용', allowed_categories = '{모형폰}'
 WHERE section_code = 'R1' AND allowed_categories = '{모형폰}';
UPDATE storage_section SET label = 'R2 그 밖의 물건', allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}'
 WHERE section_code = 'R2' AND allowed_categories = '{USB,핸드크림,보조배터리}';
UPDATE storage_section SET label = 'R3 그 밖의 물건', allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}'
 WHERE section_code = 'R3' AND allowed_categories = '{립밤}';
UPDATE storage_section SET label = 'R4 그 밖의 물건', allowed_categories = '{지갑,USB,립밤,핸드크림,보조배터리}'
 WHERE section_code = 'R4' AND allowed_categories = '{지갑}';

UPDATE storage_slot SET note = '20×20cm·보관판 위쪽 가운데' WHERE slot_id = 'H-1' AND note = '20×20cm·로봇팔 반대쪽';

ALTER TABLE storage_section DROP CONSTRAINT IF EXISTS storage_section_kind_check;
ALTER TABLE storage_section ADD CONSTRAINT storage_section_kind_check CHECK (kind IN ('shelf', 'handover', 'staff'));

INSERT INTO storage_section (section_code, label, kind, allowed_categories, sort_order) VALUES
  ('S', '직원 보관 선반', 'staff', '{}', 6)
ON CONFLICT (section_code) DO NOTHING;
