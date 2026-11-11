# web — 모든 화면 (화면 지도, 11/5 정리)

> 11/6: 화면과 관제탑(API·DB·로봇 연결) 모두 **변재원**(11/5 김재민 → 11/6 작업 완료 후 이어받음). 관제탑 코드 안내는 `docs/design/tower_handover.md`

한줄 설명: 화면은 전부 이 폴더에 **화면 하나 = 폴더 하나(`index.html`)** 로 둔다. 관제탑(8100)이 이 파일을 바로 읽어 보여 주므로,
파일을 고치고 브라우저에서 새로 고침만 하면 된다(빌드·Docker 다시 만들기 없음). Docker 화면 앞문(8080)도 같은 화면을 보여 준다.

## 1. 화면 목록
| 화면 | 주소(관제탑 `:8100` 또는 Docker `:8080`) | 폴더 | 화면 담당 | 부르는 API | 상태(11/5) |
| --- | --- | --- | --- | --- | --- |
| **통합 시연(발표용, 11/10)** | `/showcase` (`?scene=found·lost·pickup·robot`, `?cam=server·demo·browser`) | `showcase/` | 변재원 | `GET /api/admin/live/state?detail=1`, `POST /sim/reset` | 세로 키오스크 틀·분실인 휴대폰 옆에 **DB 실시간 기록**과 **AI 에이전트 흐름**을 한 화면에(1920×1080 기준, F11 전체 화면 권장). 아래 1-00 |
| 키오스크 | `/kiosk?machine=KIOSK-A` | `kiosk/` | 변재원(이전 김재민) | `GET /api/kiosk/places`, `POST /api/kiosk/items` | 모든 역: 습득 신고 + 분실 확인, 본센터만 셀프 신분 확인·회수(11/5 정책, `docs/design/operating_flow_1105.md`). 탭 3개(습득 신고 / 분실접수 / 회수). 습득은 서버 연결됨 — **11/6 찍기 버튼 없이 자동 촬영**(상자 안 카메라가 빈 상자와 달라지고 3초 멈추면 찍음, 작은 흑백 화면만 비교 · 11/8 놓기→손 빼기→3·2·1→찰칵 진행 표시, 사진 파일 접수 없음, 카메라가 없으면 "카메라 점검 중 · 역무실에 알려 주세요", **직원 시연은 주소 끝에 `&demo=1`**(예: `/kiosk?machine=KIOSK-A&demo=1`) — 가상 카메라가 물건을 넣고 자동 촬영, 위쪽 "시연 모드" 배지에서 넣을 물건을 고름) + 품목 6종 놓는 법 안내 + 연락처 이용 목적 안내, **분실접수 탭은 입력 화면만**(후보 찾기 API 가 생기면 `/api/lost/…` 연결, 3차). 회수 탭은 **모든 키오스크에 보이고**(11/6) 역 키오스크에서는 "부산역 본센터로 가세요(찾기 번호·신분증)" 안내, 실제 회수는 `?machine=CENTER`(본센터)만 — `POST /api/kiosk/returns`(11/6, 관문 값은 서버가 정함). 11/10 본센터는 회수 탭으로 열리고 신분증 뒤 첫 자리 숫자 하나만 입력. 11/11 회수 뒤 [물건 받았어요] → `POST /api/kiosk/handover`(무인 인계) |
| (옛) 등록기계 | `/intake` → **`/kiosk` 로 넘김(11/10)** | (폴더 삭제, 11/10) | - | - | 키오스크 습득 탭이 같은 일을 함. 주소 뒤 `?machine=…` 는 그대로 넘어감 |
| 분실인 웹(분실 확인) | `/lost` | `lost/` | 변재원(이전 김재민) | (서버 연결 전) | 화면 흐름 시안. 분실 확인 후 본센터 방문 안내 정책 적용 예정 |
| 폰 화면 시연(발표용, 11/10) | `/phone` (다른 화면은 `/phone?src=/kiosk?machine=KIOSK-A`) | `phone/` | 변재원 | (없음 — 틀 안에 `/lost`) | 휴대폰 틀 안에 분실인 웹을 실제 휴대폰 크기로 띄우고, 입력칸을 누르면 **폰 모양 쿼티 키보드**. PC 키보드로 치면 같은 키가 눌리며 입력(사람이 폰으로 치는 모습). 실제 휴대폰은 폰 자체 키보드 그대로 |
| 관제 모니터링 | `/live` | `live/` | 변재원(이전 김재민) | `GET /api/admin/live/state`, `/sim/*`, `POST /api/robot/stop`, `/api/admin/robot/home` | 됨(가상 시연·SO-101 실제 형상) |
| 관리자 관제(로그인) | `/admin` | `admin/` | 변재원(이전 김재민) | `/api/admin/login·logout·me` | 로그인 후 관제 모니터링(`/live`)·반환/직원(`/staff`)·**보관함(`/storage`, 11/6 도착 물건 칸 넣기 — 옛 주소 `/storage-desk` 는 11/10 `/storage` 로 넘김)**을 탭으로. `.env` `LF_ADMIN_PASSWORD` 가 없으면 로그인 없이 열림 |
| AI 챗봇 위젯 | 화면에 `<script src="/chat-widget/widget.js">` · 시험 `/chat-widget/demo` | `chat-widget/` | 변재원 | `POST /chat/questions`, `/chat/suggestions`, `/chat/health` | 됨(가상 물건 DB). **11/6 키오스크(머리말 "AI 안내" 버튼, 키오스크 모드: 닫거나 90초 무입력이면 대화 지움)와 분실인 웹("AI챗봇 사용하기" 버튼)에 붙임** — `chat-widget/README.md` |
| 회수·통계 시연(LF-9) | 독립 실행 `python -m tools.run_collection_demo` → `:8110/collection-desk` | `collection-desk/` | 정연우 작업 완료(11/5 변재원 이어받음) | 시연 전용 `/collections*` (가상 SQLite) | 관제탑·팀 DB 와 미연결. 관리자 화면으로 쓸지 변재원 결정 — `docs/reports/2026-11-05-jaewon-takeover-yeonwoo.md` |
| 직원 화면 | `/staff` | `staff-desk/` | 변재원 | `/returns/*`, `/robot/*` | 11/5 결정: 직원은 정상 흐름에서 제외. 11/11 **예외 전용** — 확인 질문 미통과(직원 대면 확인)·직원 보관 선반 물건의 교차 검증, 정지·원점 복귀. 정상 인계는 본센터 키오스크 [물건 받았어요] |

