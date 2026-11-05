# 관제탑 인수인계 (11/5 역할 조정)

한줄 설명: 11/5부터 **관제탑(API·DB·로봇 연결)과 모든 화면은 김재민**이 맡는다. 이 문서는 관제탑 코드를 처음 이어받는 사람이
"어디에 무엇이 있고, 무엇부터 만들면 되는지"를 한 번에 볼 수 있게 정리한 것이다. 2조봇에게 "docs/design/tower_handover.md 읽고 ○○ 해 줘"처럼 쓰면 된다.

## 0. 11/5 역할
| 사람 | 맡는 것 |
| --- | --- |
| 김재민 | 모든 화면(`web/`) + 관제탑 API(`agents/api.py`·`service.py`) + 팀 DB(`center/`) + 로봇 연결(`agents/robot_api.py`) |
| 변재원 | 챗봇(멀티에이전트·RAG·LangManus, 분실물 봇 `tools/lostfound_bot.py`) · 관제탑 PC 의 `.env`·방화벽 같은 PC 앞 작업 |
| 정연우 | 챗봇 보조 |
| 김건태 | 비전·매칭·집기(LF-19·20·21) |
| 이순필 | 로봇팔 정지·원점·작업대(LF-11·12) |

- 관제탑 코드·DB 표는 김재민이 **스스로 결정하고 PR 로 올린다**(다른 팀원 승인 기다릴 필요 없음). 다만 아래 "다른 사람이 쓰는 약속"을 바꾸면 PR 본문에 적는다

## 1. 큰 그림
```
[화면 web/]  --fetch-->  [관제탑 agents/api.py (FastAPI, :8100)]
                              |  service.py (요청 검사·반환 흐름 실행)
                              |  supervisor.py (반환 단계·안전 규칙)
                              v
              backends.py  CompositeBackend = 부품 묶음
               |- DB 부품      db_part.py      → 팀 DB (lostfound-db, :5434)   ← TOWER_DB=1
               |- 비전 부품    vision_adapter.py (김건태 결과 JSON)
               |- 매칭 부품    matcher_part.py
               |- 로봇 부품    (진짜는 아직 없음) / 가상 sim_world.SimRobot  ← TOWER_SIM=1
               '- 알림        discord_ops/reporter.py → 관제 채널              ← TOWER_SEND
[챗봇 tools/lostfound_bot.py] --/sim/*--> 관제탑   (변재원 담당, 바꾸면 서로 알림)
```

## 2. 파일 지도 (`agents/`)
| 파일 | 하는 일 | 자주 고칠까? |
| --- | --- | --- |
| `api.py` | 주소(엔드포인트) 목록. 화면 주소는 `PAGES` 표 | ★ 새 API 를 여기에 추가 |
| `service.py` | API 뒤에서 실제 일: 입력 검사 → 부품 호출 → 기록 | ★ 새 기능의 본체 |
| `contracts.py` | 팀 공통 약속(품목 6종 `CATEGORIES`, 상태 이름, 로봇 결과 모양) | 바꾸면 PR 에 이유 |
| `claims.py` | 찾기 요청 검사·저장(개인정보 거절 `has_pii`) | 키오스크 찾기 만들 때 참고 |
| `intake.py` | 습득 신고(`POST /items`) 검사·저장 | |
| `supervisor.py` | 반환 단계 순서와 안전 규칙(승인 없으면 로봇 안 움직임) | 신중히 |
| `backends.py` | 부품 묶기(`CompositeBackend`), 빠진 함수 검사 | 진짜 로봇 꽂을 때 |
| `db_part.py` | 팀 DB 읽기·쓰기 | DB 표 바꾸면 같이 |
| `robot_api.py` | 로봇 계약(명령 6개 + 상태 모양) 검사 | 계약 문서와 같이 |
| `sim_world.py`·`sim_director.py` | 가상 시연 세계(보관함 물건 8개, 가상 로봇, 이야기 진행) | `/live`·챗봇이 씀 |
| `live.py` | `/live/state` 화면용 데이터 | |
| `llm_reviewer.py`·`graph.py`·`mcp_server.py` | LLM 검토·LangGraph·MCP(챗봇 쪽과 겹침) | 변재원과 상의 |

## 3. 지금 있는 API (관제탑 켠 뒤 `http://127.0.0.1:8100/docs` 에서 직접 눌러 볼 수 있음)
| 무엇 | 주소 | 쓰는 곳 |
| --- | --- | --- |
| 상태 | `GET /health` | 점검 |
| 장소 목록 | `GET /places?machine=KIOSK-A` | 키오스크 습득 신고 |
| 습득 신고 | `POST /items`, `POST /items/{id}/features` | 키오스크·등록기계 |
| 찾기 요청 | `POST /claims`, `GET /claims/{id}` | 분실인 웹 |
| 반환 | `POST /returns`, `GET /returns`, `GET /returns/{id}`, `POST /returns/{id}/handover·hold` | (직원 화면 → 앞으로 본센터 키오스크) |
| 로봇 | `GET /robot/state`, `POST /robot/stop`, `POST /robot/home` | `/live` |
| 관제 | `GET /live/state` | `/live` |
| 가상 시연 | `POST /sim/found`, `POST /sim/lost`, `POST /sim/lost/{id}/answer`, `GET /sim/stories/{id}`, `POST /sim/reset` | 챗봇·`/live` (TOWER_SIM=1 일 때만) |

