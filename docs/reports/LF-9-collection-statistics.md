# LF-9 회수 기록·통계 질문 구현

## 기능

- `등록기계 보관 → 회수 중 → 본센터 보관`을 기존 item/collection/collection_item/item_status_log에 거래 하나로 기록한다.
- 회수 요청의 request_id를 유지하면 동시 재시도에도 회수·상태 기록이 중복되지 않는다. 다른 내용에 같은 ID를 재사용하면 거절한다.
- 도착한 물건만 체크하며 미도착 물건은 회수 중으로 남는다. 빈 도착 목록도 받아 전부 미도착으로 기록할 수 있다.
- 부분 도착 시 미도착 알림을 DB 큐에 넣는다. 전량 도착해야 collection.arrived_at을 채운다. 나중에 도착한 물건의 미전송 알림은 해제한다.
- 회수 후 아무 도착 입력도 없는 건은 명시한 기준시각으로 overdue 검사를 실행한다. 운영 마감시각/스케줄은 미확정이므로 임의의 시간으로 자동 실행하지 않는다.
- 통계는 한국어 질문을 제한된 SQL 템플릿으로 변환한다. `오늘/어제/YYYY-MM-DD + 등록기계(선택) + 품목/전체 + 접수 건수`만 지원한다. 자유 SQL 생성형 LLM이 아니다.
- 한국 시간 하루의 경계를 계산하고 SQL 값은 매개변수로 전달한다. 개인정보/특징 조건·기간 집계 등 미지원 질문은 거절한다.
- 전용 읽기 연결 + READ ONLY 거래 + lf_stats_reader 역할 + stats_item 뷰만 사용한다. DB 관리자는 기본 테이블 권한 없는 전용 로그인에 이 역할만 부여해야 한다. 소유자 계정을 통계 연결로 쓰지 않는다.
- 호선·역·장소 목록 upsert와 5개씩 넘기기를 제공한다. 기존 접수 검증과 호환되도록 추천은 같은 역으로 제한했다. 같은 호선 다른 역으로 확대하려면 LF-2 접수 검증과 함께 합의가 필요하다.

## 실행

기존 관제탑 API와 별도이며 충돌하는 라우트를 수정하지 않았다.

```powershell
python -m tools.db_migrate --apply
python -m uvicorn agents.center_api:app --host 127.0.0.1 --port 8110
```

필요한 실행 환경 변수: DATABASE_URL(회수/장소), LF_STATS_DATABASE_URL(읽기 전용 로그인), LF_STAFF_API_KEY(직원 접근 키). 값을 소스·문서에 적지 않는다. 모든 요청은 x-staff-key 헤더가 필요하며 키 미설정 시 503, 불일치 시 403이다. 통계 로그인 역할 부여는 DB 관리자 작업이다. 기존 팀 DB에는 이 문서 작성 중 접속하거나 마이그레이션하지 않았다.

| 요청 | 내용 |
|---|---|
| POST /collections | machine_id, item_ids, request_id |
| GET /collections/{id} | 회수 및 도착 체크 목록 |
| POST /collections/{id}/arrivals | 실제 도착 item_ids만 전달 |
| POST /collections/overdue/check | 시간대 포함 before 기준시각 |
| POST /statistics/questions | question: 오늘 등록기계 A에 들어온 USB 몇 개? |
| GET /places | machine_id, offset |
| POST /places | line, station, label |

미도착 알림은 `python -m tools.collection_alerts --before "2026-11-04T18:00:00+09:00"`처럼 명시적으로 실행한다. 예시시각은 운영 규칙이 아니다. 기본은 미리보기이고 `--send`를 지정해야 디스코드 전송한다. 실제 전송은 이번 구현 검증에서 수행하지 않았다. 전송 실패는 큐에 남고 재시도할 수 있다. 전송 후 DB 커밋 직전 중단되면 알림 중복은 가능(at least once)하나 회수/도착 상태 기록은 중복되지 않는다.

## 검증

단위 시험 `tests/test_center_operations.py`, API 인증 시험 `tests/test_center_api.py`.
실제 PostgreSQL 시험 `tests/test_center_postgres.py`는 LF_SUPPORT_TEST_DSN이 지정되고 DB 이름이 lf_support_test인 일회용 DB에서만 실행한다. 일반 테스트에서는 건너뛴다. 동시 재시도, 부분 도착·완료, 전체 롤백, 알림 미리보기, 통계 뷰 조회와 개인정보 표/쓰기 거절, 장소 중복·페이지 넘김을 확인한다.

이번 변경은 center(회수·통계·장소/마이그레이션), agents/center_api.py(직원 API), tools/collection_alerts.py(알림 실행), tests, 이 문서다. 공통 contracts.py와 로봇 반환 코드는 변경하지 않았다. 운영 접근키와 직원 권한은 실제 배포 인증 체계로 교체해야 한다.
