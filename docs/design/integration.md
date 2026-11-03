# 팀원 부품 연결 안내 — 구조는 관제탑, 부품은 각 담당

> 역할 분담(11/3 결정): **전체 구조(흐름·계약·평가·알림)는 변재원이 짠다. 팀원이 학습한 모델·만든 웹사이트·DB·로봇 동작은 이 구조에 "부품"으로 연결한다.**
> 연결 지점: `agents/backends.py` 의 `CompositeBackend`. 아직 없는 부품은 가짜로 채워져 흐름이 항상 끝까지 돈다.

## 1. 부품 묶음과 맞출 함수
| 묶음 | 담당(Jira) | 만들 함수 | 입력 → 출력 | 실패하면 |
| --- | --- | --- | --- | --- |
| vision | 김건태 LF-3 | `vision_topview()` | 없음 → `[{box, center, features, object_id?}]` | 빈 리스트 |
| matcher | 김건태 LF-20 | `match_item(query, detections)` | 특징 JSON, 검출 목록 → `{status, index, score, margin, ranking}` | `status: none` |
| db | 변재원 LF-8 | `db_get_item(item_id)`, `db_set_status(item_id, status)` | → `{item_id, status, features}` / `{ok, reason}` | `None` / `{ok: false}` |
| robot | 김건태 LF-19·21, 이순필 LF-11 | `robot_approach(center)`, `robot_grasp()`, `robot_verify_grasp()`, `robot_deliver()`, `robot_stop()` | → `{ok, reason}` | `{ok: false, reason}` |
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

## 3. 관제탑 쪽이 보장하는 것
- 안전 관문(동의·인증·확인 질문·신분증 대조·직원 확인·매칭 확신)은 부품이 아니라 흐름이 강제한다
- 상태 변경(`db_set_status`)이 실패하면 로봇을 움직이지 않는다 · 정지(`robot_stop`)가 실패하면 알림에 "직원 즉시 호출"
- MCP로 외부 AI에 여는 것은 읽기·비교·알림만, 물건 기록은 비공개 특징을 뺀 값만
- 알림에는 개인정보를 싣지 않는다(물건 번호·사례 번호만)
