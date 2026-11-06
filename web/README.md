# web — 모든 화면 (화면 지도, 11/5 정리)

> 11/6: 화면과 관제탑(API·DB·로봇 연결) 모두 **변재원**(11/5 김재민 → 11/6 작업 완료 후 이어받음). 관제탑 코드 안내는 `docs/design/tower_handover.md`

한줄 설명: 화면은 전부 이 폴더에 **화면 하나 = 폴더 하나(`index.html`)** 로 둔다. 관제탑(8100)이 이 파일을 바로 읽어 보여 주므로,
파일을 고치고 브라우저에서 새로 고침만 하면 된다(빌드·Docker 다시 만들기 없음). Docker 화면 앞문(8080)도 같은 화면을 보여 준다.

## 1. 화면 목록
| 화면 | 주소(관제탑 `:8100` 또는 Docker `:8080`) | 폴더 | 화면 담당 | 부르는 API | 상태(11/5) |
| --- | --- | --- | --- | --- | --- |
| 키오스크 | `/kiosk?machine=KIOSK-A` | `kiosk/` | 변재원(이전 김재민) | `GET /api/kiosk/places`, `POST /api/kiosk/items` | 모든 역: 습득 신고 + 분실 확인, 본센터만 셀프 신분 확인·회수(11/5 정책, `docs/design/operating_flow_1105.md`). 탭 2개(습득 신고 / 분실접수). 습득은 서버 연결됨, **분실접수 탭은 입력 화면만**(후보 찾기 API 가 생기면 `/api/lost/…` 연결, 3차). 회수 탭은 `?machine=CENTER`(본센터)일 때만 보임 — `POST /api/kiosk/returns`(11/6, 관문 값은 서버가 정함) |
| 등록기계(습득 신고) | `/intake?machine=KIOSK-A` | `intake/` | 변재원(이전 김재민) | `GET /api/kiosk/places`, `POST /api/kiosk/items` | 키오스크 습득 탭과 같은 일 → **키오스크로 합치는 중**(이 화면은 호환용으로 남김, 3차에서 `/kiosk` 로 넘김) |
| 분실인 웹(분실 확인) | `/lost` | `lost/` | 변재원(이전 김재민) | (서버 연결 전) | 화면 흐름 시안. 분실 확인 후 본센터 방문 안내 정책 적용 예정 |
| 관제 모니터링 | `/live` | `live/` | 변재원(이전 김재민) | `GET /api/admin/live/state`, `/sim/*`, `POST /api/robot/stop`, `/api/admin/robot/home` | 됨(가상 시연·SO-101 실제 형상) |
| 관리자 관제(로그인) | `/admin` | `admin/` | 변재원(이전 김재민) | `/api/admin/login·logout·me` | 로그인 후 관제 모니터링(`/live`)·반환/직원(`/staff`)을 탭으로. `.env` `LF_ADMIN_PASSWORD` 가 없으면 로그인 없이 열림 |
| AI 챗봇 위젯 | 화면에 `<script src="/chat-widget/widget.js">` · 시험 `/chat-widget/demo` | `chat-widget/` | 변재원 | `POST /chat/questions`, `/chat/suggestions`, `/chat/health` | 됨(가상 물건 DB). **11/6 키오스크(머리말 "AI 안내" 버튼, 키오스크 모드: 닫거나 90초 무입력이면 대화 지움)와 분실인 웹("AI챗봇 사용하기" 버튼)에 붙임** — `chat-widget/README.md` |
| 회수·통계 시연(LF-9) | 독립 실행 `python -m tools.run_collection_demo` → `:8110/collection-desk` | `collection-desk/` | 정연우 작업 완료(11/5 변재원 이어받음) | 시연 전용 `/collections*` (가상 SQLite) | 관제탑·팀 DB 와 미연결. 관리자 화면으로 쓸지 변재원 결정 — `docs/reports/2026-11-05-jaewon-takeover-yeonwoo.md` |
| 직원 화면 | `/staff` | `staff-desk/` | (보류) | `/returns/*`, `/robot/*` | 11/5 결정: **직원은 일단 제외** — 화면은 남겨 둠 |
| 분실인 8단계 시안 | 파일 직접 열기 | `lost-finder/` | LF-4 | 가짜 자료 | 참고용 |
| 옛 시안 | - | `archive/` | - | - | 참고용(관제탑이 열지 않음) |

- 등록기계 번호: `KIOSK-A` 해운대(앞글자 A) · `KIOSK-C` 서면(앞글자 S) · `CENTER` **부산역 본센터** 키오스크(앞글자 H). 11/6 중앙역(KIOSK-B)은 삭제
- 화면은 관제탑과 같은 주소에서 열리므로 `fetch("/items")` 처럼 앞부분 없이 부른다