- 등록기계 번호: `KIOSK-A` 중앙(앞글자 A) · `KIOSK-C` 초량(앞글자 S) · `CENTER` **부산역 본센터** 키오스크(앞글자 H). 11/6 중앙역(KIOSK-B)은 삭제
- 화면은 관제탑과 같은 주소에서 열리므로 `fetch("/items")` 처럼 앞부분 없이 부른다

## 1-00. 통합 시연 화면(11/10, `web/showcase/`)
- 한줄 설명: 발표 화면 하나에 **① 실제 사용자 화면(세로 키오스크·휴대폰) ② 저장소(DB)에 행이 생기고 칸이 바뀌는 모습 ③ AI 에이전트가 주고받는 흐름**을 같은 순서로 보여 준다.
- 장면 4개(머리말 탭): ① 습득 · 중앙역 키오스크(`/kiosk?machine=KIOSK-A`) ② 분실 신고 · 분실인 휴대폰(`/phone`) ③ 회수 · 본센터 키오스크(`/kiosk?machine=CENTER`, 회수 탭이 바로 열림) ④ 로봇 작업대(`/live?embed=1` — 11/11 제목·연결 칩을 빼고 작업대 그림 높이를 화면에 맞춰 1920×1080 에서 보관판·로봇팔이 한 화면에 들어옴)
- 11/11 ① 탭: 켜진 채로 한 번 더 누르면 중앙역(KIOSK-A) ⇄ 초량역(KIOSK-C)(`?kiosk=C`). 초량역에 웹캠 설정이 없으면 중앙역 웹캠을 같이 씀(키오스크 `?camsrc=KIOSK-A`). 작은 사진(팀 DB 조회·사진 분석)을 누르면 이 창 안에서 크게 보기(바깥·✕·Esc 로 닫기)
- 11/11 키오스크 [물건 잃어버렸어요] 탭 = 분실인 웹(`/lost?embed=kiosk&station=이 역`)과 같은 화면·같은 접수. 분실인 웹 색 고르기는 품목의 실제 색을 먼저, 나머지는 [다른 색 ▾]. 화면 키보드 칸에 Ctrl+V 붙여넣기 됨
- 11/11 빈 화면 안내: 기록이 생기기 전에는 DB 칸에 그 장면에서 바뀌는 표(INSERT·UPDATE·SELECT)를, 에이전트 칸에 말이 오가는 순서를 보여 주고 첫 기록이 생기면 사라진다. 본센터 키오스크 회수 탭 아래에는 '이렇게 받아요'(번호 확인 → 로봇이 꺼냄 → 직접 꺼내기) 순서
- 가운데 **DB 실시간 기록**: 표 이름·칸 이름은 팀 DB 와 같은 영문 이름 + 쉬운 한글 이름을 함께 적는다(`item` 습득물 · `place_text` 발견 장소). 위쪽 두 장은 "지금 보는 행"(`item` · `claim`)이고 값이 채워질 때 반짝인다. 아래는 기록 흐름(INSERT·UPDATE·DELETE·SELECT)
  - 사건은 `agents/db_watch.py` 가 저장소 함수를 감싸 만든다. **이름·전화번호·가린 신분 번호·비공개 특징 값은 서버가 보내지 않는다**(🔒 "저장됨"만 표시)
  - **팀 DB 에도 함께 저장(11/10, `agents/db_mirror.py`)**: `tools\start_tower.bat` 로 켜면 가상 시연의 접수·특징·상태·찾기 요청·보관 칸·반환 기록을 팀 DB(PostgreSQL)에도 쓴다 → 머리말 "저장소 팀 DB 저장 n건", `item` 카드에 "팀 DB 저장됨" 표시. 끄기 `start_tower.bat nodb`(머리말 "저장소 메모리")
  - [기록 흐름] 옆 **[팀 DB 조회]**: 팀 DB 에서 방금 읽은 최근 접수 — 사진 · 접수 번호 · 접수한 곳(역·등록기계) · 발견 장소 · 품목 · 상태 · 칸 · 접수 시각, 표별 행 수(`GET /api/admin/db/recent`)
  - 실제 운영 기록은 덮지 않는다: 글 신고·시연용 물건은 `item.object_id='SIM'` 으로 표시, 같은 번호의 실제 기록이 있으면 넘김, 보관 칸은 이 부품이 쓴 것(`assigned_by='system'`)만 바꿈. 팀 DB 가 꺼져 있으면 "팀 DB 연결 안 됨"으로 표시하고 시연은 메모리로 계속
  - 읽기(SELECT)는 분실 신고 후보 검색 · 챗봇 물건 검색 · 키오스크 회수/반환 흐름에서 일어난 것만 보인다(화면이 0.4초마다 부르는 조회는 뺌)
