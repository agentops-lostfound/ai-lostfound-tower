# ③ 인터페이스 — 컴포넌트 사이 계약

> 코드 기준(agents/*.py, discord_ops/reporter.py, evaluation/*.py). 함수마다 "실패하면"을 한 줄로 적었다.
> 외부 부품 쪽 상세 입·출력은 docs/contracts/mcp_tools.md 2장이 기준이다.

## 반환 흐름 (agents/supervisor.py, agents/graph.py)
```python
def run_return(req: ReturnRequest, backend, reporter, reviewer: Reviewer | None = None) -> Outcome:
    """6단계를 순서대로 실행해 결정 하나를 돌려준다."""
    # 실패하면: 예외를 던지지 않고 Outcome.decision 으로 표현(rejected / staff_check / stopped)
def run_return_graph(req: ReturnRequest, backend, reporter, reviewer=None, app=None) -> Outcome:
    """같은 단계 함수를 LangGraph StateGraph 로 실행(결과는 run_return 과 같아야 함)."""
    # 실패하면: langgraph 없으면 ImportError
def web_gate(c: Ctx) -> bool / visit_gate / locate / approach / grasp / deliver
    """단계 하나. True = 여기서 끝(c.out 에 결정 기록), False = 다음 단계로."""
```
- `Outcome.decision` 은 contracts.DECISIONS 4개 중 하나. `approved` 는 웹 단계 승인 여부
- `MAX_GRASP_ATTEMPTS = 2`(첫 시도 + 재시도 1번, 추정 — LF-19 시험 후 확정)

## 부품 묶음 (agents/tools.py — 진짜 부품도 같은 이름·입출력)
```python
def vision_topview() -> list[dict]          # 실패하면: 빈 리스트 → 흐름이 직원 확인
def match_item(query: dict, detections: list[dict]) -> dict
                                            # {status, index, score, margin, ranking}; uncertain·none → 직원 확인
def db_get_item(item_id: str) -> dict | None  # 실패·없음: None → 직원 확인
def db_set_status(item_id: str, status: str) -> dict   # {ok, reason}; 실패하면 로봇을 움직이지 않음(약속)
def robot_approach(center: list[int]) -> dict          # {ok, reason}; 실패 → robot_stop + 정지
def robot_grasp() -> dict                              # {ok, reason}; 실패 → 1번 재시도
def robot_verify_grasp() -> dict                       # {ok, reason}; 실패 → 집기 실패로 셈
def robot_deliver() -> dict                            # {ok, reason}; 실패 → robot_stop + 정지
def robot_stop() -> dict                               # {ok, reason}; 실패 → 직원 호출(약속)
```
- 검출 1개 형식은 `contracts.validate_detection` 이 검사하고, 형식이 틀린 검출은 버린다

## 부품 연결판 (agents/backends.py, 11/3 추가)
```python
class Backend(Protocol): ...                       # 위 부품 함수 9개의 모양(본문 없음)
def check_part(part: object, group: str) -> list[str]   # 빠진 함수 이름. 모르는 묶음 → ValueError
class CompositeBackend:
    def __init__(self, vision=None, matcher=None, db=None, robot=None, fallback=None)
        # 함수가 빠진 부품을 꽂으면 TypeError, 안 꽂은 묶음은 fallback(기본 MockBackend)
    def sources(self) -> dict[str, str]             # 함수 → 진짜 부품 클래스 이름 | "가짜"
    def is_all_real(self) -> bool
```

## LLM 검토 (agents/llm_reviewer.py)
```python
class OllamaReviewer:
    def __call__(self, summary: dict) -> tuple[str, str]:
        """("ok" | "hold", 메모). 입력은 사례 번호·접수 번호·상태만(개인정보 없음)."""
        # 실패하면: 시간 초과·형식 오류 → on_error(기본 "hold") = 직원 확인
    def warmup(self) -> float:   # 모델 올리기 걸린 초. 실패해도 예외 없이 걸린 초만 돌려줌(실패 여부는 알 수 없음)
```

## 관제 알림 (discord_ops/reporter.py, tools/notify.py)
```python
class Reporter:
    def send(self, channel: str, title: str, body: str = "") -> bool:
        """channel ∈ {progress, alert, score}. 개인정보 모양이면 막고 False."""
        # 실패하면: 모르는 채널 → ValueError / 전송 실패 → False (흐름은 계속)
    def progress(self, case, step, detail="") -> bool / alert(...) / score(title, body)
def notify(title: str, body: str = "", env_key: str = "DISCORD_WEBHOOK_URL") -> bool:
    # 실패하면: 웹후크 없음·네트워크 오류 → False
```
- 알림 함수 관계(위에서 아래로 부름): MCP `notify(channel, text)` → `Reporter.send(channel, title=text)` → (dry_run 아닐 때) `tools.notify(title, body, env_key=채널별 웹후크 키)`

## 평가 (evaluation/scoring.py)
```python
def supervisor_score(case_results: list[dict], violations: list[str]) -> dict   # score(0~100): 맞힌 사례 비율
def robot_score(trials: list[dict]) -> dict                                     # score: 바구니까지 전달 성공 비율
def safety_violations(case_results, blocked_messages: int = 0) -> list[str]     # 위반 설명 목록(0개가 정상)
def vision_score(preds: dict, truths: list[dict], judge=None) -> dict           # 35·C + 30·P + 20·R + 15·A
def should_adopt(base: dict, cand: dict, p95_limit: float | None, eval_complete: bool) -> tuple[bool, dict]
    # p95_limit 없음·정답지 미완성 → False(자동 채택 안 함)
```

## MCP 서버 (agents/mcp_server.py)
- 공개 도구: `list_tools · vision_topview · match_item · db_get_item · notify(channel, text)`
- `db_get_item` 은 비공개 특징(mark·visible_text = 확인 질문 정답)을 뺀 값만 돌려준다(11/3)
- 실패하면: mcp 패키지 없음 → SystemExit(설치 안내)

## 유스케이스 예외 대조표
| UC 예외 | 계약으로 표현? | 어디서 |
| --- | --- | --- |
| UC-1 ① 동의·인증 실패 | 표현 | web_gate → rejected |
| UC-1 ② 확인 질문 오답 + 알림 | 표현 | web_gate → rejected, alert |
| UC-1 ③ 물건 기록 없음 | 표현 | db_get_item None → staff_check |
| UC-1 ④ 신분증·안쪽 특징 불일치 | 표현 | visit_gate → 반환 보류 + rejected |
| UC-1 ⑤ 0개·매칭 불확실 | 표현 | locate → staff_check |
| UC-1 ⑥ 접근·전달 실패 | 표현 | robot_stop + stopped |
| UC-1 ⑦ 집기 재시도 | 표현 | MAX_GRASP_ATTEMPTS |
| UC-1 ⑧ LLM 보류·무응답 | 표현 | Reviewer on_error=hold |
| (약속) db_set_status 실패 시 로봇 안 움직임 | 표현(11/3 반영) | `_set_status()` → staff_check |
| (약속) robot_stop 실패 시 직원 호출 | 표현(11/3 반영) | `_stop()` → 알림에 "직원 즉시 호출" |
| UC-2 ① 개인정보 차단 | 표현 | Reporter.send → False, blocked |
| UC-2 ② 전송 실패해도 계속 | 표현 | 흐름이 send 반환값을 안 봄(의도) |
| UC-4 ①② 자동 채택 안 함 | 표현 | should_adopt |
| UC-6 ① 로봇 도구 비공개 | 표현 | EXPOSED |
