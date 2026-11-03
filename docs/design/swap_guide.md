# 부품 교체 안내서 — 가짜 부품을 팀원 결과물로 바꾸기 (11/3)

> 한줄 설명: 관제탑은 지금 가짜 부품으로 끝까지 돈다. 팀원이 만든 진짜 부품을 **한 번에 하나씩** 끼우고, 끼울 때마다 같은 시험으로 확인한다.
> 함수 모양(약속)은 [integration.md](integration.md) 1장과 `agents/contracts.py` 가 기준이다. 이 문서는 "언제·어떻게 바꾸고 무엇으로 확인하나"만 다룬다.

## 1. 지금 상태

```
                 +--------------------+
  web (mock) --> |                    | --> robot (mock)     Gunte LF-19/21, Soonpil LF-11
  Jaemin LF-4/6  |   TOWER  (Jaewon)  |
  vision (mock)->|   flow + DB + API  | --> discord (real)
  Gunte LF-3     |                    |
  matcher(code)->|                    |
  Gunte LF-20    +--------------------+
```

| 부품 | 지금 | 바꿀 것 | 바꾸는 방법 | 담당 |
| --- | --- | --- | --- | --- |
| DB | **진짜** | - | `.env` `TOWER_DB=1` | 변재원 LF-8 |
| 디스코드 알림 | **진짜** | - | `.env` `TOWER_SEND=1` | 변재원 LF-17 |
| 탑뷰 비전 | 가짜 | Qwen 결과 파일 | `.env` `TOWER_VISION_FILE=결과 폴더` (2장) | 김건태 LF-3 |
| 매칭 | 단순 비교(같은 글자만 맞음) | 칸별 점수 + 임베딩 | `CompositeBackend(matcher=…)` (3장) | 김건태 LF-20 |
| 로봇팔 | 가짜 | SO-101 + SmolVLA | `CompositeBackend(robot=…)` (4장) | 김건태 LF-19·21, 이순필 LF-11 |
| 분실인 웹 | 시안(가짜 데이터) | 관제탑 API 호출 | `POST /claims` (5장) | 김재민 LF-4·6 |

**교체 순서(권장)**: 비전 → 매칭 → 웹 → 로봇. 하나 바꾸고 시험이 통과한 뒤 다음으로 간다(문제가 생기면 방금 바꾼 부품이 원인).

## 2. 탑뷰 비전 — 결과 파일 스위치
- 김건태 님 `vision/sequence.py` 가 만든 `result_with_qwen.json` 을 `agents/vision_adapter.py` 가 계약 모양으로 바꿔 읽는다
- 관제탑 PC `.env` 에 두 줄을 넣고 관제탑을 다시 켠다(값은 예시)
```
TOWER_VISION_FILE=C:\git\ai-lostfound-tower\outputs\vision
TOWER_VISION_MAX_AGE=600
```
  - 폴더를 주면 그 안(하위 폴더 포함)의 **가장 최근** 결과 파일을 읽는다
  - `TOWER_VISION_MAX_AGE`: 이 초보다 오래된 결과는 쓰지 않는다(보관함이 바뀌었을 수 있음 → 직원 확인). 저장해 둔 파일로 시험할 때만 `0`
- 확인: 브라우저 `http://127.0.0.1:8100/health` → `sources.vision_topview` 가 `SequenceFileVisionPart` 이면 연결됨
- 주의: 시연 DB 물건(A-W01~W07)의 특징은 한국어 가짜 값이라, 진짜 Qwen 결과와는 매칭이 잘 안 맞는다. 실제 물건을 등록기계로 등록(Qwen 특징)한 뒤에 맞춰 본다

## 3. 매칭
- 만들 것: `match_item(query, detections)` 하나를 가진 클래스. 결과 `{status, index, score, margin, ranking}`
  - `status` 는 `matched`(자동 반환 가능) / `uncertain`(직원 확인) / `none`(직원 확인) 중 하나
