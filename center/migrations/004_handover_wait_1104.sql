-- 004 (11/4) 물건 상태에 '인계 대기' 추가 — 로봇이 바구니에 넣은 것과 직원이 분실인에게 건넨 것(인계 완료)을 나눔
-- 근거: 순필님 LF-11·12 검토(docs/progress/vision-robot-integration-review.md), agents/contracts.py ITEM_STATUS
-- item.status 의 검사 이름은 PostgreSQL 이 자동으로 붙인 item_status_check. 지우고 같은 이름으로 다시 만든다(몇 번 실행해도 같음)
ALTER TABLE item DROP CONSTRAINT IF EXISTS item_status_check;
ALTER TABLE item ADD CONSTRAINT item_status_check
    CHECK (status IN ('등록기계 보관', '회수 중', '본센터 보관', '확인 중',
                      '승인·수령 예약', '반환 중', '인계 대기', '인계 완료', '반환 보류'));
