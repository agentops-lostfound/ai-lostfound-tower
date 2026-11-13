# 결과보고서 본문·그림·표 모음

작성일: 2026-11-12 · 담당: 김건태 · Jira: [LF-18](https://agentops-lostfound.atlassian.net/browse/LF-18)

한글 결과보고서 양식의 **6개 대항목**에 맞춰 정리한 편집 자료다. 정연우의 11/12 최신 수행 내용을 공정별 본문과 검증 붙임에 반영했다. HWP 원본을 수정한 완성 문서가 아니라, 팀에서 본문·그림·표를 삽입하고 실물 증빙을 채울 수 있는 자료다.

## 바로 사용할 파일

| 자료 | 파일 | 사용 방법 |
|---|---|---|
| 결과보고서 본문·검증 붙임·참고자료 | [report-copy-ready.txt](report-copy-ready.txt) | 양식의 해당 항목에 복사 |
| 표 10개와 삽입 위치 | [tables-paste-ready.md](tables-paste-ready.md) | 표마다 코드 블록만 복사하여 탭 기준 변환 |
| 개별 탭 구분 표 | [tables/](tables/) | UTF-8 TSV, 표 제목을 제외한 셀 내용 |
| 그림 10장 | [figures/](figures/) | PNG 삽입, SVG 수정·재사용 |
| 통신·공정 그림 위치 및 캡션 | [figure-placement.txt](figure-placement.txt) | 파일 번호와 보고서 항목 대조 |
| 실제 사진·화면 확보 목록 | [capture-checklist.md](capture-checklist.md) | 아직 필요한 증빙 자료 확보 |
| 디스코드 전달용 문안 | [capture-request.txt](capture-request.txt) | 팀 공유용 문안. 자동 발송하지 않음 |
| 양식 분석·편집 판단 | [template-review-notes.txt](template-review-notes.txt) | 원래 양식과 변경 이유·자료 범위 확인 |
| 통합 시연 영상 체크리스트 | [demo_video_checklist.md](../../design/demo_video_checklist.md) | 6~8분 영상 준비·촬영·편집 |

본문 안의 간략 표를 탭 구분 표로 교체할 때는 `tables-paste-ready.md`의 최신 10개 표를 사용한다. `[기입]`이나 사진 삽입 표시는 확인할 자료를 남긴 것이며 완료 표시가 아니다.

## 한글 삽입 방법

- 그림: PNG 삽입 → 글자처럼 취급 → 가운데 정렬 → 가로세로 비율 유지. 통신·공정 그림은 너비 14~15cm, 긴 제4공정은 14cm부터 적용한다.
- 표: TSV 또는 코드 블록 내용 붙여넣기 → 해당 내용 선택 → **입력 → 표 → 문자열을 표로 → 분리 방법 지정: 탭 → 설정**.
- 표 제목·삽입 위치·주석은 셀 변환 범위에 포함하지 않는다.
- 공식 기능 안내: [한컴 문자열을 표로](https://help.hancom.com/hoffice130/ko-KR/Hwp/table/table%28to_table%29.htm).

## 그림 삽입 위치

| 파일 | 보고서 위치 | 캡션 |
|---|---|---|
| [01_system_architecture.png](figures/01_system_architecture.png) | 3. 가. 시스템 구조도 | 사용자 접수부터 로봇 반환까지의 시스템 구성 |
| [02_chatbot_agents.png](figures/02_chatbot_agents.png) | 4. 라. 3) 챗봇 프로그램 | 챗봇 에이전트 구성과 작업 흐름 |
| [03_control_tower_agents.png](figures/03_control_tower_agents.png) | 4. 마. 3) 관제 프로그램 | 메인 AI 검토와 코드 실행 조건 검사 구조 |
| [04_service_robot_background.png](figures/04_service_robot_background.png) | 1. 나. 2) 서비스 로봇 적용 확대 | IFR 2026의 전문 서비스 로봇 공급업체 표본 조사 |
| [05_process_overview.png](figures/05_process_overview.png) | 4. 가. 1) 공정 순서 | 접수·보관·찾기·반환·인계의 전체 흐름 |
| [06_communication.png](figures/06_communication.png) | 3. 나. 통신 구성 — 통신 표 앞 | 관제탑–로봇 PC 실행 요청·상태 반환·연결 유지 |
| [07_process_1_2.png](figures/07_process_1_2.png) | 4. 다. 제1·2공정 → 1) 순서도 | 습득 접수·입고·보관과 탑뷰·DB 대조 |
| [08_process_3.png](figures/08_process_3.png) | 4. 라. 제3공정 → 1) 순서도 | 정보 보완·초안 확인·실행 검사·찾기 신청 |
| [09_process_4.png](figures/09_process_4.png) | 4. 마. 제4공정 → 1) 순서도 | 본센터 확인·로봇 반환과 정지·복귀 처리 |
| [10_process_5.png](figures/10_process_5.png) | 4. 바. 제5공정 → 1) 순서도 | 제출보관함 도착·수령 확인·인계 완료 |

각 PNG와 같은 이름의 SVG를 함께 제공한다. 파일의 01~10은 자산 식별 번호이며 최종 보고서 그림 번호는 편집 순서에 맞춰 지정한다.

## 본문 및 성과 해석

- 보고서 구성: 1. 개요 / 2. 팀원·임무 / 3. 구조·사양 / 4. 공정별 결과 / 5. 미비점 / 6. 총평 / 붙임.
- PLC·CC-Link·래더도 예시는 실제 사용한 API·상태 계약·프로그램 흐름으로 바꿨다.
- 기존 그림 3번은 키오스크의 습득 접수·회수 요청·수령 확인과 Mi:dm의 다음 에이전트 선택·결정 설명을 반영했다.
- 초기 영상 목록에서 제외했던 음성 검색 장면과 최신 전달문의 음성 입력 오류 처리 시험은 다른 범위다. 실녹음 인식 정확도를 검증했다고 쓰지 않는다.
- 1,305개 고정 사례에는 신규 305여정·1,656턴이 포함된다. 20여정 6/20→20/20은 고정 시험 집합 결과다.
- 원본 점수 3,500개 대조는 기록 일치 확인이며 신규 시험 3,500개 통과가 아니다.
- 본문에 인용한 과거 시험·실물 확인과 이번 문서 게시 전 회귀 시험을 구분한다. 게시 전 시험 결과는 PR에 기록한다.
- Field Vision은 별도 개발·검증 범위다. USB 들어 올림 전달 결과를 전체 집기·놓기·HOME 또는 관제 통합 성공으로 확대하지 않는다.
- 기본 티칭·탑뷰 구현은 PR #221/#245 등의 별도 변경에서 인용한 것이다. 이 문서 PR이 로봇 코드를 배포하거나 해당 기능의 main 병합을 수행하지 않는다.
- 기존 칸 해제는 제출보관함 도착·인계 대기 단계, 인계 완료는 사용자 수령 확인 이후로 구분했다.

## 남은 작업

- [ ] 실제 PC·GPU·카메라 모델 및 장비 대수 기입
- [ ] 공정별 실제 사진·화면 캡처 추가
- [ ] 11/13 최종 수행 결과·리허설 결과 반영
- [ ] 최신 후속 코드의 운영 적용과 전체 실물 인계 확인
- [ ] 최종 HWP 편집·페이지 배치 확인

정확한 출처 URL과 과거 검증 범위는 `report-copy-ready.txt`의 붙임 1~3을 따른다. 원본 HWP, 개인정보가 있는 캡처, 실제 물건 사진 원본, 모델 가중치 및 로컬 백업은 이 자료 묶음에 포함하지 않는다.
