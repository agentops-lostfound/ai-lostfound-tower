# AI 분실물 관제탑 (AgentOps)

지하철 역의 **습득물 등록기계**(보관함 + AI 카메라 + 터치패드)에 물건을 넣으면 AI가 품목과 특징을 인식해 본센터에 기록하고, 잃어버린 사람은 **웹에서 본인인증 후 직접 검색·확인**한 뒤 본센터에서 실물 신분증 확인을 거쳐 로봇팔에게서 물건을 받는 서비스입니다. 메인 AI와 하위 에이전트로 이뤄진 **AI 관제탑**이 전체 과정을 관리하고, 평가 에이전트가 정답지와 비교해 점수를 매겨 스스로 개선합니다.

팀 공유: [이순필의 정지·Home 시험 및 진행 현황 — 2026-11-04](docs/progress/pil2ya-team-update-2026-11-04.md). 실물 확인 결과와 미검증 범위를 구분했습니다.

## 폴더 구조
| 폴더 | 내용 | Jira |
| --- | --- | --- |
| `vision/` | 내부 AI 카메라 촬영·품목 인식 | LF-3 |
| `web/` | 모든 화면 — 키오스크(습득 신고·분실 확인·회수)·등록기계·분실인 웹·관제 모니터링(`/live`). 화면 지도 `web/README.md` | LF-2 · LF-4~6 · LF-17 |
| `center/` | 본센터 DB, 회수 기록, 통계 질문 | LF-8 · LF-9 |
| `robot/` | 로봇팔 보관·전달, 반환 안전 규칙 | LF-11 · LF-12 |
| `agents/` | 메인 AI, 하위 에이전트, MCP 도구 | LF-14 · LF-16 |
| `evaluation/` | 고정 채점기, 정답지, 자동 테스트 | LF-15 |
| `discord_ops/` | 디스코드 관제 알림 | LF-17 |
| `data/` | 데이터셋 규칙(사진 원본은 올리지 않음) | LF-10 |
| `docs/` | 설계 문서, 시연 시나리오 | LF-18 |

## 시작하기

Physical AI Studio의 저장 자세·복귀 기능을 다른 PC에 설치하려면 [Studio 공유 파일과 설치 순서](docs/handoff/studio-shared-install.md)를 따릅니다. 설치 압축본과 저장 자세는 저장소에 포함되며, Studio 자체와 장비 설정은 별도로 준비합니다.

```bash
git clone https://github.com/<조직이름>/<저장소이름>.git
cd <저장소이름>
python -m venv .venv
# Windows: .venv\Scripts\activate   /  WSL·macOS: source .venv/bin/activate
cp .env.example .env   # 비밀값은 .env에만 적는다
```

## 함께 일하는 규칙
[CONTRIBUTING.md](CONTRIBUTING.md)를 먼저 읽어 주세요. 요약:
- `main`에 직접 올리지 않고, 업무별 브랜치 → Pull Request → 1명 이상 확인 후 합칩니다.
- 브랜치 이름은 `LF-번호-이름-설명`(예: `LF-3-jaemin-vision-json`), 커밋 메시지 앞에는 Jira 업무 번호를 붙입니다. 예: `LF-3 품목 인식 모델 연결`
- PR 은 자동 시험(GitHub Actions)이 통과하면 올린 사람이 직접 합칩니다. 합친 브랜치는 자동으로 지워집니다.
- 토큰·API 키·개인정보·사진 원본은 절대 올리지 않습니다.