- **사진 분석(Qwen) 카드(11/10, `agents/vision_watch.py`)**: ① 습득 장면에서는 "찾기 요청" 카드 자리에 **Qwen3-VL 사진 분석** 카드가 나온다 — 접수 사진 · 단계(사진 접수 → 작업자가 가져감 → Qwen 분석 → 결과 → 저장) · 걸린 시간 · 표 "**Qwen 이 읽은 값 | DB 에 저장한 값**"(종류 `hand_cream` → 핸드크림, 색 `white, blue` → 흰색 …). 결과가 오면 바로 옆 `item` 카드의 품목·공개 특징 칸이 채워지고 [기록 흐름]에 `UPDATE item`(Qwen 사진 분석)이 쌓인다
  - 사건은 관제탑이 만든다: 키오스크 사진 접수 → `queued`, 작업자가 대기 목록을 물음 → `picked`, 작업자가 알림(`POST /api/admin/intake/analysis/{접수 번호}` `{"stage": "analyze"|"wait_gpu"|"fail"}`) → 분석 중·실패, 특징 저장 → `result`
  - **읽은 글자·스티커·특이점(확인 질문 정답이 되는 값)은 개수·상태만** 보낸다("1개 읽음", 🔒 "저장됨(값은 가림)")
  - Qwen 작업자가 꺼져 있으면 카드에 "작업자 꺼짐"과 켜는 명령이 보인다(작업자가 대기 목록을 12초 안에 물었는지로 판단, 응답의 `qwen_worker`). 글로 한 가상 신고는 사진이 없어 이 카드가 움직이지 않고, 기록에는 "가상 분석(글 신고)"로 적힌다
