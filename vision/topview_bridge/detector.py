"""설치된 로컬 Docker CUDA 환경에서 ZIP 모듈을 실행한다."""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from agents.gpu_lease import gpu_lease


def detect(jpeg, config, log_path):
    worker = Path(__file__).with_name("worker.py").resolve()
    # Docker cp accepts an ordinary Windows absolute source with the Windows CLI;
    # this workstation uses the WSL daemon, so translate only the source path.
    source = "/mnt/" + worker.drive[0].lower() + worker.as_posix()[2:] if worker.drive else str(worker)
    prefix = ["wsl", "-d", config.get("wsl_distribution", "Ubuntu-24.04"), "--", "docker"]
    container = config.get("container", "physical-ai-studio-cuda")
    root = config.get("container_root", "/tmp/lf-topview-bridge")
    subprocess.run(prefix + ["cp", source, f"{container}:{root}/worker.py"], check=True, capture_output=True, timeout=20)
    cmd = prefix + ["exec", "-i", "-e", f"HF_HUB_CACHE={root}/hf", "-e", "HF_HUB_OFFLINE=1",
                    container, "timeout", "--signal=KILL", "160s", "/app/application/backend/.venv/bin/python", "-u", f"{root}/worker.py",
                    "--locator-root", f"{root}/locator"]
    regions = config["regions"]
    width, height = config["image_size_px"]
    roi = [min(b[0] for b in regions.values()) / width, min(b[1] for b in regions.values()) / height,
           max(b[2] for b in regions.values()) / width, max(b[3] for b in regions.values()) / height]
    payload = json.dumps({"jpeg": base64.b64encode(jpeg).decode(), "roi": roi}) + "\n"
    # The timeout runs INSIDE Docker so the actual GPU process is killed before releasing the lease.
    with gpu_lease("test", wait=2):
        with Path(log_path).open("w", encoding="utf8") as error_log:
            result = subprocess.run(cmd, input=payload, capture_output=False, stdout=subprocess.PIPE,
                                    stderr=error_log, encoding="utf8", check=True)
    return json.loads(result.stdout)
