# 번역 모델 교체 비교: Qwen3-0.6B → OPUS-MT ko-en

2026-11-03. 모델만 바꾸고 영어 규칙 추출, MiniLM, 판정 설정, 한국어 20문장, 기존 11개 후보 그룹(22개 특징 기록)을 유지했다. 모델별 220회 매칭 비교를 실행했다. 실행 도중 번역 문장을 수동 수정하거나 실패에 맞춰 규칙을 변경하지 않았다.

| 항목 | Qwen3-0.6B 범용 모델 | Helsinki-NLP/opus-mt-ko-en 번역 전용 모델 |
|---|---:|---:|
| 번역·추출 실행 완료 | 20/20 | 20/20 |
| category/colors/sticker_status 전체 일치 | 10/20 | 14/20 |
| 문장별 변환 중앙값 | 2.52초 | 0.51초 |
| 제한 전 정책 상태 | 선택 8·보류 6·일치 없음 6 | 선택 10·보류 8·일치 없음 2 |

두 모델 모두 CPU float32, 2 threads다. Qwen은 greedy 생성, OPUS-MT는 전용 모델의 빔 4 생성이다. 모델별 추론 방식은 다르므로 순수 파라미터 수 효과를 분리한 실험은 아니다. 변환 시간은 모델 로딩·다운로드·MiniLM·파일 저장을 제외한다. 선택 건수 증가가 정답률 증가를 의미하지 않는다. requires_review 제한은 모두 유지했다.

## 확인한 개선

- “검정색 아니고 흰색 아이폰”을 OPUS-MT가 not black / white로 보존해 색 조건 검사 통과. Qwen은 not bright yellow로 오역했다.
- “진한 파란색”을 dark blue로 보존했다. Qwen은 bright blue였다.
- “검정 USB, 빨간 테두리”의 두 색을 보존했다. Qwen은 검정을 분홍으로 바꾸거나 누락했다.
- “색이 기억나지 않는다”를 I don't remember color로 번역했다. Qwen의 It's not glowing 의미 변형이 사라졌다.
- “카메라 하나”를 one camera로 보존했다. Qwen은 a camera로만 표현했다.

## 남은 실패

- 남색·포켓몬 스티커를 dark cell phone / pocket sticker로 잘못 번역했다.
- 보조배터리를 side battery, VOVA를 VOA로 번역했다. 품목 추출이 unknown으로 남는다.
- “금이나 파손이 없다”의 금(균열)을 gold로 번역해 색 추출 코드가 금색으로 읽었다.
- 카드지갑을 card로 줄이거나, 남색인지 검정인지 모르는 지갑을 black or black으로 잘못 번역한 사례가 있다.
- 긴 구어체의 심한 파손이 full of crap으로 바뀌었다. 속성 검사 세 항목이 맞아도 자유 문장은 틀릴 수 있다.
- there's no sticker 같은 문장에서 전역에 등장한 side를 코드가 부정 범위로 보는 등 보수적인 규칙의 한계도 남아 있다.

따라서 새 모델은 이번 제한된 시험에서 속도와 조건 보존이 개선된 실험 기본값이다. 일반 번역 품질이나 실제 검색 정확도를 보장하지 않는다. 손상 유무 같은 자유 문장의 부정은 여전히 임베딩만으로 처리하므로 잘못된 선택 가능성이 남는다.

## 적용과 재현

통번역 데모의 기본 translator, --parse-korean의 기본 backend를 OPUS-MT로 변경했다. 기존 모델도 비교 옵션으로 유지하며 자동 확정 제한은 해제하지 않았다. 기존 Qwen/비전 환경은 변경하지 않았고 .venv-query에 SentencePiece·Sacremoses 의존성만 추가했다.

```powershell
& ..\.venv-query\Scripts\python.exe -u -m matching.evaluate_translation --translator opus --offline
```

기존 결과: outputs/matching/translation_20/REPORT.html. 새 결과: outputs/matching/translation_20_opus/REPORT.html. 둘 다 실제 번역·질문별 11그룹 후보 점수를 포함하고 모델별 별도 보존했다.

모델 출처: [공식 모델 페이지](https://huggingface.co/Helsinki-NLP/opus-mt-ko-en). 내려받은 해당 모델 카드에는 Apache-2.0으로 표시돼 있다. 다른 OPUS 프로젝트·모델 전체에 같은 라이선스를 일반화하지 않는다. upstream revision을 고정한 배포는 아니다.
