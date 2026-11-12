# LF-9 회수 기록 정합성 점검

## 사용

기존 회수·통계 통합(PR #249) 위에 추가하는 읽기 전용 기능이다. 관리자 `/center`의 **기록 점검** 버튼 또는 `GET /api/admin/center/audit?sample_limit=50`을 사용한다. 기존 관리자 로그인·실제 DB 모드 조건이 적용된다.

실행 환경의 DB 연결이 이미 설정된 터미널에서는 다음과 같이 실행한다.

```powershell
python -m tools.audit_collections --limit 50
```

도구는 `DATABASE_URL`만 실행 환경에서 사용하고 `.env`를 읽지 않는다. 실제 데이터 수정·마이그레이션·외부 알림·로봇 호출을 하지 않는다. `--apply` 기능은 없다. 종료 코드는 0=검사 범위에서 지적 없음, 1=불일치/담당자 확인 항목 있음, 2=점검 미완료다. 입력 오류도 argparse 종료 코드 2다.

## 판정 항목

| 코드 | 판정 | 내용 |
|---|---|---|
| orphan_member | 불일치 | 회수 항목의 물건 또는 묶음 누락 |
| machine_mismatch | 불일치 | 물건과 묶음의 등록기계 불일치 |
| pending_status_mismatch | 불일치 | 도착 전인데 회수 중 상태가 아님 |
| arrived_status_mismatch | 불일치 | 도착 체크 후에도 등록기계 보관/회수 중 상태 |
| empty_collection | 불일치 | 빈 회수 묶음 |
| completion_mismatch | 불일치 | 전체 도착 여부와 완료 시각 유무 불일치 |
| completion_before_pickup | 불일치 | 완료 시각이 시작보다 빠름 |
| multiple_open_collections | 불일치 | 같은 물건에 도착 전 회수 항목이 여러 개 |
| invalid_active_alert | 불일치 | 도착했거나 원장 항목이 없는데 활성 미도착 알림이 존재 |
| missing_active_alert | 불일치 | 일부 도착 또는 알림 이력이 있는 묶음에서 활성 알림 누락 |
| missing_pickup_history | 불일치 | request_id 있는 단일 회수에 대응하는 회수 시작 이력 누락 |
| missing_arrival_history | 불일치 | request_id 있는 단일 회수의 도착 이력 누락 |
| multiple_collection_history | 담당자 확인 | 복수 회수 이력. 정당한 재회수인지 단정하지 않음 |
| transit_without_open_collection | 담당자 확인 | 회수 중인데 원장 미연결. 기존 시연·외부 경로 가능 |

도착 뒤 확인 중·수령 예약·반환 중·인계 대기·인계 완료·반환 보류는 정상 후속 상태로 허용한다. 운영에서 제외된 품목의 과거 기록도 품목만으로 오류 처리하지 않는다.

## 범위와 한계

- PostgreSQL에 도착 검토 시각과 확정된 마감시각이 없으므로, 전부 도착 전이고 알림 이력도 없는 묶음은 알림 누락으로 단정하지 않는다. `unreviewed_collections`로 따로 표시한다.
- `item_status_log`에는 회수 묶음 번호가 없다. 따라서 request_id가 없거나 동일 물건의 회수 묶음이 복수이면 이력 귀속 검사를 생략하고 `history_members_unchecked`에 포함한다. 이력 중복을 전부 증명하는 기능이 아니다.
- 점검 항목 수는 서로 다른 물건 수나 실제 누락 물건 수가 아니다. 하나의 기록에 여러 문제가 있을 수 있다.
- `status=ok`는 검사한 기록에서 지적이 없다는 뜻이며 실물 수량·소유권·파지·인계 성공을 뜻하지 않는다. 미판정 범위는 별도 표시한다.

## 조회와 오류 처리

스냅샷 거래를 보장하지 못하는 autocommit 연결은 점검 미완료로 처리한다. CLI와 기본 API 연결은 psycopg의 기본 거래 모드를 사용한다.

단일 `REPEATABLE READ, READ ONLY` 거래 안에서 총계·코드별 건수·샘플을 조회한다. 쿼리별 제한 시간은 3초다. 코드별 전체 건수를 계산하며 샘플만 1~200개로 제한한다. 55건 중 5건만 표시해도 전체 건수는 55다. 오류 항목을 담당자 확인 항목보다 먼저 표시한다.

접속 실패·권한 부족·스키마 누락·시간 초과 등으로 완료하지 못하면 `completed=false`, `status=unavailable`, `issue_count=null`을 반환한다. API는 503이며 정상 0건으로 대체하지 않는다. 연결정보나 내부 오류 문자열은 응답에 포함하지 않는다.

조회 대상은 `collection`, `collection_item`, `collection_alert`, `item_status_log`와 `item`의 item_id·machine_id·status뿐이다. 연락처·인증·비공개 특징·원본 사진은 조회하지 않는다. CLI에 전용 읽기 로그인을 사용한다면 DBA가 이 범위의 권한을 별도로 검토할 수 있다. 이번 작업은 역할이나 운영 권한을 설치하지 않는다.

화면은 실패 시 이전 결과를 지우며 새 목록 요청 또는 회수/도착 변경 요청을 보내는 순간에도 이전 점검을 무효화한다. 다른 사용자의 변경을 자동 감시하지 않으므로 점검 시각을 표시한다.
