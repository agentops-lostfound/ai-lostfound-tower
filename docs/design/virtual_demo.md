# 전체 가상 시연 — 디스코드 한 줄로 습득부터 인계까지 (LF-29, 11/4)

> 한줄 설명: 등록기계·Qwen·탑뷰 카메라·로봇팔을 **움직임까지 보이는 가상 부품**으로 바꿔 끼우고, 디스코드 분실물 채널에 쓴 메시지 한 줄로 관제탑 전체 흐름(습득 → 회수 → 찾기 → 반환 → 인계)을 돌린다.
> 관제탑 자체(서비스·반환 흐름·김건태 매칭 정책·안전 규칙·GPU 사용권·정지 버튼)는 **진짜 코드 그대로** 지나간다. 진짜 부품이 생기면 그 부품만 바꿔 끼우면 된다.

코드: `agents/sim_world.py`(가상 세계·부품) · `agents/sim_director.py`(연출기) · `agents/live.py`(진행 기록판) · `web/live/index.html`(실시간 화면) · `tools/lostfound_bot.py`(분실물 봇) · 시험 `tests/test_sim_demo.py`

## 1. 보이는 장면

```
[디스코드 #분실물] "서면역 5번 출구 앞에서 검정 카드지갑 주웠어요"
  봇: 📥 습득물 접수 S-20261104-0001 · 서면역 5번 출구 앞 (KIOSK-C) · 지갑 · 검정 · 직사각형
  진행판(메시지 하나가 단계마다 바뀜)
    ✅ 등록기계 접수 → ✅ Qwen 특징 분석 → ✅ 본센터로 회수 → ✅ 보관함 배치(5번 칸)

[디스코드 #분실물] "검정 카드지갑 잃어버렸어요, 서면역에서요"
  봇: 📝 찾기 요청 C-20261104-0001 → 후보 S-20261104-0001 · 확인 질문 통과
  진행판
    ✅ 찾기 요청·확인 질문 → ✅ 메인 AI 승인 → ✅ 방문·직원 확인 → ✅ 탑뷰 촬영(물건 5개)
    → ✅ 매칭 → ✅ 사전 접근 → ✅ 집기 → ✅ 바구니 전달 → ✅ 인계 완료
```
- 같은 시간에 **실시간 화면 `/live`** 에서 보관함 탑뷰 그림 위로 물건이 놓이고, 로봇팔이 물건으로 다가가 집어 바구니로 옮기는 모습이 보인다
- 관제 채널(#관제-진행·#관제-알림)에는 지금과 같은 단계 메시지가 간다(`TOWER_SEND=1` 일 때)
- 확인 질문: 고른 후보에 비공개 특징(보이는 글자·스티커)이 있으면 봇이 먼저 묻는다. 예) 보조배터리 → "물건에 적힌 글자가 있다면?" → `VOVA`

## 2. 구조 — 무엇이 가상이고, 무엇이 진짜인가

```
 디스코드 #분실물 ──> 분실물 봇(tools/lostfound_bot.py) ──HTTP──> 관제탑 API (TOWER_SIM=1)
                                                                  │
            ┌────────────── 연출기(sim_director) ─────────────────┤ 사람·화면이 하던 일을 대신
            │  create_item · set_item_features · create_claim       │ (진짜 화면과 같은 입구만 부름)
            │  start_return · handover                              │
            v                                                       v
   관제탑 서비스·반환 흐름·매칭 정책·안전 규칙 (진짜)  ──부품 연결판──> 가상 부품
                                                                    ├ SimWorld  : 접수 저장 + DB 부품
                                                                    ├ SimTopview: 탑뷰 → result_with_qwen.json 모양 → 진짜 변환기
                                                                    └ SimRobot  : mm 좌표로 움직이는 팔(정지·원점 복귀)
   모든 관제 메시지 ──> 진행 기록판(LiveBoard) ──> 실시간 화면 /live · 봇 진행판
```

