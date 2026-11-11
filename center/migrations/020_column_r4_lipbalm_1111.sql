-- 020 (11/11) 보관함 R4 열 품목: 카드지갑 → 립밤 (LF-18, 변재원) — 사용자 결정
-- 1) 포토박스 탑뷰(Qwen)가 카드지갑을 잘 못 알아봐서 운영 품목을 목업폰 · 보조배터리 · 핸드크림 · 립밤 으로 바꿈(agents/contracts.py ACTIVE_CATEGORIES)
-- 2) 칸 위치·칸 번호·저장 자세 이름(R4-1 = pose_7, R4-2 = pose_8)은 그대로. 립밤은 세로로 두므로 pose_7·8 은 김건태님이 다시 티칭
-- 3) 018 값 그대로일 때만 바꾼다(화면·API 로 이미 바꾼 값은 보존). agents/storage.py LAYOUT 과 같게(tests/test_storage.py)
-- 4) 이미 R4 에 들어 있는 카드지갑(storage_assignment)은 옮기지 않는다 — 직원이 꺼내 직원 보관 선반으로
--
-- 되돌리기(직접 실행):
--   UPDATE storage_section SET label = 'R4 카드지갑', allowed_categories = '{지갑}' WHERE section_code = 'R4' AND label = 'R4 립밤';
--   DELETE FROM schema_migration WHERE name = '020_column_r4_lipbalm_1111.sql';

UPDATE storage_section SET label = 'R4 립밤', allowed_categories = '{립밤}'
 WHERE section_code = 'R4' AND allowed_categories = '{지갑}';
