# 챗봇 모델 Ollama 설치 (관제탑 PC, 11/7 LF-5 변재원)

한줄 설명: 챗봇이 쓸 로컬 언어모델(11/7 결정: KT Mi:dm 2.0 Mini)을 Ollama 에 올리고 `.env` 의 `LF_CHAT_RAG_MODEL` 에 이름을 적는다(근거 `docs/design/chatbot_sllm_rag.md` §9).

**기본 순서: 1 → 2-B → 3.** 2-A(Qwen3-4B-2507)는 그래픽카드 여유가 3.3GB 이상으로 확인됐을 때만 쓰는 예비.

## 1. 그래픽카드 여유 확인(기록용 — 발표 질문 대비 실제 숫자)
Warp 터미널 `작업` 탭(저장소 폴더)에서, 관제탑과 Qwen 작업자(`tools/intake_qwen_worker.py`)를 켠 상태로:
```
nvidia-smi
```
- 표의 `Memory-Usage` 에서 `6144MiB` 중 남은 양 = 6144 − 사용량
- 남은 양 **3.3GB(약 3400MiB) 이상** → 2-A Qwen3-4B-2507 / **그보다 적으면** → 2-B Mi:dm 2.0 Mini
- 모니터가 RTX 3050 에 꽂혀 있으면 화면이 약 1GB 를 쓴다(아래 프로세스 목록에 `dwm.exe` 등)

## 2-A. (예비) Qwen3-4B-Instruct-2507 (Apache 2.0, Ollama 공식)
```
ollama pull qwen3:4b-instruct-2507-q4_K_M
```
`.env`: `LF_CHAT_RAG_MODEL=qwen3:4b-instruct-2507-q4_K_M`

## 2-B. (기본) KT Mi:dm 2.0 Mini (MIT)
Ollama 공식 목록에 없어서 GGUF 파일을 받아 등록 파일(`Modelfile.midm-2.0-mini`)로 올린다.
1. 파일 받기(약 1.43GB, 저장소의 `docs/ollama` 폴더로). PowerShell 5.1 에서 `curl` 은 다른 명령의 별명이라 반드시 `curl.exe`:
```
curl.exe -L -o docs\ollama\Midm-2.0-Mini-Instruct-Q4_K_M.gguf https://huggingface.co/mykor/Midm-2.0-Mini-Instruct-gguf/resolve/main/Midm-2.0-Mini-Instruct-Q4_K_M.gguf
```
2. 등록:
```
cd docs\ollama
ollama create midm-2.0-mini -f Modelfile.midm-2.0-mini
cd ..\..
```
3. `.env`: `LF_CHAT_RAG_MODEL=midm-2.0-mini`
- 크기 확인: `(Get-Item docs\ollama\Midm-2.0-Mini-Instruct-Q4_K_M.gguf).Length` → `1426272640`
- GGUF 파일은 커밋하지 않는다(`.gitignore` 의 `*.gguf`)
- 11/7 집 PC(Ollama 0.40.15)에서 `ollama create` 성공·한국어 응답 확인

## 3. 확인
```
python tools/chat_model_bench.py --models 위에서고른이름 --limit 10
```
- `모델 사용` 칸이 0 이면 모델이 꺼졌거나 이름이 틀린 것. 관제탑을 다시 켜야 `.env` 가 반영된다
