# agents — AI 관제탑 (LF-14·16)

> 11/5부터 관제탑 담당은 김재민. 처음 이어받을 때는 `docs/design/tower_handover.md` 부터 읽는다.

| 파일 | 하는 일 |
| --- | --- |
| `contracts.py` | 팀 공통 입·출력 약속(비전 JSON, 검출, 로봇 결과, 상태·결정 이름) |
| `tools.py` | MCP 도구 목록(TOOLS)과 가짜 부품(MockBackend), 매칭 자리표시(진짜는 LF-20) |
| `supervisor.py` | 메인 AI 반환 흐름 — 안전 규칙은 코드로 강제, 집기 실패는 1번만 재시도 |
| `llm_reviewer.py` | 메인 AI LLM 검토(Ollama 로컬). '보류'만 할 수 있고 실패하면 직원 확인 |
| `graph.py` | 같은 단계 함수를 LangGraph 노드로 연결(`python agents/graph.py`) |
| `mcp_server.py` | 읽기·비교·알림 도구를 MCP로 공개(`pip install mcp` 필요) |

- 도구 약속 문서: `docs/contracts/mcp_tools.md`
- 설치: `pip install -r agents/requirements.txt` (langgraph·mcp)
- 남은 일: 개선 회차(실행→채점→개선안 비교→기록) 그래프, 진짜 부품 연결
