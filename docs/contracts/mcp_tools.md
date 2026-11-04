# MCP 도구 약속 (LF-16)

> 메인 AI(LF-14)가 다른 모듈을 부를 때 쓰는 "버튼" 목록이다. 코드 기준은 `agents/tools.py`(TOOLS)와 `agents/contracts.py`이며, 이 문서와 다르면 코드를 기준으로 이 문서를 고친다.
> 지금은 가짜 부품(`MockBackend`)으로 동작한다. 각 담당자는 **같은 이름·입력·출력**으로 진짜 부품을 만들어 바꿔 끼운다.

## 1. 공통 약속
- 비전 결과: 고정 항목 JSON `category · color · shape · mark · visible_text · material · confidence`
  - 판단 불가 `확인 불가`, 표시가 없음을 확인 `없음`, 카드·신분증 글자 `개인정보 가림`
  - `mark`·`visible_text`는 비공개 특징(후보 카드에 안 보임)
- 탑뷰 검출 1개: `{"box": [x1,y1,x2,y2], "center": [cx,cy], "features": {비전 결과}, "object_id": 선택}` (픽셀 단위)
- 로봇 함수 결과: `{"ok": true}` 또는 `{"ok": false, "reason": "집기 실패"}`
- 매칭 결과: `{"status": "matched|uncertain|none", "index": 0, "score": 0.86, "margin": 0.29, "ranking": [0,2,1]}`
- 알림에는 개인정보 없이 물건 번호만 쓴다(전화번호·주민번호·카드번호·이메일 모양이면 전송을 막는다)

## 2. 도구 목록
| 도구 | 진짜 부품 담당 | 하는 일 | 입력 | 출력 | 실패하면 |
| --- | --- | --- | --- | --- | --- |
| `vision_topview` | 김건태 LF-3 | 탑뷰로 공용 보관함 촬영 → 물건마다 박스·중심·특징 | 없음 | 검출 목록 | 빈 목록 → 직원 확인 |
| `match_item` | 김건태 LF-20 | 접수 특징 ↔ 탑뷰 물건 비교 | query(특징), detections | 매칭 결과 | uncertain·none → 자동 반환 안 함 |
| `db_get_item` | 변재원 LF-8 | 접수 번호로 기록 읽기 | item_id | `{item_id, status, features}` | None → 직원 확인 |
| `db_set_status` | 변재원 LF-8 | 상태 변경·기록 | item_id, status | `{ok, reason}` | 로봇을 움직이지 않음 |
| `db_list_active` | 변재원 LF-8 | 보관함에 있을 수 있는 물건 목록(닮은 물건 검사, 11/3) | 없음 | `[{item_id, status, features}]` | `None` → 자동 반환 안 함 |
| `robot_approach` | 김건태 LF-21 | 픽셀 → 로봇 좌표, 접근 자세로 이동 | center | `{ok, reason}` | 정지 + 알림 |
| `robot_grasp` | 김건태 LF-19 | SmolVLA 근거리 집기·들기 | 없음 | `{ok, reason}` | 1번만 재시도, 그래도 실패면 정지 |
| `robot_verify_grasp` | 김건태 LF-19 | 그리퍼 닫힘 + 탑뷰 재확인 | 없음 | `{ok, reason}` | 실패로 처리 |
| `robot_deliver` | 이순필 LF-11 | 바구니까지 이동·그리퍼 열기 | 없음 | `{ok, reason}` | 정지 + 알림 |
| `robot_stop` | 이순필 LF-11 | 즉시 정지·Home | 없음 | `{ok, reason}` | 직원 호출 |
| `notify` | 변재원 LF-17 | 관제 채널 알림 | channel(progress·alert·score), text | `{ok}` | 흐름은 멈추지 않음 |

## 3. AI에게 여는 범위
- MCP 서버(`agents/mcp_server.py`)로 여는 도구는 **읽기·비교·알림만**: `list_tools · vision_topview · match_item · db_get_item · notify`
- 로봇·상태 변경 도구는 열지 않는다. 메인 AI 흐름(`agents/supervisor.py`)이 안전 관문(동의·인증·확인 질문·신분증 대조·직원 확인·매칭 확신)을 모두 지난 뒤에만 부른다
- MCP `db_get_item` 은 비공개 특징(`mark`·`visible_text`)을 뺀 값만 돌려준다(확인 질문 정답이 외부 AI에 새지 않게, 11/3)
- 흐름은 `db_set_status` 가 `{ok: false}` 면 로봇을 움직이지 않고, `robot_stop` 이 실패하면 알림에 "직원 즉시 호출"을 붙인다(11/3)
- 닮은 물건 검사(11/3): 매칭으로 고른 물건이 다른 보관 중 물건(`contracts.ACTIVE_STATUSES`)과도 찾는 물건만큼 닮았으면(점수 0.6 이상, 차이 0.15 미만) 자동 반환하지 않고 직원 확인 — 사진으로 구별할 수 없는 물건을 잘못 돌려주지 않기 위해
- 진짜 부품 연결: `agents/backends.py` 의 `CompositeBackend(vision=…, matcher=…, db=…, robot=…)` — 안내 docs/design/integration.md

## 4. 상태 이름
`등록기계 보관 → 회수 중 → 본센터 보관 → 확인 중 → 승인·수령 예약 → 반환 중 → 인계 완료` (막히면 `반환 보류`)

## 5. 통합 때 주의할 점 (변재원 검토)
- **GPU 메모리(시연 PC RTX 3050 6GB)**: Qwen3-VL-4B(Q4 약 3.3GB)와 SmolVLA를 동시에 올리지 않는다. 탑뷰 특징 추출이 끝나면 VLM을 내리고(Ollama `keep_alive: 0`) 집기 정책을 올린다. 메인 AI LLM 검토도 같은 Qwen3-VL-4B를 써서 모델을 하나 더 올리지 않는다
- **카메라가 달라 특징이 어긋날 위험**: 접수 특징은 등록기계(포토박스 LED 조명)에서, 비교할 특징은 본센터 탑뷰(다른 조명·각도)에서 뽑는다. 색·글자가 다르게 읽히면 매칭이 자주 '불확실'이 되어 직원 확인으로 빠진다 → 같은 지갑을 두 카메라로 찍어 항목별 일치율을 먼저 재고, 덜 맞는 항목은 매칭 가중치를 낮춘다(LF-20)
- **LLM 검토는 기본 꺼짐**: 시연 PC에서 `python evaluation/run_cases.py --reviewer` 로 잘못된 보류가 0건일 때만 켠다
- **Qwen3-VL-4B는 instruct판을 쓴다(11/2 시연 PC 측정)**: `qwen3-vl:4b` 는 생각 전용판이라 `"think": false` 를 보내도 무시하고 답마다 생각 글 약 1,800~2,500자(약 500~700토큰, 10~14초)를 먼저 쓴다. `qwen3-vl:4b-instruct` 로 바꾸면 같은 JSON 답이 22토큰 · 평균 2.7초 · 생각 글자 0, 처음 올리기 약 7초(100% GPU). 특징 JSON 추출(LF-3)도 `ollama pull qwen3-vl:4b-instruct` 로 받아 이 이름을 쓴다
