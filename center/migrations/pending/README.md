# 보류 중인 DB 변경 (자동 적용 안 됨)

한줄 설명: 이 폴더의 `.sql` 은 `tools/db_migrate.py` 가 읽지 않는다(바로 위 `center/migrations/*.sql` 만 자동 적용). 관제탑을 켤 때 팀 DB 가 저절로 바뀌지 않도록 검토 전 변경을 여기에 둔다.

| 파일 | 출처 | 하는 일 | 상태 |
| --- | --- | --- | --- |
| `006_collection_alerts_1104.sql` | 정연우 LF-9(회수 관리), PR #61 에 함께 들어옴. 원래 이름 `005_collection_1104.sql` | `collection.request_id` 칸, `collection_alert` 표, 통계 읽기 전용 역할 `lf_stats_reader` 추가 | DB 담당(김재민)이 검토 후 `center/migrations/` 로 옮기면 적용됨 |

- 원래 번호 005 는 main 의 `005_kiosk_c_seomyeon_1104.sql` 과 겹쳐서 006 으로 바꿨다
- 역할(ROLE) 만들기·권한 부여가 들어 있어 팀 DB 에 영향이 크다 → 자동 적용 대신 사람이 확인
