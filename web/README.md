# web — 모든 화면 (화면 지도, 11/5 정리)

> 11/5 역할 조정: 화면과 관제탑(API·DB·로봇 연결) 모두 **김재민**. 관제탑 코드 안내는 `docs/design/tower_handover.md`

한줄 설명: 화면은 전부 이 폴더에 **화면 하나 = 폴더 하나(`index.html`)** 로 둔다. 관제탑(8100)이 이 파일을 바로 읽어 보여 주므로,
파일을 고치고 브라우저에서 새로 고침만 하면 된다(빌드·Docker 다시 만들기 없음). Docker 화면 앞문(8080)도 같은 화면을 보여 준다.

## 1. 화면 목록
| 화면 | 주소(관제탑 `:8100` 또는 Docker `:8080`) | 폴더 | 화면 담당 | 부르는 API | 상태(11/5) |
| --- | --- | --- | --- | --- | --- |
| 키오스크 | `/kiosk?machine=KIOSK-A` | `kiosk/` | 김재민 | `GET /places`, `POST /items` | 습득 신고 됨. **분실 확인·본센터 회수 추가 예정**(필요한 API 설계 메모: `docs/design/tower_handover.md` 4절) |
| 등록기계(습득 신고) | `/intake?machine=KIOSK-A` | `intake/` | 김재민 | `GET /places`, `POST /items` | 됨(#48). 키오스크와 하나로 합칠지 결정 필요 |
| 분실인 웹(분실 확인) | `/lost` | `lost/` | 김재민 | (서버 연결 전) | 화면 흐름 시안 |
| 관제 모니터링 | `/live` | `live/` | 김재민 | `GET /live/state`, `/sim/*`, `/robot/stop·home·state` | 됨(가상 시연·SO-101 실제 형상) |
| AI 챗봇 위젯 | 화면에 `<script src="/chat-widget/widget.js">` · 시험 `/chat-widget/demo` | `chat-widget/` | 변재원(붙이기 김재민) | `POST /chat/questions`, `/chat/suggestions`, `/chat/health` | 됨(가상 물건 DB). 분실인 웹 완성 뒤 붙임 — `chat-widget/README.md` |
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

### 5-1. 다른 PC(재민 님 PC 등)에서 팀 DB·화면 접속하기 (11/5, 실제로 된 방법)
한줄 설명: 기본은 관제탑 PC 안에서만 열린다. 팀원 PC 에서 붙으려면 **관제탑 PC 앞에서** `.env` 한 줄 + 방화벽 두 종류(Windows·Hyper-V)를 연다. 11/5 재민 님 PC(10.10.21.15)에서 `10.10.21.21:5434`·`:8080` 접속 성공.

| 무엇 | 다른 PC 에서 쓸 주소 |
| --- | --- |
| 팀 DB | 호스트 `10.10.21.21`(관제탑 PC), 포트 `5434`, DB·사용자 `lostfound`, 비밀번호는 직접 전달(디스코드·채팅에 쓰지 않음) |
| 화면 앞문 | `http://10.10.21.21:8080/` |

1. 메모장으로 `.env` 를 열어 `DB_BIND=0.0.0.0` 한 줄 → 작업 탭 `docker compose up -d` → `docker ps --format "{{.Names}}  {{.Ports}}"` 에 `0.0.0.0:5434->5432/tcp`
2. **관리자** PowerShell(Warp 작업 탭은 권한이 없어 "액세스가 거부되었습니다") — 접속할 PC 주소만 허용(예: 재민 님 10.10.21.15)
   ```powershell
   New-NetFirewallRule -DisplayName "LostFound DB 5434 (jaemin)" -Direction Inbound -Protocol TCP -LocalPort 5434 -RemoteAddress 10.10.21.15 -Action Allow
   New-NetFirewallRule -DisplayName "LostFound web 8080 (jaemin)" -Direction Inbound -Protocol TCP -LocalPort 8080 -RemoteAddress 10.10.21.15 -Action Allow
   New-NetFirewallHyperVRule -Name "LostFound-jaemin" -DisplayName "LostFound 5434·8080 (jaemin)" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 5434,8080 -RemoteAddresses 10.10.21.15 -Action Allow
   ```
   - 세 번째(Hyper-V)가 핵심: 교육원 PC 는 WSL 이 **미러 네트워크 모드**(`%USERPROFILE%\.wslconfig` `networkingMode=mirrored`)라 Docker Desktop 포트가 WSL 쪽 문(Hyper-V 방화벽, 기본 Block)에서 한 번 더 막힌다. Windows 방화벽만 열면 다른 PC 에서 `False`
   - 확인 명령: `Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'` → `DefaultInboundAction : Block` 이면 위 규칙 필요(기본값 자체는 바꾸지 않는다)
3. 확인은 **접속할 PC 에서**: `Test-NetConnection 10.10.21.21 -Port 5434; Test-NetConnection 10.10.21.21 -Port 8080` → 둘 다 `TcpTestSucceeded : True`
   - 관제탑 PC 에서 자기 주소(10.10.21.21)로 시험하면 미러 모드에서는 성공해도 `False` 가 나온다 — 판단에 쓰지 않는다
4. 사람이 늘면 `-RemoteAddress`/`-RemoteAddresses` 에 쉼표로 주소를 더하거나 교육원 대역 `10.10.21.0/24` 로
- 관제탑 API(8100)를 다른 PC 에 열 때도 같은 원리: `tools\start_tower.bat lan` + Windows 방화벽 8100(`docs/design/virtual_demo.md` 4-2-1). 관제탑은 Docker 가 아니라 Windows 에서 직접 돌므로 Hyper-V 규칙은 필요 없다(추정)
- 예전 우회(portproxy 18080·18100)는 필요 없다. 지우기(관리자): `netsh interface portproxy delete v4tov4 listenaddress=10.10.21.21 listenport=18080` · `... listenport=18100`
- DB 비밀번호가 저장소 기본값(`lostfound-dev`)이면 시간 날 때 바꾼다: `docker exec -it lostfound-db psql -U lostfound -d lostfound` → `\password lostfound` → `.env` 의 `POSTGRES_PASSWORD`·`DATABASE_URL` 도 같은 값으로(`.env` 값만 바꾸면 이미 만든 DB 비밀번호는 안 바뀜)
- 닫기: `.env` `DB_BIND=` 비우고 `docker compose up -d` · 관리자 PowerShell `Remove-NetFirewallHyperVRule -Name "LostFound-jaemin"; Get-NetFirewallRule -DisplayName "LostFound*" | Remove-NetFirewallRule`

## 6. 화면 확인하는 법
1. 관제탑 켜기: `tools\start_tower.bat` (가상 시연은 `.env` `TOWER_SIM=1`)
2. 브라우저: `http://127.0.0.1:8100/kiosk?machine=KIOSK-A` · `/lost` · `/live`
3. 다른 PC 에서 볼 때: `docs/design/virtual_demo.md` 4-2-1
