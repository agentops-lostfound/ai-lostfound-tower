# 통합 검사 실행기

`run_pipeline.py`는 사진/기존 결과와 한국어 텍스트/음성 파일을 하나의 결과로 연결한다.

흐름: 음성 선택 시 독립 STT 프로세스 종료 → 사진 선택 시 YOLO·ArUco·Qwen → 통합 Adapter로 객체 확인 → 한국어 선추출·OPUS 구절 번역 → 원본 Qwen 특징으로 HybridMatcher → 후보 최대3개와 특징·좌표 저장.

기존 JSON으로 빠르게 확인(team-repo에서 실행):

```powershell
$env:PYTHONIOENCODING='utf-8'
& ..\.venv-query\Scripts\python.exe -u run_pipeline.py `
  --vision-report outputs/vision/65dceab24867491f996f6bad1152caaa/result_with_qwen.json `
  --query-file matching/configs/pipeline_query.txt
```

새 사진은 `--vision-report` 대신 `--image "C:\경로\사진.jpg"`를 사용한다. `--device cpu`는 YOLO 설정이다. Qwen은 기존 격리 GPU 프로세스로 실행하며 GPU 사용권 규칙을 유지한다.

텍스트는 `--query-file` 대신 `--text "검정색 지갑을 찾습니다"`로도 넣는다. 음성은 `--audio "C:\경로\음성.m4a"`로 대체한다. 별도 .venv-speech가 필요하며 STT 로그·전사본을 결과 폴더에 저장한다. 전사문은 미확인 상태이고 자동 반환하지 않는다. 설치 경로가 다르면 `--speech-python`, `--cuda-lib-dir`, `--qwen-python`, `--qwen-site-packages`, `--qwen-cache-dir`를 지정한다.

출력: `outputs/pipeline/<실행ID>/result.json`, `REPORT.md`. `--output-dir`로 폴더를 지정할 수 있다. 로컬 결과에는 비공개 특징·원문이 포함될 수 있어 그대로 공개하지 않는다. Git에서는 outputs가 제외된다.

원래 엔진 점수 판정, 질의 제약 적용 판정, 최종 검토 판정, 관제탑 검사 전용 판정을 분리한다. inspection_complete는 소프트웨어 실행 완료이며 인식 정답이나 수령 승인이 아니다. 후보의 center_mm은 종이 좌표이고 로봇 좌표가 아니다. 재사용한 과거 사진은 현재 장면으로 간주하지 않으며 이 실행기는 로봇·DB·알림을 호출하지 않는다. 작업대→로봇 변환·안전 접근·직원 확인 UI·실제 집기는 후속 통합 범위다.

오류·취소도 결과에 기록한다. 종료 코드0은 검사 완료,2는 비전 불완전,1은 실행 오류,130은 취소다. 비전 모듈이 이미 저장한 부분 결과는 유지한다. 이번 단계에서는 음성 확인 UI 없이 검사만 진행한다.

## 2026-11-04 실행 확인

| 경로 | 결과 | 전체 시간 | 출력 폴더(outputs/pipeline 아래) |
|---|---|---:|---|
| 기존 비전 JSON + 한국어 파일 | inspection_complete | 4.55초 | first_integration |
| 사진부터 새 추론 + 한국어 파일 | inspection_complete | 36.10초 | photo_integration |
| 실제 Music/3.m4a STT + 기존 비전 JSON | inspection_complete | 10.49초 | audio_integration |

사진은 WIN_20261104_16_00_26_Pro.jpg, 재사용 결과는65dceab24867491f996f6bad1152caaa다. 새 사진 실행의 비전 결과는90db8c8234a44250b05d9def58a44ad2에 저장됐다. 후보2개와 mm좌표 (229.8,118.1)/(93.2,115.9)가 통합 결과에 전달됐다.

“검은색 휴대폰인데 뒷면에 카드가 꽂혀 있어요”는 현재 Parser가 카드 구절을 자유 특징으로 추출하지 않아 free_text가 비었고 두 후보가1.0 동점으로 보류됐다. 보조배터리의 phone 오분류도 남아 있다. 음성3번은 포켓몬 스티커 폰 설명이며 이번 장면과 정답이 일치하는 시험이 아니다. OPUS는 pocket sticker로 번역했고 점수 약.50으로 보류됐다. 이 실행은 입력·전처리·매칭 연결 시험이며 검색 정확도 증명이 아니다. 음성→새사진 조합은 같은 실행기에서 지원하나 이번에는 단계별 두 경로로 검사했다.

회귀 테스트240개 중239통과·DB1스킵. 새 테스트는 실제 Adapter와 브리지 경유 좌표 보존·직원 검토 유지, 불완전 장면 후보 차단을 확인한다. 로봇·DB 호출 및 커밋·푸시는 하지 않았다.
