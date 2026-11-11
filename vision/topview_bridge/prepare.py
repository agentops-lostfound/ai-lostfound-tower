"""준비된 ZIP 추출본과 모델을 격리 작업 폴더로 복사 (다운로드/패키지 변경 없음)."""
import argparse
import json
import subprocess
from pathlib import Path


def wsl_path(path):
    path = Path(path).resolve()
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:] if path.drive else str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--locator-root", required=True)
    parser.add_argument("--models", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf8"))
    locator = Path(args.locator_root).resolve()
    models = Path(args.models).resolve()
    if not (locator / "locate_objects.py").is_file():
        raise ValueError("locator 추출본이 필요합니다.")
    names = ("owlv2-base-patch16-ensemble", "siglip2-base-patch16-224")
    for name in names:
        if not (models / name / "model.safetensors").is_file():
            raise ValueError(f"준비되지 않은 모델: {name}")
    prefix = ["wsl", "-d", config.get("wsl_distribution", "Ubuntu-24.04"), "--", "docker"]
    container = config.get("container", "physical-ai-studio-cuda")
    root = config.get("container_root", "/tmp/lf-topview-bridge")
    subprocess.run(prefix + ["exec", container, "mkdir", "-p", f"{root}/locator"], check=True)
    subprocess.run(prefix + ["cp", wsl_path(locator) + "/.", f"{container}:{root}/locator"], check=True)
    for name in names:
        dest = f"{root}/models/{name}"
        subprocess.run(prefix + ["exec", container, "mkdir", "-p", dest], check=True)
        for file in (models / name).iterdir():
            if file.is_file() and file.suffix in {".safetensors", ".json", ".txt", ".model", ".jinja"}:
                subprocess.run(prefix + ["cp", wsl_path(file), f"{container}:{dest}/{file.name}"], check=True)
    print("탑뷰 로컬 추론 파일 준비 완료")


if __name__ == "__main__":
    main()
