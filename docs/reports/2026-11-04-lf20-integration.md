# LF-3 → LF-20 검사 전용 연결 및 실데이터 비교

## 확인 범위

2026-11-04 GitHub API에서 LF-3-yolo-aruco HEAD `9ab5e0b`를 확인했다. 로컬 HEAD도 동일하다. 작업 전 미추적 파일은 `run_vision_adapter_full.py.pre_unify.bak`뿐이며 보존했다. 이번 변경은 커밋·푸시하지 않았다.

Jira LF-3·10·19·20·21의 설명, 완료 기준, 전체 댓글을 읽었다. LF-3·10·20·21은 진행 중, LF-19는 해야 할 일이다. LF-20 완료 기준은 시험 Top-1 80% 이상(목표 추정), 불확실 자동 반환 0건, 없는 물건 거절이다. 현재 인간 정답이 없어 이 기준의 정확도를 채점하지 않았다. 의존 관계는 본문·댓글에서 LF-3→LF-20, LF-21→LF-19, LF-11→LF-19로 확인했다. 도구 응답에서 별도 issuelinks 필드는 반환되지 않아 공식 링크 관계까지 확인했다고 주장하지 않는다.

Jira LF-3 본문의 YOLO26s·Ollama4B·PaddleOCR, LF-21 본문의 마커4개는 실제 구현 및 최신 댓글과 다르다. 실제 기본은 YOLO26n/.25/640, Transformers Qwen3-VL-2B, 입력 최대 변512다. Adapter는 8대응점·최대3mm를 검사하지만 markers_mm={}로 실측 전이다. PaddleOCR은 비전 환경에 없고 시퀀스 호출도 없다.

## 인터페이스와 최소 변경

- raw: objects[].id/bbox/center_px/qwen.features; 특징은 영어 복수 colors/materials 및 상세 스티커·손상 목록.
- 관제탑 Adapter: box/center/features/vision_id, center는 픽셀 소수점1자리. 검증된 경우만 center_mm. category/color는 공통 한국어 값이며 변환 시 세부 정보가 줄어든다.
- HybridMatcher: candidates[].id/features와 query의 category/colors/sticker_status/free_text(영어). 구조화 속성 필터 후 자유 특징 MiniLM. 형태·글자·스티커 모양은 각각 독립 가중치가 아니라 자유 특징 임베딩에 함께 들어간다.
- 기존 qwen_bridge는 object_id만 읽고 반올림 전 좌표와 완전 일치를 요구해 통합 Adapter를 그대로 받을 수 없었다.
- 이번에 canonical vision_id와 기존 object_id를 모두 지원하되 충돌은 거부했다. canonical 좌표는 원본을 동일하게 반올림한 값과 비교한다. 임의 오차 허용은 하지 않는다. 중복·누락 ID와 장면 불완전·Qwen 실패 차단을 유지한다.
- Adapter 출력으로 객체 정체성·기하를 확인한 뒤 원본 Qwen 특징을 Matcher에 전달한다. 한국어 공통 요약에서 영어 특징을 역추정하지 않는다.
- engine matched/needs_confirmation/no_match와 관제탑 contract uncertain을 분리한다. 브리지는 검사 전용으로 항상 uncertain; 로봇 승인 없음. Supervisor는 matched가 아니면 직원 확인으로 끝난다. 프로덕션 조립부·계약 정의·로봇 코드는 변경하지 않았다.
- matching.inspect_sequence는 기존 JSON을 읽어 KoreanFirstParser→브리지→HybridMatcher를 실행한다. 사진별 독립 후보군을 유지한다. 반복 사진을 하나의 물품 DB에 등록하거나 자동 중복 제거하지 않는다. 그 작업에는 별도 실물 inventory ID가 필요하다.

## 실행과 집계

```powershell
$env:PYTHONIOENCODING='utf-8'
& ..\.venv-query\Scripts\python.exe -u -m matching.inspect_sequence `
  --batch outputs/batch_vision_20261104_113444 `
  --batch outputs/batch_vision_20261104_123347 `
  --output-dir outputs/matching/lf20_integration_20261104
