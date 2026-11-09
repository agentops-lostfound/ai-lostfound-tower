-- 017: 표·칸마다 한글 설명(COMMENT ON) 달기 — LF-8 (요청: 김재민, 11/9)
-- 한줄 설명: 표 이름·칸 이름·데이터는 바꾸지 않고, DB 안에서 \d+ 로 설명이 보이게 한다. 여러 번 실행해도 안전(설명 덮어쓰기만).
-- 되돌리기: COMMENT ON TABLE 표이름 IS NULL / COMMENT ON COLUMN 표.칸 IS NULL

-- schema_migration 은 tools/db_migrate.py 가 만드는 표(통합 시험은 마이그레이션을 직접 실행해 없을 수 있어 같은 정의로 먼저 보장)
CREATE TABLE IF NOT EXISTS schema_migration (
    name VARCHAR(128) PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now());

-- ========== 기준 정보 ==========
COMMENT ON TABLE machine IS '습득물 등록기계(키오스크)와 본센터 목록';
COMMENT ON COLUMN machine.machine_id IS '기계 번호. 예: KIOSK-A, CENTER';
COMMENT ON COLUMN machine.kind IS '종류: kiosk(등록기계) 또는 center(본센터)';
COMMENT ON COLUMN machine.line IS '호선(등록기계만 채움)';
COMMENT ON COLUMN machine.station IS '설치된 역';
COMMENT ON COLUMN machine.is_virtual IS '시연용 가상 기계 여부';

COMMENT ON TABLE place IS '습득 장소 추천 목록(역마다 화장실·승강장 등, 자주 나온 순서로 보여 줌)';
COMMENT ON COLUMN place.place_id IS '장소 번호(자동 증가)';
COMMENT ON COLUMN place.line IS '호선';
COMMENT ON COLUMN place.station IS '역';
COMMENT ON COLUMN place.label IS '장소 이름. 예: 화장실, 대합실·개찰구 주변';
COMMENT ON COLUMN place.use_count IS '선택된 횟수(추천 순서용)';

-- ========== 접수 ==========
COMMENT ON TABLE item IS '접수된 분실물 1개 = 1행. 상태가 접수부터 인계 완료까지 바뀐다';
COMMENT ON COLUMN item.item_id IS '접수 번호(화면에 보임). 예: A-20261103-0001, 시연용 A-W01';
COMMENT ON COLUMN item.machine_id IS '접수한 등록기계(machine 참조)';
COMMENT ON COLUMN item.place_id IS '고른 추천 장소(place 참조, 직접 입력이면 비어 있음)';
COMMENT ON COLUMN item.place_text IS '습득 장소 글자(고른 장소 또는 직접 입력, 필수)';
COMMENT ON COLUMN item.received_at IS '접수한 시각';
COMMENT ON COLUMN item.status IS '현재 상태: 등록기계 보관·회수 중·본센터 보관·확인 중·승인·수령 예약·반환 중·인계 대기·인계 완료·반환 보류';
COMMENT ON COLUMN item.category IS '품목. 11/9 운영 4종: 지갑(카드지갑)·모형폰(목업폰)·핸드크림·보조배터리. USB·립밤은 옛 기록용으로만 허용, 판단 불가면 확인 불가';
COMMENT ON COLUMN item.features IS '공개 특징 JSON(color·shape·material·confidence). 분실인 화면에 보여도 되는 것';
COMMENT ON COLUMN item.private_features IS '비공개 특징 JSON(mark·visible_text). 확인 질문의 정답이라 후보 카드·MCP에 안 보임';
COMMENT ON COLUMN item.photo_path IS '접수 사진 파일 위치(사진 자체는 DB 밖에 저장)';
COMMENT ON COLUMN item.object_id IS '시연·평가용 물건 ID(정답지 W01 등)';
COMMENT ON COLUMN item.updated_at IS '마지막으로 바뀐 시각';

COMMENT ON TABLE finder_contact IS '습득자 연락처(입력은 선택 = 저장 동의). 감사 연락에만 쓰고 직원만 열람, 인계 완료 30일 뒤 삭제';
COMMENT ON COLUMN finder_contact.item_id IS '어느 접수 물건의 습득자인지(item 참조)';
COMMENT ON COLUMN finder_contact.name IS '습득자 이름';
COMMENT ON COLUMN finder_contact.phone IS '습득자 전화번호';
COMMENT ON COLUMN finder_contact.consented_at IS '저장에 동의한 시각';

