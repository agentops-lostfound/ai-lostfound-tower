# web — 모든 화면 (화면 지도, 11/5 정리)

한줄 설명: 화면은 전부 이 폴더에 **화면 하나 = 폴더 하나(`index.html`)** 로 둔다. 관제탑(8100)이 이 파일을 바로 읽어 보여 주므로,
파일을 고치고 브라우저에서 새로 고침만 하면 된다(빌드·Docker 다시 만들기 없음). Docker 화면 앞문(8080)도 같은 화면을 보여 준다.

## 1. 화면 목록
| 화면 | 주소(관제탑 `:8100` 또는 Docker `:8080`) | 폴더 | 화면 담당 | 부르는 API | 상태(11/5) |
| --- | --- | --- | --- | --- | --- |
| 키오스크 | `/kiosk?machine=KIOSK-A` | `kiosk/` | 김재민 | `GET /places`, `POST /items` | 습득 신고 됨. **분실 확인·본센터 회수 추가 예정** |
| 등록기계(습득 신고) | `/intake?machine=KIOSK-A` | `intake/` | 김재민 | `GET /places`, `POST /items` | 됨(#48). 키오스크와 하나로 합칠지 결정 필요 |
| 분실인 웹(분실 확인) | `/lost` | `lost/` | 김재민 | (서버 연결 전) | 화면 흐름 시안 |
| 관제 모니터링 | `/live` | `live/` | 화면 김재민 · 데이터 변재원 | `GET /live/state`, `/sim/*`, `/robot/stop·home·state` | 됨(가상 시연·SO-101 실제 형상) |
| 직원 화면 | `/staff` | `staff-desk/` | (보류) | `/returns/*`, `/robot/*` | 11/5 결정: **직원은 일단 제외** — 화면은 남겨 둠 |
| 분실인 8단계 시안 | 파일 직접 열기 | `lost-finder/` | LF-4 | 가짜 자료 | 참고용 |
| 옛 시안 | - | `archive/` | - | - | 참고용(관제탑이 열지 않음) |

- 등록기계 번호: `KIOSK-A` 해운대 · `KIOSK-B` 중앙 · `KIOSK-C` 서면(접수 번호 앞글자 S). 본센터 키오스크 번호는 TBD
- 화면은 관제탑과 같은 주소에서 열리므로 `fetch("/items")` 처럼 앞부분 없이 부른다

## 2. 화면이 따를 흐름 (11/5 칠판 정리)
```
[일반 역 키오스크]  습득 신고 + 분실 확인 → (물건 있으면) "본센터에서 받으세요" 안내
[본센터 키오스크]   습득 신고 + 분실 확인 + 회수(키오스크가 신분 확인 → 로봇팔 → 인계)
[분실인 웹·챗봇]    분실 확인 → (물건 있으면) 본센터 방문 안내
[관제 모니터링]     전체 진행(/live)
```
- "본센터 여부"는 등록기계 정보로 판단한다: 팀 DB `machine.kind` 가 `center` 면 본센터(`center/schema.sql`)
- 신분 확인은 본센터 키오스크가 직접(셀프, 11/5 결정 a). 직원 확인 단계는 일단 뺀다

## 3. 지켜야 할 약속
- 요청·응답 형식: `agents/contracts.py`, `docs/contracts/mcp_tools.md`, 등록기계 API 는 `intake/README.md`
- 찾기 요청(`POST /claims`)은 동의·신분 인증 결과·가린 이름·특징 설명·확인 질문이 필요하다(전화번호 원문을 받지 않는다)
- 물건 종류는 팀 6종: 지갑 · USB · 립밤 · 모형폰 · 핸드크림 · 보조배터리 (`agents/contracts.py` CATEGORIES)
- 개인정보(전화번호·주민번호·이메일)는 장소·설명 칸에 쓰면 관제탑이 거절한다
- 로봇 관련 화면 요소(정지·원점·관절 값)는 `docs/contracts/robot_api.md` 기준

## 4. 고친 화면이 관제탑에 올라가는 흐름 (재민 님이 혼자 끝까지)
```
2조봇에게 "web/kiosk/index.html 바꿔 줘" → "미리보기 주소 줘"(8101) → "PR 올려 줘" → GitHub 에서 Merge → "관제탑 반영해 줘"
```
- "관제탑 반영해 줘": 2조봇이 관제탑 PC 저장소를 최신 main 으로 받는다(`git pull --ff-only`). HTML 은 새로 고침하면 바로 보인다
- 관제탑을 개발 모드(`tools\start_tower.bat dev`)로 켜 두면 파이썬(`agents/*.py`)이 바뀌어도 스스로 다시 켜진다(가상 시연 기록은 그때마다 초기화). 발표 때는 기본 모드로
- 교육원 PC 가 꺼져 있으면 2조봇도 꺼진다. 다른 PC 공개(방화벽·포트 연결)와 `.env` 는 PC 앞에서 변재원이

## 5. Docker · DB (팀 공용 하나)
| 무엇 | 값 | 비고 |
| --- | --- | --- |
| Docker 설정 | `docker-compose.yml` 하나 | `tools\start_tower.bat` 이 `docker compose up -d` 를 대신 함 |
| 팀 DB 컨테이너 | `lostfound-db` (PostgreSQL 16 + pgvector) | 접속 `127.0.0.1:5434`, DB·사용자 `lostfound`, 비밀번호는 관제탑 PC `.env`(채팅·디스코드에 쓰지 않음) |
| 표(테이블) | `center/schema.sql` — machine · place · item · finder_contact · claim · reservation 등 | 설명 `docs/design/database.md` |
| 화면 앞문 | `lostfound-web` (nginx, 8080) | 8080 으로 열면 관제탑(8100)의 화면·API 를 그대로 보여 줌 |
| 사진 | 관제탑 PC `data/photos/<기계번호>/` | DB 에는 경로만, Git 에는 안 올림 |
| 모드 | `.env` `TOWER_SIM=1` = 가상 시연(메모리, 관제탑 끄면 사라짐) / `TOWER_SIM=` + `TOWER_DB=1` = 팀 DB 에 저장 | 바꾸면 관제탑 재시작 |
- 화면은 DB 에 직접 붙지 않는다. 항상 관제탑 API(`/places`, `/items`, `/claims`, `/live/state`, `/robot/state` …)를 부른다 — API 문서는 관제탑 켠 뒤 `http://127.0.0.1:8100/docs`

## 6. 화면 확인하는 법
1. 관제탑 켜기: `tools\start_tower.bat` (가상 시연은 `.env` `TOWER_SIM=1`)
2. 브라우저: `http://127.0.0.1:8100/kiosk?machine=KIOSK-A` · `/lost` · `/live`
3. 다른 PC 에서 볼 때: `docs/design/virtual_demo.md` 4-2-1
