-- 009 (11/6) 행별 품목을 판 사진에 맞춤 (LF-8, 변재원) — 팀이 임의로 정한 시연 시작값
-- 사진: R1 모형폰(사선) · R2 비어 있음 · R3 립밤 2개 · R4 카드지갑+반지갑 → 지갑 행, 남은 품목(USB·핸드크림·보조배터리)은 R2
-- 007 시작값 그대로일 때만 바꾼다(화면·API 로 이미 바꾼 값은 보존). agents/storage.py LAYOUT 과 같게(tests/test_storage.py)
UPDATE storage_section SET label = '2행 USB·핸드크림·보조배터리', allowed_categories = '{USB,핸드크림,보조배터리}'
 WHERE section_code = 'R2' AND allowed_categories = '{USB,핸드크림}';
UPDATE storage_section SET label = '4행 지갑', allowed_categories = '{지갑}'
 WHERE section_code = 'R4' AND allowed_categories = '{지갑,보조배터리}';
