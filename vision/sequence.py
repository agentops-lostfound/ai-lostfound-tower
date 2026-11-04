"""Single-image detection followed by an isolated Qwen process.

11/4 (변재원, 관제탑 연동):
- report["captured_at"]: 사진을 찍은 시각(ISO 8601 + 시간대). 관제탑은 이 값으로 결과 나이를 센다(분석 45~76초만큼 저장 시각보다 정확)
  기본값 = 입력 사진 파일의 수정 시각(카메라로 찍어 저장한 시각). 촬영 프로그램이 정확한 시각을 알면 captured_at= 으로 넘긴다
- Qwen 실행 전에 GPU 사용권("qwen")을 받는다(agents/gpu_lease.py, docs/design/gpu_lease.md). 못 받으면 Qwen 을 띄우지 않고 failed
  기다리는 최대 초: 환경값 QWEN_GPU_WAIT(기본 120). QWEN_GPU_LEASE=0 이면 사용권을 쓰지 않음
"""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from .vision_pipeline import run_image


def write_report(path, report):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _run_qwen(command, *, report_path, **kwargs):
    started = perf_counter()
    with subprocess.Popen(command, **kwargs) as process:
        try:
            while True:
                try:
                    return subprocess.CompletedProcess(command, process.wait(timeout=5))
                except subprocess.TimeoutExpired:
                    progress = json.loads(Path(report_path).read_text(encoding="utf-8"))
                    done = sum(o["qwen"]["status"] != "pending" for o in progress["objects"])
                    print(f'[Qwen] loading/analyzing; {done}/{len(progress["objects"])} crops finished; '
                          f'{perf_counter()-started:.0f}s elapsed', flush=True)
        except KeyboardInterrupt:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise


def captured_at_of(image, captured_at=None):
    """촬영 시각 문자열. 넘긴 값이 있으면 그대로(시간대 없는 값은 PC 시간대를 붙임), 없으면 사진 파일 수정 시각."""
    if isinstance(captured_at, datetime):
        dt = captured_at
    elif isinstance(captured_at, str) and captured_at.strip():
        dt = datetime.fromisoformat(captured_at.strip().replace("Z", "+00:00"))
    else:
        try:
            dt = datetime.fromtimestamp(Path(image).stat().st_mtime)
        except OSError:
            dt = datetime.now()
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="seconds")


def _gpu_lease():
    """GPU 사용권(없거나 꺼져 있으면 None). 저장소 루트의 agents/gpu_lease.py 를 쓴다."""
    if str(os.environ.get("QWEN_GPU_LEASE") or "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from agents.gpu_lease import gpu_lease
    try:
        wait = float(os.environ.get("QWEN_GPU_WAIT") or 120)
    except ValueError:
        wait = 120.0
    return gpu_lease("qwen", wait=wait)


def run_sequence(image, qwen_root, qwen_python, config=None, device="cpu", site_packages=None, cache_dir=None,
                 captured_at=None):
    qwen_root, qwen_python = Path(qwen_root).resolve(), Path(qwen_python).resolve()
    if not (qwen_root / "src/feature_extractor.py").is_file():
        raise FileNotFoundError(f"Qwen source not found: {qwen_root}")
    if not qwen_python.is_file():
        raise FileNotFoundError(f"Qwen Python not found: {qwen_python}")
    if site_packages and not Path(site_packages).is_dir():
        raise FileNotFoundError(f"Qwen site-packages not found: {site_packages}")
    started = perf_counter()
    print("[1/3] YOLO detection and crop saving...", flush=True)
    report, detection_path = run_image(image, config, device)
    report["captured_at"] = captured_at_of(image, captured_at)
    print(f"[1/3] {len(report['objects'])} crops saved: {detection_path.parent}", flush=True)
    report["detection_result_path"] = str(detection_path)
    report["sequence"] = {"status": "running", "visual_accuracy_verified": False,
                          "qwen_schema": "general_items_v1",
                          "detection_seconds": perf_counter()-started}
    for obj in report["objects"]:
        obj["qwen"] = {"status": "pending", "features": None}
    target = detection_path.parent / "result_with_qwen.json"
    if not report["objects"]:
        report["sequence"].update(status="no_detections", total_seconds=perf_counter()-started)
        write_report(target, report)
        return report, target
    write_report(target, report)
    log = detection_path.parent / "qwen_process.log"
    command = [str(qwen_python), "-u", str(Path(__file__).with_name("qwen_worker.py")),
               "--qwen-root", str(qwen_root), "--report", str(target)]
    if site_packages:
        command += ["--site-packages", str(Path(site_packages).resolve())]
    if cache_dir:
        command += ["--cache-dir", str(Path(cache_dir).resolve())]
    env = dict(os.environ, HF_HUB_OFFLINE="1", PYTHONIOENCODING="utf-8")
    print(f"[2/3] Starting Qwen. Initial loading may take a minute. Log: {log}", flush=True)
    cancelled, process_error = False, None
    lease = None
    try:
        lease = _gpu_lease()
        if lease is not None:
            lease.acquire()          # STT·VLA 가 GPU 를 쓰는 중이면 기다린다(GpuBusy 면 아래 except)
        with log.open("w", encoding="utf-8") as stream:
            result = _run_qwen(command, report_path=target, cwd=qwen_root, env=env,
                               stdout=stream, stderr=subprocess.STDOUT)
        returncode = result.returncode
    except KeyboardInterrupt:
        cancelled, returncode = True, 130
        print("Qwen cancelled; saving partial results.", flush=True)
    except OSError as error:
        returncode, process_error = 1, str(error)
    except Exception as error:     # GpuBusy 등: Qwen 을 띄우지 않음
        if type(error).__name__ != "GpuBusy":
            raise
        returncode, process_error = 1, f"GPU 사용권을 받지 못함: {error}"
        print(f"[2/3] {process_error}", flush=True)
    finally:
        if lease is not None:
            lease.release()          # Qwen 프로세스가 끝났으므로(메모리 해제) 사용권 반납
    report = json.loads(target.read_text(encoding="utf-8"))
    if returncode:
        for obj in report["objects"]:
            if obj["qwen"]["status"] == "pending":
                obj["qwen"] = {"status": "cancelled" if cancelled else "failed", "features": None,
                               "error": process_error or f"Qwen process exited {returncode}; see {log}"}
    failed = sum(obj["qwen"]["status"] != "ok" for obj in report["objects"])
    report["sequence"].update(status="cancelled" if cancelled else ("failed" if failed or returncode else "complete"),
                              qwen_failed=failed, qwen_process_log=str(log),
                              total_seconds=perf_counter()-started)
    write_report(target, report)
    print(f"[3/3] {report['sequence']['status']}: {target}", flush=True)
    return report, target