| 단계 | 가상 시연에서 하는 것 | 지키는 약속(함수 모양) | 진짜로 바꿀 때 |
| --- | --- | --- | --- |
| 등록기계 접수 | 연출기가 `create_item` 호출 | `POST /items` | 김재민 등록기계 화면(PR #48)이 같은 주소로 보냄 → 연출기 ① 생략 |
| Qwen 특징 | 메시지 글 → Qwen 모양 JSON(`sim_qwen`) → `set_item_features` | `POST /items/{id}/features` `{"qwen": …}` | 김건태 Qwen 작업이 같은 주소로 보냄 |
| 회수·보관함 배치 | 세계에서 물건을 옮기고 상태 `회수 중 → 본센터 보관` | `db_set_status(changed_by="staff")` | 직원 상태 변경 화면(TBD) |
| 찾기 요청 | 후보 카드(공개 특징) → 확인 질문 → `create_claim` | `POST /claims` | 분실인 웹(김재민 LF-2·4·6) |
| 반환 시작 | `start_return(claim_id + 현장 관문 3개)` | `POST /returns` | 직원 화면 "반환 시작" |
| 탑뷰 | 보관함을 "찍어" `result_with_qwen.json` 모양 → **진짜 `adapt_report`(보정 관문 포함)** | `vision_topview()` | `.env TOWER_VISION_FILE=결과 폴더` 만 넣으면 가상 시연 중에도 진짜 탑뷰로 바뀜 |
| 매칭 | **진짜** 김건태 정책(`PolicyMatcherPart`) | `match_item()` | 이미 진짜 |
| 로봇팔 | 작업대 mm 로 움직임·집기·바구니·정지·원점 | `robot_approach(center_mm, center_px)` 외 5개 | 로봇 부품(LF-11·19·21)을 `robot=` 에 꽂음 |
| 인계 | 3초 뒤 자동 `handover`(또는 `#수동인계`) | `POST /returns/{case}/handover` | 직원 화면 "분실인에게 건넴" |

- `/health` 의 `sources` 에서 함수마다 가상(`SimRobot` 등)인지 진짜인지 보인다
- 세계(SimWorld)는 관제탑 상태와 별개로 **물건이 실제로 어디 있는지**(등록기계·이동 중·보관함 칸·그리퍼·바구니)를 기억한다 → 매칭이 엉뚱한 물건을 고르면 화면에서도 엉뚱한 물건이 바구니로 간다(숨기지 않음)

## 3. 안전 규칙을 보여 주는 꼬리표

분실 신고 메시지 끝에 붙인다. 진짜 관제탑 규칙이 그대로 막는 장면이다.

| 꼬리표 | 장면 | 결과 |
| --- | --- | --- |
| `#집기실패` | 첫 집기 실패 → 1번 다시 집기 | 반환 완료(집기 2번째 시도) |
| `#보정실패` | 탑뷰 표식(ArUco) 보정 실패 → mm 좌표 없음 | 직원 확인 · 로봇 안 움직임 |
| `#신분증불일치` | 방문자 실물 신분증 불일치 | 반환 안 함 · 반환 보류 |
| `#수동인계` | 바구니까지만 | 직원 화면 `/staff` 에서 인계 확인 |
| (꼬리표 없이) 확인 질문 오답 | 예) 보조배터리 글자 `SAMSUNG` | 반환 안 함(확인 질문 미통과) |
| 디스코드 `정지` 또는 화면 🛑 | 반환 도중 즉시 정지 | 로봇 정지 → `원점` 으로 복귀 |

## 4. 켜는 법 (교육원 PC)