## 4. 다음에 만들 것 — 키오스크용 API (설계 메모, 결정은 김재민)
11/5 흐름(`web/README.md` 2절): 모든 키오스크 = 습득 신고 + 분실 확인, 회수는 본센터 키오스크만, 신분 확인은 키오스크 셀프, 직원 단계는 뺀다.

### 4-1. 분실물 후보 찾기 (예: `POST /kiosk/lost/search`)
- 입력(예): `machine_id`, `category`(6종), `description`, `lost_date`, `place`
- 출력(예): 후보 목록(접수 번호·품목·색·보관 장소 — **습득자 정보·사진 원본 없이**), `at_center`(이 키오스크가 본센터인지), 다음 안내(`"본센터에서 받으세요"` 또는 `"회수 진행"`)
- 참고할 코드: 가상 시연의 찾기(`sim_director.py` 의 lost → 확인 질문 흐름), 매칭 부품(`matcher_part.py`), 개인정보 거절(`claims.has_pii`)
- 본센터 여부: 팀 DB `machine.kind = 'center'` (`center/schema.sql`). 본센터 키오스크 번호는 아직 TBD → DB 에 한 줄 추가 필요

### 4-2. 본센터 회수 시작 (예: `POST /kiosk/pickup`)
- 순서(예): 셀프 신분 확인 결과 → 확인 질문(특징) → 찾기 요청 저장(`claims`) → 반환 시작(`service.start_return`) → 로봇팔 → 인계
- 지금 반환 흐름은 `staff_confirmed`(직원 확인) 칸을 요구한다. 11/5 결정으로 직원을 뺐으므로 "키오스크 셀프 확인"으로 바꿀지, 칸 이름만 "현장 확인"으로 읽을지 정해야 한다(`docs/contracts/robot_api.md` 3절 4번)
- 안전 규칙(승인 기록 없이 로봇 안 움직임, 정지 우선)은 그대로 둔다

## 5. 모드와 `.env` (값은 관제탑 PC 에만, 이름만 적음)
| 하고 싶은 것 | `.env` |
| --- | --- |
| 가상 시연(메모리, 끄면 사라짐) | `TOWER_SIM=1` |
| 팀 DB 에 저장 | `TOWER_SIM=` 비우고 `TOWER_DB=1` (+ `DATABASE_URL`) |
| 관제 채널로 알림 보내기 | `TOWER_SEND=1` — **작업 중엔 꺼 두면 팀 채널이 조용하다** |
- `.env` 는 2조봇이 읽거나 고치지 않는다. 바꿀 일이 있으면 교육원 PC 앞에서(변재원에게 부탁하거나 직접 메모장으로) 바꾸고 관제탑을 다시 켠다
- 새 설정이 필요하면 이름만 `.env.example` 에 추가한다

## 6. DB 표 바꾸는 법
1. `center/migrations/` 에 다음 번호 파일을 만든다(예: `006_center_kiosk_1106.sql`). `center/schema.sql` 에도 같은 내용을 반영해 새로 만드는 DB 와 맞춘다
2. `python tools/db_migrate.py` 로 적용할 파일을 미리 보고, `--apply` 로 적용한다(관제탑을 `tools\start_tower.bat` 로 켜면 자동 적용)
3. `docs/design/database.md` 표 설명도 함께 고친다
- 지우는 변경(DROP)은 되돌리기 어렵다 → 새 칸 추가 위주로

## 7. 고치고 확인하는 순서
```
2조봇: "agents/service.py 에 ○○ 추가해 줘" → 시험(python -m unittest discover -s tests) 통과 확인
      → "미리보기 주소 줘"(8101) → "PR 올려 줘" → GitHub Merge → "관제탑 반영해 줘"
```
- 관제탑을 `tools\start_tower.bat dev` 로 켜 두면 `agents/*.py` 가 바뀔 때 스스로 다시 켜진다(가상 시연 기록은 초기화)
- 새 API 에는 `tests/` 에 시험을 하나 이상 붙인다(예: `tests/test_robot_api.py` 모양 참고)

## 8. 다른 사람이 쓰는 약속 (바꾸면 PR 본문에 적고 알리기)
| 약속 | 쓰는 사람 |
| --- | --- |
| `/sim/*` 입력·출력 | 변재원(챗봇 `tools/lostfound_bot.py`) |
| `docs/contracts/robot_api.md` 1층 함수 | 김건태·이순필 |
| 비전 결과 JSON(`contracts.py`, `vision_adapter.py`) | 김건태 |
| `CATEGORIES` 6종 | 모두 |

## 9. 지키는 규칙 (요약)
- 화면은 DB 에 직접 붙지 않고 항상 관제탑 API 를 부른다
- 개인정보(전화번호·주민번호·이메일) 원문은 받지도 저장하지도 않는다. 디스코드·로그에는 물건 번호·사례 번호만
- `main` 직접 push·force push 금지, 업무 하나 = 브랜치 하나(`LF-번호-jaemin-영문-설명`)