```

기존 16장×512/384 두 배치×한국어6질의=192회. YOLO·Qwen GPU 재실행, 로봇 이동, DB 작업, Jira 수정은 하지 않았다. 출력은 위 폴더의 results.json(추출·번역·전체 순위·거절 이유·내부/외부 판정), summary.csv(요약)다. 개인정보 가능성이 있는 원본 특징을 보고서에 복제하지 않는다. 실행 출력은 Git 제외한다.

| 입력 | 내부 matched | 내부 needs_confirmation | 내부 no_match | 엔진 미실행 |
|---|---:|---:|---:|---:|
| 512 | 14 | 15 | 43 | 24 |
| 384 | 11 | 18 | 43 | 24 |
| 합계 | 25 | 33 | 86 | 48 |

144회가 브리지를 통과했다. 48회는 4개 사진×두배치×6질의의 무검출·불완전 상태로 sequence_incomplete 보류다. 엔진 no_match로 집계하지 않았다. 관제탑 결과는 192회 모두 uncertain이다. 이 숫자는 정답률이 아니다.

## 대표 관찰

| 질의·사진 | 512 | 384 |
|---|---|---|
| 검정 VOVA 보조배터리 / set2 | id2, .8085, 내부 matched | id2, .5904, 보류 |
| 검정 VOVA 보조배터리 / set6 | id1, .8903, 내부 matched | id1, .6571, 보류 |
| 글자는 기억 안 나는 검정 보조배터리 / set6 | id1, 1.0, 내부 matched | id1, .7143, 보류 |
| 휴대폰처럼 생긴 검정 물건 / phoneset | id1·2 동점1.0, 보류 | 동일 |
| 카드지갑 / set2 | id3 1.0, id1 .8 | 동일 상위2개 |

사용자가 알려준 실제 보조배터리 상표는 VOVA다. 512에서 문자 오독에도 품목·색으로 후보가 유지됐고, 384에서 category=other가 되자 품목 불확실성으로 보류됐다. 점수1.0은 요청한 일부 속성의 가중 일치이며 확률100%가 아니다.

원본 set2/set6를 시각 확인했다. set2의 열린 갈색 지갑 안 카드가 별도 card_wallet 후보로 잡히는 모습과, set6의 USB·그림 물품이 검출 후보에 없는 것을 관찰했다. 이는 AI의 시각 관찰이지 사람이 확정한 정답지가 아니다. 사용자는 이번에 추가 정답 검수를 하지 않기로 했으므로 human_ground_truth=null을 유지하고 정확도·재현율을 계산하지 않았다.

## 드러난 미해결 문제와 다음 순서

1. “빨간색 우산”에서 우산을 지원하지 않아 category=unknown, red만 남는다. topview1에서는 내부 matched가 나왔다. 미지원 품목을 명시적으로 보존·보류해야 한다. 이번에 사전이나 가중치를 실험 정답에 맞춰 수정하지 않았다.
2. “검정색 물건인데 정확히 모르겠어요”는 단일 적격 후보가 있으면 내부 matched가 된다(set5/topview1/usb, 양쪽 배치 총6회). 현재 최종 보류로 차단되지만 자동 확정용 정책은 추가 검증해야 한다.
3. “휴대폰처럼 생긴” 모호성이 phone 확정 조건으로 변환된다. 추출의 확실성과 사용자가 말한 품목을 구분할 필요가 있다.
4. 카드지갑 후보가 열린 지갑 속 카드일 수 있다. 객체 분할·포함 관계 및 사람 검수가 필요하다.
5. 일반 자유 특징 부정·미검출·품목/색 오판독·카메라 간 흔들림은 남아 있다. 이번 512/384는 해상도 실험이며 두 카메라 교차 검증이 아니다.
6. 실물 ID, 사람 정답, 촬영 세션을 붙인 독립 평가 전까지 Top-1 목표 달성을 선언하지 않는다. 한국어 requires_review 및 검사 전용 uncertain을 유지한다.

## 회귀 검증

변경 전 UTF-8 환경:226개 중225통과·1스킵. 변경 후230개 중229통과·1스킵. 새4개 검사는 통합 Adapter 반올림/미보정 연결, 충돌 ID, 비유한 좌표, 후보 순서 변경 시 ID→index 보존이다. 기본 CP949에서 GPU 사용권 오류 메시지의 em dash 출력 문제가 기존에 확인돼 UTF-8로 실행했다. 콘솔 호환 코드는 이번 범위에서 변경하지 않았다.

관련 자료: [LF-20](https://agentops-lostfound.atlassian.net/browse/LF-20), [LF-3](https://agentops-lostfound.atlassian.net/browse/LF-3), [기준 커밋](https://github.com/agentops-lostfound/ai-lostfound-tower/commit/9ab5e0b).

## 후속: 한국어 질의 보류 보강

사용자 승인 후 미지원 품목·품목 불명·외형 유사 표현을 명시적인 match_block_reasons로 보존했다. 우산 등 일부 미지원 품목은 원문 span도 보존한다. 한국어 전처리의 공통 guard_decision이 이 조건을 적용하므로 blanket requires_review를 나중에 해제해도 해당 제약은 유지된다. 임베딩 모델·가중치·후보 특징·관제탑 계약은 변경하지 않았다.

inspect_sequence 출력에는 engine_decision(점수만의 원래 판정), query_policy_decision(원문 제약 적용), final_decision(전처리 전체 검토 제한 적용), contract_result(관제탑 검사 전용)을 분리했다. top3는 확인용 후보이며 보류 후에도 표시된다. 확정·반환 승인을 의미하지 않는다.

동일192회 재실행 결과는 `outputs/matching/lf20_query_guard_20261104/{results.json,summary.csv}`에 별도로 저장했다.

| 질의 | 기존 내부 matched | 질의 제약 적용 후 matched | 비고 |
|---|---:|---:|---|
| 검정 VOVA 보조배터리 | 4 | 4 | 엔진 판정 전체 동일 |
| 글자 기억 안 나는 검정 보조배터리 | 4 | 4 | 엔진 판정 전체 동일 |
| 휴대폰처럼 생긴 검정 물건 | 5 | 0 | 품목 유사 표현 보류 |
| 카드지갑 | 4 | 4 | 엔진 판정 전체 동일, 카드 오검출 문제는 남음 |
| 빨간 우산 | 2 | 0 | 미지원 품목 증거 유지·보류 |
| 정체 모르는 검정 물건 | 6 | 0 | 품목 미확정·보류 |

질의 제약 적용 결과: matched12·needs_confirmation87·no_match45·엔진미실행48. 기존 단순 엔진 결과 matched25에서13개를 보류한 것과 함께, 품목 정보가 사라진 상태의 no_match도 보류로 바뀌었다. 없는 우산을 정확하게 no_match로 분류한 개선은 아니다. 정보 손실 상태로 확정하거나 부재를 단정하지 않는 보강이다. 관제탑 최종 결과는 이전과 같이192회 전부 uncertain.

한계: 미지원 사전은 우산·열쇠·이어폰·헤드폰·노트북·안경·가방·시계 일부이며 전 한국어 품목을 인식하지 않는다. 사전에 없는 품목도 category=unknown이면 보류하나, 지원 품목과 혼합된 복잡한 문장·부품/무늬 언급은 과도하게 보류하거나 놓칠 수 있다. 유사 표현 규칙도 유한하며 추가 독립 문장이 필요하다. 사람 정답 검수는 사용자 요청에 따라 미실시; 정답률을 계산하지 않는다.

최종 회귀:236개 중235통과·DB1스킵. 신규6개는 미지원 품목 원문 보존, 품목 불명, 품목 유사성, 로고만 모르는 확정 품목 유지, 부정된 미지원 품목, blanket 검토 해제 후에도 제약 유지 검사다. 코드·보고서는 미커밋·미푸시다.
