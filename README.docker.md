# Docker 화면 (React) — 관제탑 API·팀 DB 에 연결 (11/5 변경)

재민 님이 만든 React 화면(습득물 등록 · 분실물 반환 신청)을 Docker 로 띄운다.
11/5부터 화면 전용 서버·DB 는 쓰지 않고, 접수는 **관제탑 API(8100) → 팀 DB** 로 들어간다.
그래서 이 화면으로 접수한 물건이 `/live`, 직원 화면, 매칭에 바로 나타난다.

```
[브라우저] → app-web(nginx, 8080) ─/api/·/lost─→ 관제탑 API(이 PC 8100) → 팀 DB(lostfound, 5434)
```

## 켜기
1. 관제탑을 먼저 켠다: `tools\start_tower.bat`
2. 저장소 폴더에서 아래를 실행한다(`.env` 는 만들거나 복사하지 않는다 — 팀 `.env` 를 덮어쓰지 않게)
   ```
   docker compose -f docker-compose.app.yml up --build -d
   ```
3. 접속: `http://localhost:8080`
   - 등록기계 화면: `http://localhost:8080/?machine=KIOSK-A` (KIOSK-B 중앙 · KIOSK-C 서면)
   - 반환 신청 탭 → 관제탑 분실인 화면(`/lost`)으로 넘어간다
4. 끄기: `docker compose -f docker-compose.app.yml stop` (컨테이너·볼륨은 남음)

## 연결 방식
- `frontend/default.conf.template`: nginx 가 `/api/places`·`/api/items` 를 관제탑 `/places`·`/items` 로, `/lost` 를 관제탑 `/lost` 로 전달
- 관제탑 주소는 환경값 `TOWER_URL` (기본 `http://host.docker.internal:8100` = 컨테이너 안에서 본 이 PC)
- 컨테이너에서 관제탑에 닿지 않으면(접수 때 "관제탑 연결을 확인해 주세요") 관제탑을 `tools\start_tower.bat lan` 으로 켠다(추정: Docker 설정에 따라 다름)
- 요청·응답 형식은 팀 약속(`agents/contracts.py`, `docs/contracts/mcp_tools.md`)을 따른다. 접수 번호는 관제탑이 `A-날짜-순번` 으로 매긴다
- 습득자 연락처는 관제탑이 `finder_contact` 표에만 저장하고 30일 뒤 지운다(`tools/purge_contacts.py`)

## 다른 PC 에서 보기
Docker 가 교육원 네트워크 주소로는 포트를 열지 않는 경우가 있어(11/5 교육원 PC 확인) 포트 연결로 넘겨준다 — `docs/design/virtual_demo.md` 4-2-1

## 예전 방식(standalone, 팀 DB 와 별개)
화면 전용 서버(`backend/`, FastAPI)와 DB(`app-db`)는 지우지 않고 `standalone` 프로필로 남겨 두었다. 팀 DB·관제탑과 데이터가 섞이지 않는다.
```
copy .env.app.example .env.app      # 팀 .env 와 다른 파일
TOWER_URL=http://app-api:8000 docker compose --env-file .env.app -f docker-compose.app.yml --profile standalone up --build -d
```
(PowerShell 은 `$env:TOWER_URL="http://app-api:8000"; docker compose ...`)

## 아직 없는 것
직원 인증·권한, TLS, rate limiting 은 아직 없다. 교육원 안 시연용으로만 연다.
