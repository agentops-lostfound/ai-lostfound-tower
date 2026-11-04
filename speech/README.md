# 독립 한국어 음성 입력

음성 파일 또는 명시적으로 녹음한 마이크 음성을 한국어 텍스트로 반환한다. faster-whisper 1.2.1을 사용하며 기본 모델은 large-v3-turbo, 기본 실행은 CUDA int8_float16이다. CPU 비교용으로 multilingual small + int8을 선택할 수 있다. 모든 경로는 language=ko, task=transcribe를 사용하며 영어로 번역하지 않는다.

## 역할과 연결

```text
마이크/음성 파일 → speech → 한국어 전사문
                               ↓ 메인에서 확인·수정
타이핑 입력 ──────────────→ matching 한국어 전처리 → 후보 비교
```

speech는 matching·vision·DB를 import하지 않는다. 메인이 입력 선택과 확인 화면을 제공하고, 확인된 한국어 문장만 매칭으로 전달한다. 실시간 스트리밍·화자 분리·확인 UI·로봇 동작은 이 모듈의 구현 범위에 포함하지 않는다.

## 별도 환경

저장소 루트, Python 3.11 기준:

```powershell
python -m venv ..\.venv-speech
& ..\.venv-speech\Scripts\python.exe -m pip install -r speech/requirements.txt
```

현재 PC에는 이 별도 환경을 구성했다. 기존 .venv-vision, .venv-query, 외부 Qwen 환경은 변경하지 않는다. 기본 faster-whisper 모델 이름의 CTranslate2 변환 가중치를 다운로드해 .cache/speech에 보관한다. 최초 다운로드에는 네트워크가 필요하며 이후 --offline을 사용할 수 있다. 모델 파일 upstream revision은 현재 고정하지 않았다.

## 파일 전사

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& ..\.venv-speech\Scripts\python.exe -u -m speech.transcribe `
  --audio outputs/speech/input.wav `
  --cuda-lib-dir ..\qwen\.venv\Lib\site-packages\torch\lib
```

Windows GPU 실행에는 CUDA 12용 cuBLAS·cuDNN 9 DLL이 필요하다. 현재 PC에는 외부 Qwen 환경의 torch/lib에 DLL이 있어 해당 디렉터리를 프로세스에서만 참조한다. PyTorch CUDA가 동작한다는 사실만으로 CTranslate2의 DLL 탐색까지 자동 설정되지는 않는다. 다른 PC에서는 본인의 설치 경로를 지정한다. 시스템 PATH를 영구 변경하거나 다른 환경의 패키지를 설치하지 않는다.

GPU 실패 시 조용히 CPU로 바꾸지 않고 오류를 반환한다. CPU 전사는 명시적으로 선택한다.

```powershell
& ..\.venv-speech\Scripts\python.exe -m speech.transcribe `
  --audio outputs/speech/input.wav --model small --device cpu
```

--output-dir로 결과 폴더를 지정할 수 있다. 기본값은 outputs/speech/<고유ID>/이며 transcript.txt와 transcript.json을 저장한다. --beam-size, --threads, --no-vad 옵션을 제공한다. VAD가 켜진 무음 입력에서 텍스트가 없으면 status=no_speech다. no_speech는 인식된 검색 요청이 아니므로 매칭으로 넘기지 않는다.

## 마이크 녹음

아래 명령을 직접 실행할 때만 마이크에 접근한다. 모델 생성·파일 전사에서는 마이크를 열지 않는다.

```powershell
& ..\.venv-speech\Scripts\python.exe -m speech.record --list-devices
& ..\.venv-speech\Scripts\python.exe -m speech.record --seconds 8 --output outputs/speech/input.wav
```

입력 장치가 여러 개면 --device 번호를 지정한다. 기본 16kHz·모노·PCM16 WAV로 저장하며 장치가 16kHz를 지원하지 않으면 --sample-rate 48000을 지정한다. 1~60초의 고정 길이 녹음이며 Ctrl+C 취소 시 새 파일을 저장하지 않는다. 기본 경로를 재사용하면 기존 파일을 덮어쓰므로 보존할 녹음은 다른 경로로 지정한다.

시작 문장 예: “검은색 카드지갑을 잃어버렸어요. 앞에 별 모양 스티커가 있어요.”

## 메인에서 사용할 함수

```python
from speech.transcriber import SpeechConfig, KoreanTranscriber

config = SpeechConfig()  # CUDA int8_float16
with KoreanTranscriber(config) as stt:
    report = stt.transcribe("recording.wav")
    if report["status"] == "transcribed":
        korean_text = report["text"]
        # 메인에서 사람이 확인·수정한 뒤 matching에 전달
```

반복 요청에는 같은 인스턴스를 재사용해 모델 로딩을 반복하지 않는다. GPU 라이브러리 경로는 SpeechConfig(cuda_lib_dirs=(... ,))로도 지정할 수 있다. Qwen과 6GB VRAM을 공유하므로 초기에는 순차 실행하고, STT 프로세스 종료 후 Qwen 프로세스를 시작하는 방식으로 자원 해제를 확인한다. 동시 상주 가능 여부와 VRAM 최대치는 실제로 측정해야 한다.

## 출력·검증 기준

현재 PC에서 turbo CUDA 전사를 실제 확인했습니다. 합성 한국어 6.15초를 약 1.39초에 기준 문장대로 전사했고, 2초 무음은 no_speech였습니다. 사람 발화 정확도는 아직 검증하지 않았습니다. [실행 기록·제한](../docs/reports/2026-11-04-speech-setup.md)을 참고하세요.

- text, 한국어 구간별 시작·종료 시간과 원문을 저장한다.
- requires_confirmation=true는 인식 문장 확인을 위한 인터페이스 표시이며 모델의 오류 탐지 결과가 아니다.
- avg_logprob/no_speech_prob는 디코더 지표이며 물품 매칭 확률이나 보정된 전사 정확도가 아니다.
- 모델 로딩, 전사(구간 generator 소비 포함), 음성 길이, VAD 후 길이, 실시간 비율을 분리해 기록한다.
- 색·품목·스티커·“없어요” 같은 핵심 단어와 부정을 실제 녹음으로 평가한다. 깨끗한 합성 음성 시험과 사람 음성 정확도를 구분한다.
- 녹음·결과·모델 가중치·캐시는 Git에서 제외한다. STT 호출 비용이 드는 외부 API는 사용하지 않는다.

공식 사용법·GPU 요구사항: [faster-whisper](https://github.com/SYSTRAN/faster-whisper). 원본 turbo 모델: [Whisper large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo). faster-whisper와 원본 Whisper는 MIT 라이선스이며 실제 배포하는 변환 모델·종속성의 고지도 함께 확인한다.
