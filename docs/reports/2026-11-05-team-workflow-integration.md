# 정연우 · 팀 최신 구조와 회수·검색·통계 통합 검증

## 기준과 변경

main `fe9e935804cecc449d1f52f32c4c8436ab766280`까지 작업 브랜치에 반영했다. [PR #67](https://github.com/agentops-lostfound/ai-lostfound-tower/pull/67)의 비전 안전·매칭·로봇 도구와 [PR #68](https://github.com/agentops-lostfound/ai-lostfound-tower/pull/68)의 화면·Docker 통합을 포함한다. main에 우리 작업을 병합한 것은 아니다.

- 화면은 `web/<화면>/index.html`, Docker는 `docker-compose.yml` 하나다. 제거된 frontend/backend·standalone 샘플을 안내하던 검색 연동 문서를 고쳤다.
- 수령 안내 RAG는 최신 `web/README.md`에 맞춰 본센터 방문·키오스크 셀프 신분 확인 방향을 안내한다. 직원 최종 확인·예약을 현행 절차로 단정하던 설명을 교체하고 허용 문서·검증 해시·출처를 함께 갱신했다. 설계 방향이며 인증 연결 완료를 뜻하지 않는다는 문구를 유지한다. 준비물·시간·장소도 미확정이다.
- 키오스크에서의 수령과 등록기계→본센터 물류 회수는 다른 단계다. LF-9 회수 기록을 키오스크 반환 기능으로 바꾸거나 실제 API 권한을 풀지 않았다.
- 팀 CI와 같은 `opencv-python-headless`를 로컬에 설치했다. YOLO/Qwen 모델 다운로드나 실물 장비 실행은 하지 않았다.
- Windows에서 새 모의 로봇 HTTP 시험의 인증 거절 응답 중 연결 중단이 반복됐다. 시험 클라이언트가 작은 헤더·본문을 함께 보내도록 보완했다. 403·확인값 검사·명령 미전송 검사는 유지했으며 로봇 제어 코드는 변경하지 않았다.

## 동일 PostgreSQL의 저장 모듈을 이어 검증

신규 통합 시험 2개는 `tests/test_center_postgres.py`에 있다. 이름을 `lf_support_test`로 제한한 임시 DB에 팀 스키마·마이그레이션을 적용하고 `PostgresIntakeStore`, `CollectionStore`, `PostgresItemSearch`/`SearchAgent`, `Statistics`를 함께 사용한다. 인증 검증기는 시험용으로 주입한다.

| 단계 | 검정 지갑 검색 후보 | 해당 날짜 A 지갑 접수 통계 |
|---|---:|---:|
| 2개 접수·특징 저장 | 2 | 2 |
| 2개 회수 중 | 0 | 2 |
| 1개 도착 | 1 | 2 |
| 모두 도착 | 2 | 2 |

중복 회수 요청은 같은 회수 번호를 반환한다. 도착 저장을 반복해도 이력이 중복되지 않는다. 최종 이력은 접수 2·회수 2·도착 2의 6건이며 미해결 알림은 0건이다.

다른 기계 회수·없는 물건을 섞은 회수는 거래 전체를 거절하고 후보와 통계를 유지한다. 미인증·위조 토큰은 검색 SQL을 호출하지 않으며 공개 응답에는 접수 번호·합성 비공개 특징이 나오지 않는다.

이 시험은 PostgreSQL 모듈 통합 시험이다. 브라우저부터 실제 인증 서버·실물 로봇까지의 운영 시험 및 LF-20 특징 순위 매칭 연결은 이번 범위에 포함하지 않았다.

## 결과와 대기

- LF-5 전체 Python: 677개 실행, 실패 0, 환경 조건 11개 생략.
- LF-9 별도 PostgreSQL 포함 전체 Python: 728개 실행, 실패 0, 환경 조건 1개 생략. 기존 DB 시험 10개와 신규 통합 2개를 포함한다.
- Node 화면 동작 시험: 25개 모두 통과.
- 직접 만든 임시 검증 컨테이너만 정리했다. 실제 팀 DB·실물 로봇·기존 로컬 시연 기록은 변경하지 않았다.

실제 인증·동의 계약, 본센터 키오스크 신분 확인, 실제 예약·반환 승인 연결은 대기다. [LF-5 PR #61](https://github.com/agentops-lostfound/ai-lostfound-tower/pull/61)·[LF-9 PR #64](https://github.com/agentops-lostfound/ai-lostfound-tower/pull/64)는 초안으로 유지한다.