COMMENT ON TABLE item_status_log IS '물건 상태가 바뀐 기록(무엇에서 무엇으로, 누가, 언제)';
COMMENT ON COLUMN item_status_log.id IS '기록 번호(자동 증가)';
COMMENT ON COLUMN item_status_log.item_id IS '상태가 바뀐 물건(item 참조)';
COMMENT ON COLUMN item_status_log.from_status IS '바뀌기 전 상태(처음 등록이면 비어 있음)';
COMMENT ON COLUMN item_status_log.to_status IS '바뀐 뒤 상태';
COMMENT ON COLUMN item_status_log.changed_by IS '바꾼 주체: kiosk(등록기계)·staff(직원)·tower(관제탑)·system';
COMMENT ON COLUMN item_status_log.at IS '바뀐 시각';

-- ========== 회수(등록기계 → 본센터, 하루 1번) ==========
COMMENT ON TABLE collection IS '회수 1회 = 1행. 직원이 등록기계 물건을 꺼내 본센터로 옮기는 묶음';
COMMENT ON COLUMN collection.collection_id IS '회수 번호(자동 증가)';
COMMENT ON COLUMN collection.machine_id IS '물건을 꺼낸 등록기계(machine 참조)';
COMMENT ON COLUMN collection.picked_at IS '등록기계에서 꺼낸 시각';
COMMENT ON COLUMN collection.arrived_at IS '본센터 도착(입고 확인) 시각, 도착 전에는 비어 있음';

COMMENT ON TABLE collection_item IS '회수 묶음에 들어 있는 물건 목록(도착했는지 확인해 빠진 물건을 찾는다)';
COMMENT ON COLUMN collection_item.collection_id IS '회수 번호(collection 참조)';
COMMENT ON COLUMN collection_item.item_id IS '회수에 들어간 물건(item 참조)';
COMMENT ON COLUMN collection_item.arrived IS '본센터 도착이 확인되면 TRUE';

-- ========== 찾기(분실인 웹) ==========
COMMENT ON TABLE claim IS '찾기 요청 1건 = 분실인 1명의 1회 방문 과정. 동의·가린 신분 정보·분실 설명을 담는다';
COMMENT ON COLUMN claim.claim_id IS '찾기 요청 번호. 예: C-20261103-0001';
COMMENT ON COLUMN claim.consented_at IS '필수 동의 시각(동의 없으면 요청을 만들지 않음)';
COMMENT ON COLUMN claim.name_masked IS '신분증 OCR 이름을 가린 값. 예: 변*원';
COMMENT ON COLUMN claim.id_no_masked IS '신분증 번호를 가린 값(주민등록번호 칸은 없음)';
COMMENT ON COLUMN claim.id_verified IS '웹 신분증 OCR 인증을 통과했는지(관제탑 관문 id_verified)';
COMMENT ON COLUMN claim.description IS '분실인이 설명한 특징 JSON(category·color·shape·mark·visible_text·material만 허용)';
COMMENT ON COLUMN claim.lost_line IS '잃어버린 호선';
COMMENT ON COLUMN claim.lost_station IS '잃어버린 역';
COMMENT ON COLUMN claim.lost_date IS '잃어버린 날짜';
COMMENT ON COLUMN claim.created_at IS '요청을 만든 시각';

COMMENT ON TABLE claim_candidate IS '찾기 요청별 후보 물건 1~3순위(점수는 내부용, 분실인 화면에 안 보임)';
COMMENT ON COLUMN claim_candidate.claim_id IS '찾기 요청 번호(claim 참조)';
COMMENT ON COLUMN claim_candidate.item_id IS '후보 물건(item 참조)';
COMMENT ON COLUMN claim_candidate.rank IS '후보 순위 1~3';
COMMENT ON COLUMN claim_candidate.score IS '매칭 점수(내부용)';

