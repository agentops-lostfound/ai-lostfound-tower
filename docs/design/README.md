# AI 관제탑 설계문서 5종 (LF-14~17)

> 수업 Day2 섹션3 "5대 설계문서" 방식(AI 초안 → 사람 검수 → 반영)으로, **이미 있는 코드와 약속 문서를 기준으로** AI 관제탑(메인 AI·평가·MCP·디스코드)의 모양을 정리한 문서다.
> 범위: 변재원 담당 AI 영역. 비전·로봇·DB·웹 내부는 "외부 부품"으로만 다룬다.

| 순서 | 문서 | 정하는 것 | 입력 |
| --- | --- | --- | --- |
| 0 | [architecture.md](architecture.md) | 전체 구조·PC 배치·관제탑 API·데이터 소유 | 결정(11/3) |
| ① | [usecases.md](usecases.md) | 누가·무엇을·왜, 예외 흐름 | docs/contracts/mcp_tools.md, evaluation/test_cases.json |
| ② | [components.md](components.md) | 부품·책임·하지 않는 것·의존 | ① |
| ③ | [interfaces.md](interfaces.md) | 함수 계약·실패 시 동작 | ②, agents/*.py |
| ④ | [sequence.md](sequence.md) | 반환 흐름 호출 순서(Mermaid) | ③ |
| ⑤ | [erd.md](erd.md) · [database.md](database.md) | 관제탑 기록 근거 · 전체 DB 표 설계 | ①, ③ |
| 검수 | [review.md](review.md) | 문서·코드끼리 어긋난 곳(표만) | ①~⑤ |
| 환경 | [ai-environment.md](ai-environment.md) | AI 환경 세팅 순서·점검 | ②, ③ |
| 연결 | [integration.md](integration.md) | 팀원 부품(모델·DB·로봇·웹) 연결 방법 | ③ |
| 교체 | [swap_guide.md](swap_guide.md) | 가짜 부품 → 팀원 결과물 교체 순서·확인·가짜 시나리오로 찾은 한계 | integration.md |

- 코드가 기준이다. 문서와 코드가 다르면 review.md 에 적고, 어느 쪽을 고칠지는 사람이 정한다.
- 기준 입·출력 약속(agents/contracts.py, docs/contracts/mcp_tools.md)을 바꾸려면 PR에 이유를 적고 팀원 확인을 받는다.
