-- 018 (11/10) 보관함 열 순서 다시 정함: 왼쪽부터 휴대폰 · 보조배터리 · 핸드크림 · 카드지갑 (LF-13, 변재원) — 사용자 결정
-- 1) 016 의 R2 카드지갑 · R3 보조배터리 · R4 핸드크림 → R2 보조배터리 · R3 핸드크림 · R4 카드지갑 (R1 휴대폰은 그대로).
--    실물 보관판 배치와 로봇 티칭(칸 위치 = pose_1~8)은 그대로이고, 칸에 두는 **품목만** 바뀐다
-- 2) 016 값 그대로일 때만 바꾼다(화면·API 로 이미 바꾼 값은 보존). agents/storage.py LAYOUT 과 같게(tests/test_storage.py)
-- 3) 이미 칸에 들어 있는 물건(storage_assignment)은 옮기지 않는다 — 다른 품목 열에 남은 물건은 직원이 꺼내 맞는 열에 다시 넣는다
--
-- 되돌리기(직접 실행):
--   UPDATE storage_section SET label = 'R2 카드지갑', allowed_categories = '{지갑}' WHERE section_code = 'R2' AND label = 'R2 보조배터리';
--   UPDATE storage_section SET label = 'R3 보조배터리', allowed_categories = '{보조배터리}' WHERE section_code = 'R3' AND label = 'R3 핸드크림';
--   UPDATE storage_section SET label = 'R4 핸드크림', allowed_categories = '{핸드크림}' WHERE section_code = 'R4' AND label = 'R4 카드지갑';
--   DELETE FROM schema_migration WHERE name = '018_columns_phone_battery_cream_wallet_1110.sql';

UPDATE storage_section SET label = 'R2 보조배터리', allowed_categories = '{보조배터리}'
 WHERE section_code = 'R2' AND allowed_categories = '{지갑}';
UPDATE storage_section SET label = 'R3 핸드크림', allowed_categories = '{핸드크림}'
 WHERE section_code = 'R3' AND allowed_categories = '{보조배터리}';
UPDATE storage_section SET label = 'R4 카드지갑', allowed_categories = '{지갑}'
 WHERE section_code = 'R4' AND allowed_categories = '{핸드크림}';