- **물건 카드의 직원 단추(11/10)**: 아직 등록기계에 있는 물건에만 보인다
  - **[본센터로 회수]** `POST /api/admin/items/{번호}/collect` — 칸 대기(보관함 열이 꽉 참)·사진 분석이 늦게 끝나 멈춘 물건을 지금 회수. 맞는 빈 칸이 있으면 그 칸, 없으면 **직원 보관 선반**(S-n). 사진 분석 전에는 꺼져 있다
  - **[접수 취소]** `POST /api/admin/items/{번호}/cancel` — 실수로 접수한 물건을 지운다(**되돌릴 수 없음**, 두 번 눌러 실행). 가상 세계와 팀 DB(함께 저장 중이면)에서 물건·상태 기록·연락처를 지우고, 기록 흐름에 `DELETE item` 이 남는다. 회수된 물건·찾기 요청이 걸린 물건은 지우지 않는다. 사진 파일은 남는다
  - 키오스크 "접수되었습니다" 화면에도 **[잘못 찍었어요 · 접수 취소]** 가 있다(`POST /api/kiosk/items/{번호}/cancel`, 방금 접수한 것만 — 3분 안, 조작 화면에서만)
  - **찾기 요청 단추(11/10)** — `/live` 처리 현황 카드와 통합 화면(`/showcase`) 찾기 요청 카드에, 방문 전인 요청에만 보인다. [직원 확인 후 진행] `POST /api/admin/claims/{찾기번호}/visit`(본센터 방문 대기에서 직원 대면 확인으로 반환 시작 — 확인 질문이 맞지 않아 키오스크가 받지 않는 요청도) · [찾기 요청 취소] `POST /api/admin/claims/{찾기번호}/cancel`(두 번 눌러 실행, 물건은 계속 보관). 분실인 웹 완료 화면의 [찾기 요청 취소]는 `POST /api/lost/claims/{찾기번호}/cancel`(가린 신분 번호로 본인 확인). 단추에 쓰는 목록은 `/api/admin/live/state` 의 `claims_open`(개인정보 없음)
  - **로봇 작업대(`/live`)의 🗑 [기록 삭제](11/10)** `POST /api/admin/items/{번호}/purge` — 저장소에 있는 물건을 골라 그 물건에 딸린 기록을 **전부** 지운다(두 번 눌러 실행, 되돌릴 수 없음): 물건 · 상태 기록 · 연락처 · 보관 칸(칸이 빈다) · 찾기 요청(확인 질문·방문 예약 포함) · 반환 기록(단계 포함) · 개수 확인 · 회수 묶음. 가상 세계와 팀 DB 모두. 그 물건만 가리키던 찾기 요청은 함께 지우고, 다른 물건도 후보로 둔 요청은 남긴다. 반환 중(로봇이 움직이는 중)인 물건은 지울 수 없다. 사진 파일은 남는다
  - 가상 시연(`TOWER_SIM=1`)에서만 동작한다
