"""Hugging Face Hub 비공개 저장소로 데이터셋·모델을 올리고 받는 도구.

한줄 설명: 교육원 PC(수집·시연)와 집 PC(학습)가 같은 파일을 주고받는 공용 창고.

사용법
    # 올리기 (폴더 통째로)
    python tools/hub_sync.py upload  --kind data  --local datasets/vision_v1103 --path vision_v1103
    python tools/hub_sync.py upload  --kind model --local models/yolo26n_v1103   --path yolo26n_v1103
    # 받기
    python tools/hub_sync.py download --kind data  --path vision_v1103  --local datasets/vision_v1103
    python tools/hub_sync.py download --kind model --path yolo26n_v1103 --local models/yolo26n_v1103

설정(.env)
    HF_TOKEN=          # Hugging Face 쓰기 토큰(비밀값)
    HF_DATA_REPO=agentops-lostfound/lf-vision-data
    HF_MODEL_REPO=agentops-lostfound/lf-vision-models

- 저장소가 없으면 비공개(private)로 만든다.
- --dry-run 이면 무엇을 할지만 출력하고 아무것도 보내지 않는다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.envfile import load_env  # noqa: E402

KIND_TO = {
    "data": ("HF_DATA_REPO", "dataset"),
    "model": ("HF_MODEL_REPO", "model"),
}


def resolve_repo(kind: str) -> tuple[str, str]:
    env_key, repo_type = KIND_TO[kind]
    repo_id = os.environ.get(env_key, "").strip()
    if not repo_id or "/" not in repo_id:
        raise SystemExit(f"[hub] .env 의 {env_key} 를 '조직/저장소' 형식으로 채워 주세요")
    return repo_id, repo_type


def check_path(path: str) -> str:
    clean = path.strip().strip("/")
    if not clean or ".." in Path(clean).parts:
        raise SystemExit("[hub] --path 는 비어 있거나 '..' 을 포함하면 안 됩니다")
    return clean


def upload(kind: str, local: Path, path: str, dry_run: bool) -> None:
    repo_id, repo_type = resolve_repo(kind)
    path = check_path(path)
    if not local.is_dir():
        raise SystemExit(f"[hub] 올릴 폴더가 없습니다: {local}")
    files = [p for p in local.rglob("*") if p.is_file()]
    size_mb = sum(p.stat().st_size for p in files) / 1_048_576
    print(f"[hub] 올리기: {local} → {repo_type}:{repo_id}/{path} ({len(files)}개, {size_mb:.1f}MB)")
    if dry_run:
        return
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(repo_id, repo_type=repo_type, private=True, exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        repo_type=repo_type,
        folder_path=str(local),
        path_in_repo=path,
        commit_message=f"{path} 업로드",
    )
    print("[hub] 올리기 완료")


def download(kind: str, path: str, local: Path, dry_run: bool) -> None:
    repo_id, repo_type = resolve_repo(kind)
    path = check_path(path)
    print(f"[hub] 받기: {repo_type}:{repo_id}/{path} → {local}")
    if dry_run:
        return
    from huggingface_hub import snapshot_download

    tmp = snapshot_download(repo_id=repo_id, repo_type=repo_type, allow_patterns=[f"{path}/*", f"{path}/**"])
    src = Path(tmp) / path
    if not src.is_dir():
        raise SystemExit(f"[hub] 저장소에 {path} 폴더가 없습니다")
    import shutil

    local.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, local, dirs_exist_ok=True)
    print("[hub] 받기 완료")


def main(argv: list[str] | None = None) -> int:
    load_env()
    ap = argparse.ArgumentParser(description="Hugging Face Hub 비공개 저장소 올리기·받기")
    ap.add_argument("action", choices=["upload", "download"])
    ap.add_argument("--kind", choices=list(KIND_TO), required=True, help="data(데이터셋) 또는 model(모델)")
    ap.add_argument("--local", type=Path, required=True, help="내 PC 폴더")
    ap.add_argument("--path", required=True, help="저장소 안 폴더 이름(예: vision_v1103)")
    ap.add_argument("--dry-run", action="store_true", help="보내지 않고 할 일만 출력")
    a = ap.parse_args(argv)
    if a.action == "upload":
        upload(a.kind, a.local, a.path, a.dry_run)
    else:
        download(a.kind, a.path, a.local, a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
