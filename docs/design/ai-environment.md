# AI 환경 세팅 — 메인 AI · LLM 검토 · MCP · 디스코드 (LF-14~17)

> 설계문서(components.md·interfaces.md)에서 뽑은 "AI 쪽이 돌아가려면 필요한 것" 목록과 세팅 순서. 시연 PC = 교육원 PC.

## 검토 결론 (11/3)
- **세팅 가능.** AI 영역 6개 컴포넌트(반환 흐름·LLM 검토·관제 알림·평가·자기 개선·MCP 서버)는 코드가 있고 가짜 부품으로 전 과정이 돈다(시험 90개).
- **교육원 PC 점검(11/3 09:37): 통과 10 · 주의 0 · 고칠 것 0** (Python 3.13.15, langgraph·mcp, 웹후크 3곳, Ollama + qwen3-vl:4b-instruct, RTX 3050 남은 5.3GB)
- 교차 검수 빈칸 중 안전 2개·보안 1개는 반영 완료(review.md 반영 결과). 남은 결정: 반환 기록 소유자(review 8)
- **AI 환경 밖이라 기다려야 하는 것**: 진짜 부품(비전 LF-3·매칭 LF-20·DB LF-8·로봇 LF-11·19·21), 실제 정답지, p95 한도

## 필요한 것 (컴포넌트별)
| 컴포넌트 | 필요한 것 | 없으면 |
| --- | --- | --- |
| 반환 흐름 | Python 3.11+, (선택) `langgraph` | LangGraph판만 꺼짐, 일반 흐름은 동작 |
| LLM 검토 | Ollama 실행 + `qwen3-vl:4b-instruct`, GPU 남은 메모리 약 3.5GB 이상 | 켜면 전부 직원 확인 → 꺼 두기 |
| 관제 알림 | `.env` 의 `DISCORD_WEBHOOK_PROGRESS/ALERT/SCORE`(또는 `DISCORD_WEBHOOK_URL`) | 화면에만 출력 |
| 평가·자기 개선 | 표준 라이브러리만, (선택) `numpy` | — |
| MCP 서버 | `mcp` 패키지 | 서버 실행 불가 |
| 시연 실행기 | 위 전부 + 2조 봇 세션(C:\git\discord-lab) | 사람이 PowerShell에서 실행 |

## 세팅 순서 (Windows 터미널 → PowerShell 탭)
1. 저장소·가상환경
```
cd C:\git\ai-lostfound-tower
.venv\Scripts\Activate.ps1
git pull
pip install -r requirements.txt
pip install -r agents/requirements.txt
```
2. Ollama 모델(Ollama 설치는 ollama.com → Download → Windows)
```
ollama list
ollama pull qwen3-vl:4b-instruct
```
3. 비밀값: `notepad .env` → `MAIN_AI_MODEL=qwen3-vl:4b-instruct`, 웹후크 3줄 확인(값은 어디에도 붙여 넣지 않기)
4. 한 번에 점검
```
python tools/check_ai_env.py
```
- ❌ 가 0개면 다음으로. ⚠️ 는 표의 "없으면"만큼 기능이 꺼진다
5. 동작 확인
```
python -m unittest discover -s tests
python evaluation/run_cases.py --reviewer
python tools/tower_demo.py
```
- `--reviewer` 결과에서 "잘못된 보류 0건"이면 시연에서 LLM 검토를 켜도 된다
6. (선택) 팀 DB + DB 모드: `docker compose up -d` → `.env` 에 `POSTGRES_PASSWORD`·`DATABASE_URL`·`TOWER_DB=1` → `tools\start_tower.bat`
7. (선택) MCP 서버: `python agents/mcp_server.py` (stdio로 대기 — 멈춘 것처럼 보이면 정상, Ctrl+C로 종료)

## 점검 도구가 보는 것 (tools/check_ai_env.py)
| 항목 | ✅ | ⚠️ | ❌ |
| --- | --- | --- | --- |
| Python | 3.11 이상 | — | 3.10 이하 |
| langgraph·mcp·numpy | 설치됨 | 없음(기능 일부 꺼짐) | — |
| .env 파일 | 있음 | — | 없음 |
| 디스코드 웹후크 | 채널 3곳 | 공용 하나 또는 없음 | — |
| MAIN_AI_MODEL | 설정됨 | 비어 있음(기본값) | `qwen3-vl:4b`(생각 전용판) |
| Ollama · 모델 | 실행 중 · 모델 있음 | 응답 없음 | 모델 없음 |
| GPU | 남은 메모리 3.5GB 이상 | 부족 · 확인 불가 | — |
- 비밀값은 출력하지 않는다(키가 채워졌는지만 봄). 아무것도 설치·전송하지 않는다