- 오른쪽 **AI 에이전트 흐름**: [관제탑 에이전트](메인 AI 를 거쳐 키오스크 AI·DB·보관 칸·매칭·로봇팔·채점 에이전트가 주고받음, `agents/agent_talk.py`·`tower_brain.py`) / [챗봇 에이전트](coordinator → planner → supervisor ⇄ 일꾼 → reporter — Langfuse 에 남는 단계와 같은 순서, `agents/observability.py` 리스너). 새 사건이 온 쪽으로 저절로 바뀌고, 단추를 누르면 그쪽에 고정
- **에이전트 그림 자동 전환(11/10)**: 챗봇 질문이 들어오면 [챗봇 에이전트], 관제탑 에이전트가 일하면(에이전트 대화 · 메인 AI 판단 · 사진 분석) [관제탑 에이전트] 그림으로 스스로 바뀐다. 챗봇 질문이 진행 중이거나 막 끝났으면(4초) 관제탑 사건이 그림을 뺏지 않고, 사용자가 직접 고르면 8초 동안 유지한 뒤 다시 따라간다
- **챗봇 단계 순서(11/10)**: `reporter` 도 실행 기록에 남겨 실제 순서(일꾼 → supervisor → reporter → supervisor 가 끝을 정함 → 답)대로 그린다. 일꾼(researcher 등)이 만든 글은 "답 초안"으로 표시하고, 화면에 나가는 답은 reporter 가 정리한 뒤의 "답 · 화면에 표시" 한 줄이다. 재생은 밀린 시간에 맞춰 빨라져 실제 챗봇 화면보다 그림이 늦게 따라오지 않게 한다
- **챗봇 답과 그림의 때 맞추기(11/10)**: ① 챗봇 창(`web/chat-widget/widget.js`)은 진행 막대가 **100% 가 된 뒤에** 답을 보인다(답이 오면 남은 숫자를 최대 0.45초에 채움) ② 챗봇 창이 질문을 보내는 순간 바깥 화면에 알려(`postMessage`, 질문 내용은 안 보냄) 챗봇 그림으로 곧바로 바꾸고 0.12초마다 읽는다 ③ 이미 끝난 질문의 남은 단계는 쉬지 않고 재생한다. 잰 값(클라우드): 2초 걸리는 답은 그림이 '답'에 닿은 뒤 0.1~0.2초 뒤에 답이 나오고, 0.1초 안에 끝나는 규칙 답은 그림이 0.4초쯤 늦다
- 사건이 한꺼번에 와도 하나씩 순서대로 재생한다(밀리면 빨라짐). [처음으로] = 가상 세계 초기화(두 번 눌러 실행)
- 주소 옵션: `?scene=lost` 처럼 시작 장면 · `?cam=demo`(가상 카메라 자동 촬영) · `?cam=server`(관제탑 PC 웹캠) · `?cam=browser`(이 브라우저 카메라). 안 주면 `TOWER_KIOSK_CAMERAS` 에 KIOSK-A 가 있으면 server, 없으면 demo
- 관리자 로그인(`LF_ADMIN_PASSWORD`)이 켜져 있으면 `/admin` 에서 먼저 로그인해야 가운데·오른쪽 칸이 채워진다(같은 문지기)
- 에이전트 칸의 챗봇 질문·답 요약은 전화번호·주민번호·이메일 모양만 가려서 보인다(Langfuse 로 보내는 것과 같은 기준). 관리자 로그인을 끈 채 `lan` 으로 열면 같은 네트워크의 다른 PC 도 이 요약을 볼 수 있으니, 발표 때 실제 개인정보는 입력하지 않는다

## 1-0. 화면 키보드(11/10, `web/ui/vkeyboard.js`)
- 한줄 설명: 입력칸을 누르면 아래에 쿼티 키보드가 뜨고, **터치로 누르거나 PC 키보드로 치면** 그 칸에 들어간다. PC 키보드로 칠 때는 화면 키보드의 같은 키가 손가락으로 누른 것처럼 눌려 보인다(발표용)
- 키오스크(모든 입력칸, 큰 키) · 폰 화면 시연 `/phone`(폰 모양). 한글 두벌식 조합 · 영문 · 숫자, [한/영]·PC 한/영 키·오른쪽 Alt 로 전환
- 칸별: `type=tel`·`data-vk="num"` 숫자 패드, `data-vk="id"` 숫자 + `*` + `-`(가린 신분증), `data-vk="en"` 영문 시작, `data-vk-upper` 대문자, `data-vk="off"` 끄기
- 키보드가 붙은 칸은 `readonly` 로 바뀐다 → 태블릿 자체 키보드·윈도우 한글 입력기가 끼어들지 않음(글자는 화면 키보드만 넣음)