COMMENT ON TABLE quiz_attempt IS '확인 질문 시도 기록. 정답과 입력한 답은 저장하지 않고 맞았는지만 남김';
COMMENT ON COLUMN quiz_attempt.id IS '시도 번호(자동 증가)';
COMMENT ON COLUMN quiz_attempt.claim_id IS '찾기 요청 번호(claim 참조)';
COMMENT ON COLUMN quiz_attempt.item_id IS '질문한 대상 물건(item 참조)';
COMMENT ON COLUMN quiz_attempt.field IS '물은 항목: mark·visible_text·place·color·shape';
COMMENT ON COLUMN quiz_attempt.passed IS '맞았는지(TRUE=통과)';
COMMENT ON COLUMN quiz_attempt.at IS '시도한 시각';

COMMENT ON TABLE reservation IS '수령 예약(메인 AI 승인 뒤 만들어짐). 찾기 요청 1건에 예약 1개';
COMMENT ON COLUMN reservation.claim_id IS '찾기 요청 번호(claim 참조, 예약의 기본키)';
COMMENT ON COLUMN reservation.item_id IS '수령할 물건(item 참조)';
COMMENT ON COLUMN reservation.visit_date IS '방문해서 받기로 한 날짜';
COMMENT ON COLUMN reservation.status IS '예약 상태: booked(예약)·visited(방문)·cancelled(취소)';
COMMENT ON COLUMN reservation.created_at IS '예약을 만든 시각';

-- ========== 반환(관제탑) ==========
COMMENT ON TABLE return_case IS '반환 시도 결과 1건 = 1행. 관제탑이 반환이 끝날 때마다 저장';
COMMENT ON COLUMN return_case.case_id IS '반환 사건 번호(같은 번호로 두 번 실행하지 않음)';
COMMENT ON COLUMN return_case.item_id IS '반환 대상 물건(item 참조)';
COMMENT ON COLUMN return_case.claim_id IS '웹 찾기에서 온 반환이면 그 요청 번호(claim 참조)';
COMMENT ON COLUMN return_case.decision IS '결정: returned(반환)·rejected(거절)·staff_check(직원 확인)·stopped(정지)';
COMMENT ON COLUMN return_case.reason IS '결정 이유(개인정보 없음)';
COMMENT ON COLUMN return_case.approved IS '메인 AI 승인 여부';
COMMENT ON COLUMN return_case.matched_object IS '매칭된 물건 ID(시연·평가용)';
COMMENT ON COLUMN return_case.seconds IS '반환에 걸린 시간(초)';
COMMENT ON COLUMN return_case.created_at IS '저장한 시각';

COMMENT ON TABLE return_step IS '반환 사건의 단계별 진행 기록(위치 확인·집기 등)';
COMMENT ON COLUMN return_step.id IS '단계 기록 번호(자동 증가)';
COMMENT ON COLUMN return_step.case_id IS '반환 사건 번호(return_case 참조)';
COMMENT ON COLUMN return_step.step IS '단계 이름';
COMMENT ON COLUMN return_step.detail IS '단계 설명';
COMMENT ON COLUMN return_step.at IS '단계 시각';

-- ========== 보관함(구역·칸·배정·재고 점검) ==========
COMMENT ON TABLE storage_section IS '본센터 보관함 구역(열 R1~R4 = 탑뷰 왼쪽→오른쪽: 휴대폰·카드지갑·보조배터리·핸드크림, 직원 선반 S, 인계 구역 H)';
COMMENT ON COLUMN storage_section.section_code IS '구역 코드. 예: R1, H, S';
COMMENT ON COLUMN storage_section.label IS '구역 이름(화면 표시용)';
COMMENT ON COLUMN storage_section.kind IS '구역 종류: shelf(보관 선반)·handover(인계 구역)·staff(직원 보관 선반, 로봇 안 씀)';
COMMENT ON COLUMN storage_section.allowed_categories IS '넣을 수 있는 품목 목록(빈 배열 = 제한 없음)';
COMMENT ON COLUMN storage_section.bounds_mm IS '작업대 mm 좌표 [x1, y1, x2, y2] (ArUco 기준, 선택)';
COMMENT ON COLUMN storage_section.sort_order IS '화면에 보여 줄 순서';

