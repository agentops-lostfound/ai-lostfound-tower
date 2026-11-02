# Windows PC 개발 환경 설치 (교육원 PC · 집 PC 공통)

## 1. 준비물 확인 (PowerShell)
```
python --version; git --version; nvidia-smi
```
- Python 3.11 이상, git, NVIDIA 드라이버가 보이면 된다.

## 2. 저장소 받기
```
mkdir C:\git -Force; cd C:\git
git clone https://github.com/agentops-lostfound/ai-lostfound-tower.git
cd ai-lostfound-tower
```

## 3. 가상환경 만들고 패키지 설치
```
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r vision/requirements.txt
```
- `Activate.ps1`이 막히면: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` → `Y`
- torch 줄의 `cu128`은 CUDA 12.8용(추정). 설치 후 아래가 `True`면 GPU를 쓰는 것이다.
```
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## 4. 버전 맞추기 (교육원 PC가 기준)
- 교육원 PC에서 설치가 끝나면 정확한 버전을 기록해 올린다.
```
pip freeze > requirements-lock.txt
```
- 집 PC는 이 파일로 설치해 두 PC의 버전을 똑같이 맞춘다.
```
pip install -r requirements-lock.txt
```

## 5. 비밀값 설정
```
copy .env.example .env
notepad .env
```
- `DISCORD_WEBHOOK_URL`: 디스코드 채널 → 연동 → 웹후크 → URL 복사
- `HF_TOKEN`: huggingface.co → Settings → Access Tokens → Write 토큰
- `.env`는 절대 커밋하지 않는다(.gitignore에 들어 있음).

## 6. 동작 확인
```
python -m unittest discover -s tests
python tools/notify.py "환경 확인" "내 PC 설치 완료"
yolo version
```