## 1-1. 공통 디자인(11/8 디자인 개편)
- 모든 화면은 `web/ui/theme.css`(색·글자·간격 토큰 `--ui-*`, 부품 `.ui-btn`·`.ui-card`·`.ui-input`·`.ui-chip`·`.ui-badge`)와 `web/ui/theme.js`(라이트/다크 전환)를 쓴다. 관제탑이 `/ui/theme.css`·`/ui/theme.js` 로 제공
- 새 화면: `<head>` 에 `<link rel="stylesheet" href="/ui/theme.css?v=20261111a">` + `<script src="/ui/theme.js"></script>`, 머리말에 `<span data-theme-slot></span>`(전환 버튼 자리). 색은 토큰만 쓴다(직접 색 값 금지 → 다크에서 깨짐)
- 전환: 처음엔 휴대폰·PC 밝기 설정을 따르고, 버튼을 누르면 그 브라우저에 기억. 관리자 화면 안쪽(iframe) 화면도 함께 바뀜
- 글꼴 Pretendard 는 인터넷으로 받는다. 끊기면 맑은 고딕 등 시스템 글꼴로 열린다(화면은 정상)

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
- 물건 종류는 운영 품목 4종: 휴대폰(목업폰) · 보조배터리 · 핸드크림 · 립밤 (`agents/contracts.py` ACTIVE_CATEGORIES = MVP_CATEGORIES). 11/11 카드지갑(포토박스 탑뷰 인식이 어려움)·11/9 USB 는 운영에서 뺐다 — 계약 CATEGORIES 에는 옛 기록 때문에 남아 있다
  - 11/8: 화면에는 **휴대폰**으로 보인다. 품목 값(계약·DB·비전·매칭·API JSON)은 `모형폰` 그대로라, 서버 값을 화면에 보일 때는 표시 사전 `{모형폰: "휴대폰"}`(파이썬은 `agents/contracts.py` `category_label()`)을 거친다. 사용자 입력은 `모형폰`·`휴대폰` 둘 다 알아듣는다
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

