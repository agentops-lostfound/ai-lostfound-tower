"""Single-image detection followed by an isolated Qwen process."""
import json
import os
from pathlib import Path
import subprocess
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


def run_sequence(image, qwen_root, qwen_python, config=None, device="cpu", site_packages=None, cache_dir=None):
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
    try:
        with log.open("w", encoding="utf-8") as stream:
            result = _run_qwen(command, report_path=target, cwd=qwen_root, env=env,
                               stdout=stream, stderr=subprocess.STDOUT)
        returncode = result.returncode
    except KeyboardInterrupt:
        cancelled, returncode = True, 130
        print("Qwen cancelled; saving partial results.", flush=True)
    except OSError as error:
        returncode, process_error = 1, str(error)
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