- 방향(architecture.md 3-3): 색·품목은 칸별 점수(동의어 표: 푸른·퍼런→blue 등), 스티커·흠집 같은 자유 문장은 임베딩
- 확인: `python tools/mock_scene.py` 의 결과가 나빠지지 않아야 한다(6장)

## 4. 로봇팔
- 만들 것: `robot_approach(center)`, `robot_grasp()`, `robot_verify_grasp()`, `robot_deliver()`, `robot_stop()` — 모두 `{ok, reason}` 을 돌려준다
- **예외를 던지지 않는다.** 실패하면 `{"ok": False, "reason": "집기 실패"}` 처럼 돌려줘야 관제탑이 정지·직원 호출로 보낸다
- `center` 는 탑뷰 픽셀 좌표 `[cx, cy]`. 로봇 좌표로 바꾸는 보정은 로봇 부품 안에서 한다(탑뷰 결과의 `center_world_mm` 를 쓸지 TBD)
- 확인: 처음에는 **팔을 움직이지 않는 판**(명령만 기록)으로 끼워 흐름을 확인한 뒤, 실제 동작은 비상 정지 준비 후 한 사례씩

## 5. 분실인 웹
- 웹은 부품이 아니라 관제탑을 **부르는 쪽**이다. 가짜 데이터 대신 `POST /claims` 를 부르면 된다(본문 예시: architecture.md 3-2)
- 확인: 직원 화면 `http://127.0.0.1:8100/staff` 에서 웹이 만든 찾기 번호(C-…)가 조회되면 연결됨

## 6. 교체할 때마다 하는 확인(3가지)
1. `python -m unittest discover -s tests` — 전체 시험 통과
2. `check_part(부품, "묶음")` 가 `[]` — 빠진 함수 없음
3. `python tools/mock_scene.py` — 가짜 보관함 시나리오 9개(카드지갑 기준). **"다른 물건 집음"이 0건이어야 한다**
   - 디스코드에서 보기: 2조봇에게 "가짜 시나리오 돌려줘" → 요약 답(봇이 `--discord` 실행) / AgentOps 관제 채널 3곳에 남기려면 `--send`

## 7. 가짜 시나리오로 찾은 한계 (11/3, `tools/mock_scene.py`)
| 사례 | 내용 | 상태 |
| --- | --- | --- |
| S05 | 찾는 지갑이 보관함에 없는데, **생김새가 똑같은 다른 지갑을 집어 반환**함 | **해결(11/3, B 닮은 물건 검사) → 직원 확인** |
| S03 | 같은 물건을 다시 찍으니 Qwen 표현이 흔들림(red→dark red, rectangular→rectangle). 지금은 통과했지만 점수가 깎임 | 매칭 보강(3장)으로 대응 |

- S05 해결: **B. 닮은 물건 검사** 채택(11/3 변재원)
  - 매칭으로 고른 물건이 다른 보관 중 물건(`contracts.ACTIVE_STATUSES`)과도 찾는 물건만큼 닮았으면(점수 0.6 이상, 차이 0.15 미만) 자동 반환하지 않고 직원 확인
  - 보관 중 물건 목록은 DB 부품의 `db_list_active()` 로 읽는다. 못 읽으면 검사할 수 없으므로 역시 자동 반환하지 않는다
  - 대가: 똑같이 생긴 물건이 둘 다 보관 중이면 진짜 주인이 와도 직원 확인으로 간다(S09). 안전을 위해 받아들인다
  - 나중에 시간이 되면 A(보관 칸 번호 기록)를 더해 직원 확인을 줄인다(TBD)

## 8. 가짜로는 못 잡는 것(실물 단계에서 확인)
- 정확도: 실제 Qwen 의 오독(색·글자)
- 시간: Qwen 물건 2개 약 50초 + GPU 내리고 VLA 올리는 시간(가짜 부품은 즉시 답함)
- 위치: 카메라 좌표 ↔ 로봇 좌표 보정 오차