## 키오스크 카메라 설정 (11/6 결정: 키오스크는 PC 화면에서 운영)
- **11/6 17시 실측: 갤럭시 탭 A8(SM-X200, Android 14) 크롬은 USB 웹캠을 보여 주지 않는다.** `&camsetup=1` 목록에 내장 카메라 2개(`camera 0, facing back`·`camera 1, facing front`)만 나오고 ROYCHE 웹캠은 없었다(OTG 케이블 연결 상태). 안드로이드 크롬은 기기 카메라 체계(Camera2)에 등록된 카메라만 쓰는데, 이 기종은 외부 USB 카메라 등록을 지원하지 않는 것으로 보인다(추정) → **태블릿 키오스크는 포기, 키오스크는 PC 화면에서 운영**
- 포토박스 탑뷰 캠(ROYCHE RPC-20F, UVC 1080p)은 **키오스크 화면을 띄우는 PC**에, 보관함 탑뷰 캠과 로봇팔 캠은 **관제탑 PC**에 꽂는다(같은 PC 라면 카메라 3대가 한 PC 에 — USB 포트 고정·라벨)
- 키오스크 PC 에서 `http://127.0.0.1:8080/kiosk?machine=KIOSK-A` (중앙) · `KIOSK-C` (초량) · `CENTER` (부산역 본센터). 처음 한 번 주소 끝에 `&camsetup=1` 을 붙여 목록에서 포토박스 캠(이름에 USB·Webcam·FHD)을 고르면 그 PC 브라우저에 기억된다. 번호 고정 `&cam=2`, 이름 일부 `&cam=webcam`
- **브라우저는 https 또는 localhost(127.0.0.1)에서만 카메라를 준다.** 관제탑 PC 자신이 키오스크면 `127.0.0.1` 로 열면 된다. 다른 PC 에서 `http://10.10.21.21:8080/kiosk` 로 열면 카메라가 막힌다 → 그 PC 크롬 `chrome://flags/#unsafely-treat-insecure-origin-as-secure` 에 `http://10.10.21.21:8080` 입력 → Enabled → Relaunch (교육원 내부 시연에서만)
- 11/6 교육원 PC(10.10.21.21)에서 USB 캠 "USB CAMERA (1124:2925)" 인식·자동 촬영·접수(H-20261106-0009)까지 확인함
- **11/10 조작 화면은 하나(`agents/kiosk_control.py`)**: 같은 기계의 습득 화면을 여러 PC 에서 열어도 **한 화면만 찍고 접수**한다. 화면이 2초마다 `POST /api/kiosk/control/{기계}` 로 묻는다 — 조작 화면이 없으면 먼저 물은 화면이 되고, 있으면 **보기 전용**(영상만, "다른 화면에서 사용 중")이 된다. 보기 전용 화면의 **[여기서 조작하기]** 로 넘겨받는다. 조작 화면이 8초 동안 소식이 없으면(창을 닫음·다른 탭·통합 시연의 다른 장면) 자리를 내준다. 사진 접수(`POST /api/kiosk/items`)도 조작 화면에서 온 것만 받는다(409). 가상 카메라(시연 모드)·분실 신고·챗봇은 그대로
- **11/10 물건을 뺀 것은 찍지 않는다**: 물건이 든 모습이 빈 상자 기준으로 잡힌 뒤(물건을 둔 채 화면을 처음 열었거나 [빈 상자 다시 확인]을 누름) 물건을 빼면, 전에는 "달라졌다"만 보고 **빈 상자를 찍었다**. 이제 달라진 자리가 둘레(바닥)와 비슷해졌으면 "물건이 빠졌다"로 보고 찍지 않으며, 그 빈 상자를 새 기준으로 삼아 기억한다(`changeKind`). 바닥과 비슷한 물건·다른 물건으로 바꾼 경우는 구별하지 않고 예전처럼 찍는다
- **11/10 자동 촬영 보강**: ① 멈춘 뒤 **5초**에 찍는다(전에는 3초) ② **[지금 찍기]** — 자동으로 안 잡힐 때 지금 화면을 바로 찍는다 ③ **빈 상자 기억** — 물건을 찍고 상자를 비웠을 때의 모습을 이 브라우저에 기억해 두고, 다음에 화면을 열 때 물건이 이미 들어 있으면 그 기억과 견줘 찍는다(전에는 물건을 둔 채 새로고침하면 그 모습을 빈 상자로 삼아 영영 못 찍었다). 배경지를 바꾸면 기억을 스스로 버린다 ④ **[빈 상자 다시 확인]** — 기억을 지우고 지금 상자를 빈 상자로 다시 잡는다(상자를 비운 뒤 누름). 가상 카메라(시연 모드)는 기억을 쓰지 않는다
- **11/9 태블릿 키오스크 다시 가능 — 서버 카메라(`&cam=server`)**: 태블릿은 화면만, 웹캠은 관제탑 PC 에 꽂는다. PC 가 웹캠을 읽어 영상(MJPEG `/api/kiosk/camera/{기계}.mjpg`)을 보내고, 키오스크 화면은 그 영상으로 물건 감지·3초·자동 촬영을 똑같이 한다. 태블릿 크롬이 카메라를 직접 열지 않으므로 **https 설정·태블릿 웹캠 지원과 상관없음**
  1. 관제탑 PC: `python tools/list_cameras.py` → 상자 위 웹캠 번호 확인(사진이 `data/camera_check/` 에 저장됨)
  2. `.env` 에 `TOWER_KIOSK_CAMERAS=KIOSK-A=0`(기계=번호, 1번 단계에서 "영상이 보이는 번호" — 교육원 PC 웹캠 1대면 0, 여러 대면 쉼표 `KIOSK-A=0,KIOSK-C=1`) → 관제탑 다시 켜기
  3. 태블릿 크롬: `http://10.10.21.21:8100/kiosk?machine=KIOSK-A&cam=server` — 머리말에 "PC 카메라 연결됨"
  4. 상태 확인: `http://10.10.21.21:8100/api/kiosk/cameras` · 한 장 보기 `/api/kiosk/camera/KIOSK-A.jpg`
  5. **11/11 노출 고정(선택, `TOWER_KIOSK_EXPOSURE`)**: 회색 펠트를 깔면 카메라 자동 노출이 화면을 밝게 올려 분홍·하늘색 핸드크림·흰 물건이 하얗게 날아간다(색이 흰색으로 찍힘). 관제탑을 끄고 흰 폰을 상자 가운데 둔 채 `python tools/camera_exposure.py` → 값마다 사진(`data/exposure_check/sheet.jpg`)과 "물건 날아감 %"가 나오고 추천 값이 나온다 → `.env` 에 `TOWER_KIOSK_EXPOSURE=-6`(추천 값) → 관제탑 다시 켜기 → `/api/kiosk/cameras` 의 `exposure` 에 요청 값·카메라가 읽은 값이 보임. 비우면 예전처럼 카메라가 정함. "노출 값을 바꿔도 밝기가 거의 같음"이 나오면 이 웹캠이 노출 고정을 받지 않는 것 — 비워 둔다. **화이트밸런스 고정(`TOWER_KIOSK_WB`, 켈빈 2800~6500)**: 자동 화이트밸런스는 큰 색 물건이 들어오면 그 색을 빼 버려 물건마다 색 기준이 달라진다 → 조명을 한 모드(11/11 흰색 권장)로 정하고 상자를 비운 채 `python tools/camera_exposure.py --exposure 고른노출 --wb auto,4000,4600,5200,6000` → 회색 펠트가 가장 회색인 값 추천 → `.env` `TOWER_KIOSK_WB=추천값`(상태 `/api/kiosk/cameras` 의 `white_balance`). 조명 모드를 바꾸면 다시 고른다. **11/11 교육원 웹캠은 OpenCV 노출·화이트밸런스 명령을 받지 않음**(읽은 값 `-1`, 값을 바꿔도 밝기 같음) → `python tools/camera_exposure.py --props`(받아들이는 설정 목록) · `--dialog`(웹캠 드라이버 설정 창 + 미리보기에 날아간 점 % 실시간, `s` 저장 · `q` 끝)으로 손으로 바꿔 본다. 드라이버 설정은 웹캠을 뽑았다 꽂으면 풀릴 수 있음(추정)
  - 같은 웹캠을 PC 크롬 키오스크(`127.0.0.1`)가 동시에 쓰면 "다른 프로그램이 사용 중" — 서버 카메라를 쓰는 동안 PC 쪽 키오스크 탭은 닫는다
  - 설정에 없는 기계 번호는 열지 않는다(404, 주소만 바꿔 탑뷰 카메라를 보지 못하게). 아무도 안 보면 60초 뒤 웹캠을 닫는다
  - 끌 때: Ctrl+C 한 번이면 3초 안에 꺼진다(11/9 저녁 — 키오스크 영상 연결이 끝나지 않아 `Waiting for connections to close` 에서 멈추던 것을 `--timeout-graceful-shutdown 3` 으로 막음, `tools/start_tower.bat`)
  - 11/10 그래도 안 꺼져 탭이 먹통이 되던 것: 서버는 멈췄는데("Finished server process") 파이썬이 남는 경우가 있었다 → `tools/run_tower.py` 가 웹캠을 놓고 프로그램을 끝낸다(서버가 멈춘 직후, 또는 Ctrl+C 뒤 8초). `start_tower.bat` 가 평소에는 이 실행기를, `dev` 에서는 예전처럼 uvicorn 을 쓴다. Ctrl+C 뒤 `일괄 작업을 끝내시겠습니까 (Y/N)?` 가 보이면 `Y` + Enter
  - 11/9 저녁 보강: 관제탑 창에 `VideoCapture::open(DSHOW) ... can't be used to capture by index` 경고가 쏟아지면 **.env 번호에 카메라가 없다는 뜻**(교육원 PC 웹캠 하나만 꽂으면 보통 `0`). 이제 DirectShow 로 안 열리면 Media Foundation 으로 한 번 더 열고, 실패하면 5초 쉬었다 다시 열어 경고가 쏟아지지 않는다. 영상이 새까마면 MJPG 를 빼고 다시 열고, `/api/kiosk/cameras` 에 `warning` 이 뜬다
