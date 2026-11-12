# 프롬프트 staging 평가와 실제 사용 이력 (LF-5)

## 선택·읽기

- `LF_PROMPT_LABEL`: production(기본) 또는 staging. 다른 값은 오류로 거절한다.
- 이름+라벨+클라이언트로 캐시를 구분한다. staging 실패 후 production/latest를 다시 읽지 않는다.
- 본문과 config(model/temperature/use_llm)를 한 객체에서 함께 가져온다. 본문 컴파일에 실패하면 원격 config도 버리고 기본값을 적용한다.
- `LF_PROMPT_FETCH=1`: trace를 꺼도 프롬프트만 읽을 수 있다. 명시한 경우에만 읽기 SDK를 생성하며 tracing_enabled=False를 강제한다.
- 기본 동작은 기존대로 유지한다. 별도 읽기를 켜지 않았고 추적 클라이언트도 없으면 코드 기본값을 사용한다.
- SDK 범위는 테스트한 v3 호환선(langfuse>=3.15,<4)으로 제한한다. 현재 검증한 SDK는3.15.0이다.

공식 동작 근거: [버전/라벨 조회](https://langfuse.com/docs/prompt-management/features/prompt-version-control),
[프롬프트와 함께 버전 관리되는 config](https://langfuse.com/docs/prompt-management/features/config).

## 실제 사용 기록

단순 설정 조회나 비활성 역할을 사용한 것처럼 세지 않는다. 실제 모델 요청 직전에 아래를 기록한다.

agent / prompt 이름 / 요청 label / 실제 version / prompt_source(langfuse 또는 code) /
fallback_reason / template_sha256 / 실제 model·temperature·use_llm / setting_sources / calls.

- 원질문·답변·임의 config·키·토큰·컴파일된 사용자 변수는 이 기록에 넣지 않는다.
- 템플릿 해시는 원본 템플릿 기준이다. 코드 기본값 사용 시 클라우드 버전을 지어내지 않고 version=null로 남긴다.
- AgentBrain/RAG/실제 ops 모델 호출의 generation trace와 평가 JSON에 사용 이력을 남긴다.
- 평가 회차의 usage_scope는 다른 회차/스레드와 분리하며 HTTP 작업 스레드의 호출도 모은다.
- 요청 라벨이 staging이어도 코드 기본값만 썼으면 staging_provenance_complete=false다.
- 한 역할이 평가 중 서로 다른 버전·모델·설정으로 호출되면 mixed_agents에 표시한다.
- staging_provenance_complete는 출처 완전성만 뜻한다. 기능 점수·보안·성능 확인이나 운영 승인을 대신하지 않는다.

## 평가

클라우드 연결 설정이 준비된 사용자 실행 환경에서:

```powershell
python evaluation/chat_eval.py --model midm-2.0-mini --prompt-label staging
```

라벨을 명시하면 프롬프트 읽기를 켠다(명시적으로 LF_PROMPT_FETCH=0이면 유지).
trace는 기본 꺼짐이다. 고정50문항만 추적하려면 같은 라벨로 별도 실행한다.

```powershell
python evaluation/chat_eval.py --model midm-2.0-mini --prompt-label staging --trace --lf
```

연결이 없는 로컬 검증(.env/실제DB/Langfuse를 사용하지 않음):

```powershell
python tools/validate_chat_midm.py --suite 500 --prompt-label staging --out docs/reports/midm-500.json
```

이 경우 기록에 label=staging, prompt_source=code, version=null, 출처완전성=false가 남는다.
이를 클라우드 staging 버전 검증으로 보고하면 안 된다.
도구는 기존 엑셀/원본 점수를 덮어쓰지 않고 소스·문항 해시와 실제 모델 호출/대체 이력을 별도 기록한다.

## 적용 순서

1. staging 라벨의 프롬프트/config 준비(팀 운영 절차).
2. 고정 코드·문항으로 평가하고 실제 사용 버전/기본값/혼합 여부 확인.
3. 기능·안전·오류 복구·응답 성능 및 기존 대비 퇴행 확인.
4. 검토한 버전만 production 라벨 이동 대상으로 판단. 이 코드는 자동 게시·라벨 이동을 하지 않는다.

기존 tools/langfuse_setup.py의 --push-prompts 기본 대상은 production이다.
이번 작업에서는 실행하지 않으며 --force로 팀 production 내용을 덮어쓰지 않는다.
