# 건태 로컬 비전 소스 보존본

2026-11-13 로봇 PC 정리 시 Git 저장소 밖에 남아 있던 소스 49개를 보존했다.
이 디렉터리는 과거 독립 모듈의 보존본이며, 현재 관제탑의 기본 실행 경로나 배포 구성에는 연결하지 않았다.
원본 README와 검증 기록의 날짜·설명을 유지했으므로, 당시 결과와 현재 운영 기능을 구분해서 읽는다.

## 구성

- `vision_pipeline.py`, `yolo/`, `aruco/`, `configs/`, `scripts/`: 독립 검출·크롭·마커 좌표 보정 실험.
- `qwen/`: Qwen 사진 특징 추출, 실패 처리, SmolVLM 비교 실험 및 모의 테스트.
- `requirements*.txt`: 당시 설치 요구 사항 및 버전 목록. 새 PC에서는 독립 가상환경을 만든다.
- `source-manifest.json`: 보존한 원본 파일의 SHA-256. `ARCHIVE_README.md`는 이번에 작성한 안내이므로 원본 목록에 포함하지 않았다.

SmolVLM은 영상·언어 모델이며, 삭제한 로봇 행동 모델 SmolVLA와 다르다. 여기에는 어느 쪽의 가중치도 포함하지 않았다.
모델·사진·영상·실제 `.env`·토큰·가상환경·머신별 에디터 설정은 제외했다.

## 독립 테스트

이 폴더를 작업 디렉터리로 두고 설치한 환경의 Python으로 실행한다.

```powershell
$env:PYTHONUTF8 = '1'
python -m unittest discover -s tests -v
Set-Location qwen
python -m pytest tests -q
```

2026-11-13 보존본에서 비전 unittest 4개와 Qwen pytest 31개가 통과했다.
Qwen 검증은 가짜 추론을 사용하는 단위 테스트다. GPU 추론·카메라 재연결·실물 로봇 동작을 새로 검증한 결과가 아니다.

로봇 및 대용량 자료 복구 위치는 [로컬 보존 인수인계](../../docs/handoff/2026-11-13-local-preservation.md)를 참고한다.