## 2. 화면이 따를 흐름 (11/5 칠판 정리)
상세 이벤트·API 권한·본센터 판별·6종 분류 정책은 [docs/design/operating_flow_1105.md](../docs/design/operating_flow_1105.md)를 기준으로 한다.
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
- 물건 종류는 팀 6종: 지갑 · USB · 립밤 · 모형폰 · 핸드크림 · 보조배터리 (`agents/contracts.py` CATEGORIES 및 MVP_CATEGORIES)
- 개인정보(전화번호·주민번호·이메일)는 장소·설명 칸에 쓰면 관제탑이 거절한다
- 로봇 관련 화면 요소(정지·원점·관절 값)는 `docs/contracts/robot_api.md` 기준

## 4. 고친 화면이 관제탑에 올라가는 흐름 (재민 님이 혼자 끝까지)
```
2조봇에게 "web/kiosk/index.html 바꿔 줘" → "미리보기 주소 줘"(8101) → "PR 올려 줘" → GitHub 에서 Merge → "관제탑 반영해 줘"
```
- "관제탑 반영해 줘": 2조봇이 관제탑 PC 저장소를 최신 main 으로 받는다(`git pull --ff-only`). HTML 은 새로 고침하면 바로 보인다
- 관제탑을 개발 모드(`tools\start_tower.bat dev`)로 켜 두면 파이썬(`agents/*.py`)이 바뀌어도 스스로 다시 켜진다(가상 시연 기록은 그때마다 초기화). 발표 때는 기본 모드로
- 교육원 PC 가 꺼져 있으면 2조봇도 꺼진다. 다른 PC 공개(방화벽·포트 연결)와 `.env` 는 교육원 PC 앞에서 직접(2조봇은 `.env` 를 읽거나 고치지 않음)

## 5. Docker · DB (팀 공용 하나)
| 무엇 | 값 | 비고 |
| --- | --- | --- |
| Docker 설정 | `docker-compose.yml` 하나 | `tools\start_tower.bat` 이 `docker compose up -d` 를 대신 함 |
| 팀 DB 컨테이너 | `lostfound-db` (PostgreSQL 16 + pgvector) | 접속 `127.0.0.1:5434`(다른 PC 는 5-1, `DB_BIND`), DB·사용자 `lostfound`, 비밀번호는 관제탑 PC `.env`(채팅·디스코드에 쓰지 않음) |
| 표(테이블) | `center/schema.sql` — machine · place · item · finder_contact · claim · reservation 등 | 설명 `docs/design/database.md` |
| 화면 앞문 | `lostfound-web` (nginx, 8080) | 8080 으로 열면 관제탑(8100)의 화면·API 를 그대로 보여 줌 |
| 사진 | 관제탑 PC `data/photos/<기계번호>/` | DB 에는 경로만, Git 에는 안 올림 |
| 모드 | `.env` `TOWER_SIM=1` = 가상 시연(메모리, 관제탑 끄면 사라짐) / `TOWER_SIM=` + `TOWER_DB=1` = 팀 DB 에 저장 | 바꾸면 관제탑 재시작 |
- 화면은 DB 에 직접 붙지 않는다. 항상 관제탑 API(`/places`, `/items`, `/claims`, `/live/state`, `/robot/state` …)를 부른다 — API 문서는 관제탑 켠 뒤 `http://127.0.0.1:8100/docs`

### 5-1. 다른 PC(교육원 사람·재민 님 PC)에서 화면·팀 DB 접속하기 (11/5, 실제로 된 방법)
한줄 설명: 관제탑 PC 앞에서 `.env` 한 줄 + 방화벽 두 종류(Windows·Hyper-V)를 연다. 11/5 기준 **화면(8080)·팀 DB(5434) 모두 교육원 대역(10.10.21.0/24)** 에 열어 두었다(챗봇 작업·DBeaver 확인용).

| 무엇 | 다른 PC 에서 쓸 주소 | 누구에게 열림(11/5) |
| --- | --- | --- |
| 화면 앞문 | `http://10.10.21.21:8080/` (→ `/kiosk`, 그 밖에 `/lost` · `/live` · `/chat-widget/demo`) | 교육원 대역 10.10.21.0/24 |
| 팀 DB | 호스트 `10.10.21.21`, 포트 `5434`, DB·사용자 `lostfound`, 비밀번호는 직접 전달(디스코드·채팅에 쓰지 않음) | 교육원 대역 10.10.21.0/24 |
- `127.0.0.1` 은 "지금 이 컴퓨터"라서 다른 PC 에서는 관제탑이 아니다 → 다른 PC 는 꼭 `10.10.21.21`
- 로그인이 없다 → 8080 으로 들어오면 직원 화면(`/staff`)·로봇 정지·원점 API 도 누구나 누를 수 있다. 가상 시연(`TOWER_SIM=1`)일 때만 넓게 열고, 실제 로봇을 붙이면 좁힌다

