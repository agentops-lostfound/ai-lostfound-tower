@echo off
rem 11/10 One-step setup of the Qwen environment (.venv-qwen) used by tools\intake_qwen_worker.py (kiosk photo analysis).
rem Run in the repository folder:  tools\setup_qwen.bat      Safe to run again: finished steps are quick the second time.
rem First run downloads about 6-8 GB (PyTorch CUDA build + Qwen3-VL-2B weights into qwen\.cache). Needs an NVIDIA GPU.
setlocal
cd /d "%~dp0.."
echo [setup_qwen] Qwen environment for kiosk photo analysis. First run downloads about 6-8 GB.
if exist .venv-qwen\Scripts\python.exe goto have_venv
set PYCMD=
py -3.11 -c "print(1)" >nul 2>nul && set PYCMD=py -3.11
if not defined PYCMD py -3.12 -c "print(1)" >nul 2>nul && set PYCMD=py -3.12
if not defined PYCMD py -3.13 -c "print(1)" >nul 2>nul && set PYCMD=py -3.13
if not defined PYCMD python -c "import sys; raise SystemExit(0 if (3,11)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul && set PYCMD=python
if not defined PYCMD echo [FAIL] Python 3.11 - 3.13 not found. Install Python first.
if not defined PYCMD goto fail
echo [1/4] Create .venv-qwen  (%PYCMD%)
%PYCMD% -m venv .venv-qwen
if errorlevel 1 goto fail
:have_venv
.venv-qwen\Scripts\python.exe --version
echo [2/4] Install packages (PyTorch CUDA build, about 3 GB the first time)
.venv-qwen\Scripts\python.exe -m pip install --upgrade pip
.venv-qwen\Scripts\python.exe -m pip install -r qwen\requirements.txt
if errorlevel 1 goto fail
echo [3/4] GPU check + model download (Qwen3-VL-2B, about 4 GB the first time)
pushd qwen
..\.venv-qwen\Scripts\python.exe -m scripts.check_environment --load-model
set QWEN_RC=%ERRORLEVEL%
popd
if not "%QWEN_RC%"=="0" goto fail
echo [4/4] Tower connection check (the tower must be running: tools\start_tower.bat)
.venv-qwen\Scripts\python.exe tools\intake_qwen_worker.py --check
echo.
echo [OK] Qwen environment is ready. Start the worker with:
echo      .\.venv-qwen\Scripts\python.exe tools\intake_qwen_worker.py
goto end
:fail
echo.
echo [FAIL] Setup stopped. Copy the messages above and share them.
:end
pause