COMMENT ON TABLE storage_slot IS '보관함 칸(구역 안의 자리). 로봇이 집거나 놓는 저장 자세와 연결';
COMMENT ON COLUMN storage_slot.slot_id IS '칸 번호. 예: R1-1, H-1';
COMMENT ON COLUMN storage_slot.section_code IS '속한 구역(storage_section 참조)';
COMMENT ON COLUMN storage_slot.slot_no IS '구역 안의 칸 순서: 1 = 로봇 가까운 칸, 2 = 먼 칸';
COMMENT ON COLUMN storage_slot.pose_name IS '로봇 저장 자세 이름(티칭 전에는 비어 있음). 칸 번호 N(가까운 줄 1·3·5·7, 먼 줄 2·4·6·8) = pose_N, H-1 = close';
COMMENT ON COLUMN storage_slot.note IS '칸 메모. 예: 45도 사선 배치';

COMMENT ON TABLE storage_assignment IS '어느 칸에 어느 물건이 들어 있는지(한 칸에 한 물건, 인계 완료되면 자동으로 지워짐)';
COMMENT ON COLUMN storage_assignment.slot_id IS '칸 번호(storage_slot 참조)';
COMMENT ON COLUMN storage_assignment.item_id IS '들어 있는 물건(item 참조, 한 물건은 한 칸에만)';
COMMENT ON COLUMN storage_assignment.assigned_at IS '칸에 배정한 시각';
COMMENT ON COLUMN storage_assignment.assigned_by IS '배정한 주체: staff(직원)·tower(관제탑)·system';

COMMENT ON TABLE inventory_check IS '구역별 재고 점검 기록(예상 개수와 카메라로 센 개수 비교)';
COMMENT ON COLUMN inventory_check.id IS '점검 번호(자동 증가)';
COMMENT ON COLUMN inventory_check.section_code IS '점검한 구역(storage_section 참조)';
COMMENT ON COLUMN inventory_check.item_id IS '특정 물건을 점검했다면 그 물건(item 참조)';
COMMENT ON COLUMN inventory_check.expected_count IS 'DB 기준 있어야 하는 개수';
COMMENT ON COLUMN inventory_check.detected_count IS '카메라가 센 개수(못 셌으면 비어 있음)';
COMMENT ON COLUMN inventory_check.status IS '점검 결과 코드: count_match(일치)·count_mismatch(불일치)·verification_unavailable(확인 불가)·resolution_mismatch·invalid_calibration·section_out_of_frame·match_held';
COMMENT ON COLUMN inventory_check.at IS '점검 시각';

-- ========== 관리용 표·통계 보기 ==========
COMMENT ON TABLE schema_migration IS 'DB 바뀐 점(center/migrations) 중 이미 적용한 파일 목록. tools/db_migrate.py 가 관리';
COMMENT ON COLUMN schema_migration.name IS '적용한 마이그레이션 파일 이름';
COMMENT ON COLUMN schema_migration.applied_at IS '적용한 시각';

COMMENT ON VIEW stats_item IS '통계 질문(Text2SQL)용 읽기 전용 보기: 접수 물건 + 설치 호선·역(개인정보 칸 없음)';
COMMENT ON VIEW stats_return IS '통계 질문(Text2SQL)용 읽기 전용 보기: 반환 결과(개인정보 칸 없음)';
COMMENT ON COLUMN stats_item.item_id IS '접수 번호(item.item_id)';
COMMENT ON COLUMN stats_item.machine_id IS '접수한 등록기계 번호';
COMMENT ON COLUMN stats_item.line IS '등록기계 설치 호선';
COMMENT ON COLUMN stats_item.station IS '등록기계 설치 역';
COMMENT ON COLUMN stats_item.category IS '품목';
COMMENT ON COLUMN stats_item.status IS '현재 상태';
COMMENT ON COLUMN stats_item.received_at IS '접수한 시각';
COMMENT ON COLUMN stats_return.case_id IS '반환 사건 번호';
COMMENT ON COLUMN stats_return.item_id IS '반환 대상 물건 번호';
COMMENT ON COLUMN stats_return.decision IS '결정(returned·rejected·staff_check·stopped)';
COMMENT ON COLUMN stats_return.approved IS '메인 AI 승인 여부';
COMMENT ON COLUMN stats_return.seconds IS '반환에 걸린 시간(초)';
COMMENT ON COLUMN stats_return.created_at IS '저장한 시각';