### 4-1. 분실물 봇 만들기(처음 한 번, 변재원이 직접 — 토큰은 채팅·문서에 쓰지 않는다)
1. 브라우저에서 디스코드 개발자 포털(https://discord.com/developers/applications) → **New Application** → 이름 `분실물봇`(예시) → Create
2. 왼쪽 **Bot** → **Reset Token** → 나온 토큰을 복사해 바로 메모장 `.env` 의 `LOSTFOUND_BOT_TOKEN=` 뒤에 붙여 넣고 저장
3. 같은 **Bot** 화면 아래 **Privileged Gateway Intents** → **MESSAGE CONTENT INTENT** 켜기 → Save Changes
4. 왼쪽 **OAuth2** → **URL Generator** → Scopes `bot` → Bot Permissions `View Channels` · `Send Messages` · `Read Message History` → 아래 주소 복사 → 새 탭에서 열어 팀 서버에 추가(서버 관리 권한이 필요하면 서버 관리자에게 부탁)
5. 디스코드 앱 설정 → 고급 → **개발자 모드** 켜기 → 분실물 채널 오른쪽 클릭 → **채널 ID 복사** → `.env` 의 `LOSTFOUND_CHANNEL_ID=` 에 붙여 넣기

### 4-2. 매번 켜기
```powershell
# 관리자 PowerShell(작업 탭)
cd $HOME\ai-lostfound-tower        # 저장소 폴더(PC 마다 다를 수 있음)
git pull
.\.venv\Scripts\Activate.ps1
pip install -r tools/requirements-bot.txt     # 처음 한 번
python -m unittest discover -s tests          # 통과 확인
```
- `.env` 에 `TOWER_SIM=1` 을 넣고 저장 → `tools\start_tower.bat` 로 관제탑 켜기(가상 시연에서는 DB 를 쓰지 않음)
- 브라우저 `http://127.0.0.1:8100/live` → 위 칩에 **모드 가상 시연** 이 보이면 준비 완료
- 새 PowerShell 탭: 같은 폴더·`.venv` 켠 뒤 `python tools/lostfound_bot.py` → `[분실물 봇] 연결됨` 이 나오면 디스코드에서 메시지 보내기
- 디스코드 없이 연습: `/live` 왼쪽 **시험 입력** 또는 `python tools/lostfound_bot.py --try "서면역 5번 출구 앞에서 검정 카드지갑 주웠어요"`
- 끝나면 `.env` 의 `TOWER_SIM=` 을 비우고 관제탑을 다시 켜면 원래(진짜 부품·DB) 모드

## 5. 알아둘 점
- **서면역 기계 KIOSK-C 를 새로 추가했다**(공통 약속 `agents/contracts.py` 변경, DB `center/migrations/005`). 접수 번호 앞글자는 **S** — `C` 로 하면 접수 번호가 찾기 번호(`C-날짜-순번`)와 똑같아진다
- 보관함에는 시연 물건 4개(빨강·남색 카드지갑, 은색 USB SanDisk, 검정 보조배터리 VOVA, 번호 `H-…`)가 미리 있다. 디스코드 `초기화` 로 처음 상태
- 가상 시연은 메모리에만 기록한다(관제탑을 끄면 사라짐). 찾기·반환 번호는 초기화해도 이어진다(같은 번호 재사용 방지)
- 메시지 원문은 저장하지 않는다. 장소 글·물건 특징만 남고, 관제 메시지는 기존 개인정보 검사를 그대로 지난다
- 봇은 교육원 PC 에서 켜 둔 동안만 동작한다. 2조봇과 다른 봇이므로 2조봇 허용 목록(access.json)은 바꾸지 않는다
- 가상 Qwen 은 낱말 표로 색·품목·글자를 읽는다(사진 아님). 표에 없는 말(예: "자주색")은 `기타`·`확인 불가` 로 남는다
- 시간: 반환 한 번 약 20초(`TOWER_SIM_SPEED=1`). 발표 때 더 빠르게 하려면 `0.5`

## 6. 남은 일(TBD)
- 회수(등록기계 → 본센터) 상태를 바꾸는 진짜 직원 화면·API — 지금은 연출기만 바꾼다
- 습득 접수를 관제 채널에 알리는 일을 진짜 서비스(`create_item`)로 옮길지 — 지금은 연출기가 알림
- 진짜 로봇 부품 연결 뒤 같은 장면을 `TOWER_SIM` 없이 재현(LF-29)
