# 독립 한국어 STT 모듈 구현 및 실행 확인

실행일: 2026-11-04. 메인에서 음성 입력을 붙일 수 있도록 speech 모듈을 matching과 분리해 구현했다. 현재 메인 UI·자동 매칭은 연결하지 않았다.

## 구현

- KoreanTranscriber.transcribe(audio_path): 한국어 텍스트·구간 시간·실행 설정·시간 반환.
- CLI: 음성 파일 → transcript.txt / transcript.json 저장.
- 별도 마이크 녹음 CLI: 장치 목록, 명시적 1~60초 녹음, 모노 PCM16 WAV 저장.
- 기본 large-v3-turbo / CUDA int8_float16, CPU 비교 옵션 small / int8.
- language=ko, task=transcribe, VAD 기본 사용. 영어 번역을 수행하지 않는다.
- requires_confirmation 표시로 메인에서 인식 문장 확인·수정 후 매칭에 넘기도록 인터페이스를 준비했다.
- 별도 .venv-speech 환경을 만들었으며 비전·번역·외부 Qwen 환경은 변경하지 않았다.

## 실제 실행 확인

실제 사람 녹음 파일은 없어, Windows Microsoft Heami Desktop으로 생성한 한국어 합성 음성과 무음을 사용했다. 마이크 장치 목록에서 USB Microphone은 확인했으나 마이크 녹음은 실행하지 않았다.

| 입력 | 출력 | 모델 로딩 | 전사 시간 |
|---|---|---:|---:|
| 한국어 합성 음성 6.15초 | 기준 문장과 같은 한국어 텍스트 | 3.18초 | 1.39초 |
| 무음 2초 | no_speech, 빈 텍스트 | 2.87초 | 0.085초 |

기준 및 실제 전사 문장:

> 검은색 카드지갑을 잃어버렸어요. 앞에 별 모양 스티커가 있어요.

Whisper large-v3-turbo, faster-whisper 1.2.1, CTranslate2 4.8.5, CUDA int8_float16, beam 5, VAD 사용으로 실행했다. 장비는 기존 RTX 3050 6GB다. CUDA 라이브러리는 기존 외부 Qwen 환경의 torch/lib 디렉터리를 해당 프로세스에서 참조했다. Qwen 비전 모델과 동시에 상주시킨 실험은 아니다.

첫 모델 다운로드가 자동 전송 방식에서 정체돼 공개 모델 파일을 직접 전송하고 크기(1,617,884,929 bytes)와 SHA256을 확인했다. 이후 완전한 로컬 캐시를 사용해 --offline 전사를 확인했다. 위 로딩 시간에는 다운로드를 포함하지 않으며, 전사 시간은 오디오 디코딩·VAD·구간 generator 소비를 포함하고 출력 저장은 제외한다.

합성 음성 한 문장 일치는 실제 사용자 발화 정확도나 벤치마크 CER을 입증하지 않는다. CPU small, 실시간 스트리밍, 사람 발화 20개, 소음 환경, 동시 GPU 사용과 최대 VRAM은 아직 평가하지 않았다.

## 재현·다음 시험

실행 명령은 [speech/README.md](../../speech/README.md)에 있다. 현재 설치 환경의 버전 목록은 [Windows lock 파일](../../speech/requirements-lock.windows.txt)에 보존했다. 원본 합성 WAV·실행 JSON은 outputs/speech에 두고 Git에서 제외한다.

실제 마이크로 같은 문장을 녹음한 뒤, 색·품목·스티커·부정 표현이 유지되는지 확인한다. 예를 들어 “스티커가 있어요/없어요”, “파란색 아니고 검정색”을 구분해 평가한다. 메인은 확정된 text만 기존 한국어 특징 추출로 넘기며 STT가 물품을 직접 선택하거나 로봇을 호출하지 않는다.
