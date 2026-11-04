# 팀원 부품 연결 안내 — 구조는 관제탑, 부품은 각 담당

> 역할 분담(11/3 결정): **전체 구조(흐름·계약·평가·알림)는 변재원이 짠다. 팀원이 학습한 모델·만든 웹사이트·DB·로봇 동작은 이 구조에 "부품"으로 연결한다.**
> 연결 지점: `agents/backends.py` 의 `CompositeBackend`. 아직 없는 부품은 가짜로 채워져 흐름이 항상 끝까지 돈다.

## 1. 부품 묶음과 맞출 함수
| 묶음 | 담당(Jira) | 만들 함수 | 입력 → 출력 | 실패하면 |
| --- | --- | --- | --- | --- |
| vision | 김건태 LF-3 | `vision_topview()` | 없음 → `[{box, center, center_mm?, features, object_id?}]` (center_mm 없으면 로봇 안 움직임) | 빈 리스트 |
| matcher | 김건태 LF-20 | `match_item(query, detections)` | 특징 JSON, 검출 목록 → `{status, index, score, margin, ranking}` | `status: none` |
| db | 변재원 LF-8 | `db_get_item(item_id)`, `db_set_status(item_id, status)`, `db_list_active()` | → `{item_id, status, features}` / `{ok, reason}` / `[{item_id, status, features}]` | `None` / `{ok: false}` / `None` |
| robot | 김건태 LF-19·21, 이순필 LF-11 | `robot_approach(center_mm, center_px)` (이동은 작업대 mm, 픽셀은 참고, 11/4), `robot_grasp()`, `robot_verify_grasp()`, `robot_deliver()`, `robot_stop()` | → `{ok, reason}` | `{ok: false, reason}` |
- 형식 상세: docs/contracts/mcp_tools.md 1·2장, 값 목록: agents/contracts.py
- **예외를 던지지 말고 약속된 실패 값을 돌려준다**(흐름이 실패 값을 보고 직원 확인·정지로 보낸다). `None` 이나 다른 모양을 돌려주면 실패로 처리된다
- 웹·직원 화면(김재민 LF-6 등)은 부품 묶음이 아니라 **관제탑을 부르는 쪽**이다: 관문 결과를 담아 관제탑 API `POST /returns` 를 HTTP로 부른다(architecture.md 3장, 본문 예시 포함). 화면 기술은 자유

## 2. 연결 순서 (예: 비전 담당)
1. 자기 모듈에 클래스 하나를 만든다
```python
# vision/part.py (예시 이름)
class VisionPart:
    def vision_topview(self) -> list[dict]:
        ...   # YOLO26s 검출 + Qwen3-VL 특징 JSON
```
2. 빠진 함수가 없는지 확인
```python
from agents.backends import check_part
print(check_part(VisionPart(), "vision"))   # [] 이면 연결 가능
```
3. 연결해서 사례를 돌려 본다(나머지는 가짜)
```python
from agents.backends import CompositeBackend
be = CompositeBackend(vision=VisionPart())
print(be.sources())     # vision_topview: VisionPart, 나머지: 가짜
```
4. 시험 통과 확인 후 PR(브랜치 `LF-번호-영문-설명`). 계약을 바꿔야 하면 PR에 이유를 적고 변재원 확인

## 2-1. 비전(LF-3) 연결 — 시퀀스 결과 파일 읽기 (11/3 준비)
- 김건태 님 `vision/sequence.py` 가 만드는 `result_with_qwen.json`(YOLO 박스 + Qwen general_items_v1, 영어 값)을
  `agents/vision_adapter.py` 가 계약 모양 `[{box, center, features}]` 으로 바꾼다
  - category: wallet·card_wallet→지갑, usb→USB, lip_balm→립밤, phone→모형폰, hand_cream→핸드크림, power_bank→보조배터리, 나머지→확인 불가
  - color: 첫 색을 계약 색 목록으로(dark brown→갈색, 목록 밖→기타, 없음→확인 불가)
  - mark: 스티커 있음→"star sticker (front corner)", 없음→없음, 모름→확인 불가 / visible_text: 읽은 글자, 못 읽음→확인 불가
- Qwen 이 물건당 수십 초라 반환 중에 다시 돌리지 않는다. 보관함을 찍을 때 미리 돌려 두고 관제탑은 **가장 최근 결과**만 읽는다
```python
from agents.backends import CompositeBackend
from agents.vision_adapter import SequenceFileVisionPart
be = CompositeBackend(vision=SequenceFileVisionPart("outputs/vision", max_age_s=600))  # 10분 넘은 결과는 안 씀 → 직원 확인
```
- 관제탑 API·MCP 서버는 `.env` 의 `TOWER_VISION_FILE`(결과 파일 또는 폴더)만 넣으면 위처럼 끼운다(교체 안내: [swap_guide.md](swap_guide.md) 2장)
- **남은 맞출 점(LF-3·20)**: Qwen 의 shape·material 은 영어(bifold, leather), 접수 DB 특징은 한국어(반지갑, 가죽)라
  매칭 점수가 낮게 나온다 → Qwen 프롬프트를 계약 값 목록(한국어)으로 고정하거나, 변환표를 늘린다(김건태 님과 결정)

## 2-2. 매칭(LF-20) 연결 — 김건태 정책 (11/3)
- `agents/matcher_part.py` 의 `PolicyMatcherPart` 가 `matching/policy.py` 를 `match_item` 약속으로 감싼다. 11/3 부터 기본(되돌리기 `TOWER_MATCHER=simple`)
- 결과 비교·남은 결정은 [swap_guide.md](swap_guide.md) 3-1

## 3. 관제탑 쪽이 보장하는 것
- 안전 관문(동의·인증·확인 질문·신분증 대조·직원 확인·매칭 확신)은 부품이 아니라 흐름이 강제한다
- 상태 변경(`db_set_status`)이 실패하면 로봇을 움직이지 않는다 · 정지(`robot_stop`)가 실패하면 알림에 "직원 즉시 호출"
- 매칭으로 고른 물건과 똑같이 생긴 다른 보관 중 물건이 있으면 자동 반환하지 않는다(닮은 물건 검사, swap_guide.md 7장)
- MCP로 외부 AI에 여는 것은 읽기·비교·알림만, 물건 기록은 비공개 특징을 뺀 값만
- 알림에는 개인정보를 싣지 않는다(물건 번호·사례 번호만)
