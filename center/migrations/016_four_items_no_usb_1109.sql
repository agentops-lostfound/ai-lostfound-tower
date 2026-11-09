-- 016 (11/9) 품목 4종 고정: 목업폰 · 보조배터리 · 핸드크림 · 카드지갑 (LF-13, 변재원) — 사용자 결정(USB 도 운영 품목에서 뺌)
-- 1) 운영 품목 = agents/contracts.py ACTIVE_CATEGORIES(지갑·모형폰·핸드크림·보조배터리). 계약 품목(CATEGORIES)·item.category 검사에는
--    USB·립밤을 남긴다(옛 기록 보존). 운영하지 않는 품목이 새로 들어오면 받는 열이 없어 직원 보관 선반으로 간다
-- 2) 열 배정: R1 휴대폰(45도 '/') · R2 카드지갑 · R3 보조배터리 · R4 핸드크림(015 의 '핸드크림·USB' → 핸드크림만)
--    015 값 그대로일 때만 바꾼다(화면·API 로 이미 바꾼 값은 보존). agents/storage.py LAYOUT 과 같게(tests/test_storage.py)
-- 3) 이미 칸에 들어 있는 물건(storage_assignment)은 옮기지 않는다(R4 에 USB 가 있으면 그대로 두고 직원이 꺼냄)
--
-- 되돌리기(직접 실행):
--   UPDATE storage_section SET label = 'R2 지갑' WHERE section_code = 'R2' AND label = 'R2 카드지갑';
--   UPDATE storage_section SET label = 'R4 핸드크림·USB', allowed_categories = '{핸드크림,USB}' WHERE section_code = 'R4' AND label = 'R4 핸드크림';
--   DELETE FROM schema_migration WHERE name = '016_four_items_no_usb_1109.sql';

UPDATE storage_section SET label = 'R2 카드지갑'
 WHERE section_code = 'R2' AND label = 'R2 지갑' AND allowed_categories = '{지갑}';
UPDATE storage_section SET label = 'R4 핸드크림', allowed_categories = '{핸드크림}'
 WHERE section_code = 'R4' AND allowed_categories = '{핸드크림,USB}';
