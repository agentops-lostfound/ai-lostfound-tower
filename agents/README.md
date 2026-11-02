# agents — AI 관제탑 (LF-14·16)

| 파일 | 하는 일 |
| --- | --- |
| `contracts.py` | 팀 공통 입·출력 약속(비전 JSON, 검출, 로봇 결과, 상태·결정 이름) |
| `tools.py` | MCP 도구 목록(TOOLS)과 가짜 부품(MockBackend), 매칭 자리표시(진짜는 LF-20) |
| `supervisor.py` | 메인 AI 반환 흐름 — 안전 규칙은 코드로 강제, 집기 실패는 1번만 재시도 |
| `llm_reviewer.py` | 메인 AI LLM 검토(Ollama 로컬). '보류'만 할 수 있고 실패하면 직원 확인 |
| `mcp_server.py` | 읽기·비교·알림 도구를 MCP로 공개(`pip install mcp` 필요) |

- 도구 약속 문서: `docs/contracts/mcp_tools.md`
- 남은 일: LangGraph 그래프로 감싸기 — LLM은 결과를 '직원 확인'으로만 바꿀 수 있다