1. 메모장으로 `.env` 를 열어 `DB_BIND=0.0.0.0` 한 줄 → 작업 탭 `docker compose up -d` → `docker ps --format "{{.Names}}  {{.Ports}}"` 에 `0.0.0.0:5434->5432/tcp` (DB 를 열 때만 필요, 화면 8080 은 원래 0.0.0.0)
2. **관리자** PowerShell(Warp 작업 탭은 권한이 없어 "액세스가 거부되었습니다"), 한 줄씩
   ```powershell
   New-NetFirewallRule -DisplayName "LostFound web 8080 (classroom 10.10.21.0/24)" -Direction Inbound -Protocol TCP -LocalPort 8080 -RemoteAddress 10.10.21.0/24 -Action Allow
   New-NetFirewallHyperVRule -Name "LostFound-web-classroom" -DisplayName "LostFound web 8080 (classroom)" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 8080 -RemoteAddresses 10.10.21.0/24 -Action Allow
   New-NetFirewallRule -DisplayName "LostFound DB 5434 (classroom 10.10.21.0/24)" -Direction Inbound -Protocol TCP -LocalPort 5434 -RemoteAddress 10.10.21.0/24 -Action Allow
   New-NetFirewallHyperVRule -Name "LostFound-db-classroom" -DisplayName "LostFound DB 5434 (classroom)" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 5434 -RemoteAddresses 10.10.21.0/24 -Action Allow
   ```
   - Hyper-V 규칙이 핵심: 교육원 PC 는 WSL 이 **미러 네트워크 모드**(`%USERPROFILE%\.wslconfig` `networkingMode=mirrored`)라 Docker Desktop 포트가 WSL 쪽 문(Hyper-V 방화벽, 기본 Block)에서 한 번 더 막힌다. Windows 방화벽만 열면 다른 PC 에서 `False`
   - 확인: `Get-NetFirewallRule -DisplayName "LostFound*" | Select-Object DisplayName, Enabled` · `Get-NetFirewallHyperVRule | Where-Object Name -like "LostFound*" | Select-Object Name, LocalPorts, RemoteAddresses` (`-Name` 에는 `*` 가 안 먹는다. 두 명령을 `;` 로 이어 치면 두 번째 표가 안 보일 수 있으니 따로)
3. 확인은 **다른 PC 에서**: `Test-NetConnection 10.10.21.21 -Port 8080` → `TcpTestSucceeded : True`, 브라우저 `http://10.10.21.21:8080/`
   - 관제탑 PC 에서 자기 주소(10.10.21.21)로 시험하면 미러 모드에서는 `False` 가 나온다 — 관제탑 PC 는 `http://127.0.0.1:8080/` 으로 확인
4. 사람을 더하거나 넓히기: `-RemoteAddress`/`-RemoteAddresses` 에 쉼표로 주소 추가, 다른 강의실(예: 10.10.22.x)까지면 그 대역도
- 화면 앞문은 `/` 를 `/kiosk` 로 넘길 때 포트를 유지한다(`docker/web.conf.template` `absolute_redirect off`, 11/5 #79). 설정을 바꾸면 `docker compose up -d --force-recreate web`
- 관제탑 API(8100)를 직접 열 때: `tools\start_tower.bat lan` + Windows 방화벽 8100(`docs/design/virtual_demo.md` 4-2-1). 8080 이 8100 의 화면·API 를 그대로 넘기므로 보통은 필요 없다
- DBeaver: PostgreSQL → Host `10.10.21.21`(관제탑 PC 자신은 `127.0.0.1`), Port `5434`, Database·Username `lostfound` → Test Connection. 표는 `public` 스키마(`item`·`claim`·`machine`·`place` …), 설명 `docs/design/database.md`
- DB 가 교육원 전체에 열려 있으니 비밀번호를 기본값에서 바꾸는 것을 권장: `docker exec -it lostfound-db psql -U lostfound -d lostfound` → `\password lostfound` → `.env` 의 `POSTGRES_PASSWORD`·`DATABASE_URL` 도 같은 값으로(`.env` 값만 바꾸면 이미 만든 DB 비밀번호는 안 바뀜). 저장소 기본값은 `lostfound-dev`
- 닫기: `.env` `DB_BIND=` 비우고 `docker compose up -d` · 관리자 PowerShell `Get-NetFirewallHyperVRule | Where-Object Name -like "LostFound*" | Remove-NetFirewallHyperVRule; Get-NetFirewallRule -DisplayName "LostFound*" | Remove-NetFirewallRule`

## 6. 화면 확인하는 법
1. 관제탑 켜기: `tools\start_tower.bat` (가상 시연은 `.env` `TOWER_SIM=1`)
2. 브라우저: `http://127.0.0.1:8100/kiosk?machine=KIOSK-A` · `/lost` · `/live`
3. 다른 PC 에서 볼 때: `docs/design/virtual_demo.md` 4-2-1
