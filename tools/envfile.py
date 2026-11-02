"""저장소 루트의 .env를 읽어 환경변수로 올리는 작은 도구 (외부 패키지 없이 동작).

한줄 설명: 비밀값을 코드에 쓰지 않고 .env 파일에서만 읽기 위한 공용 함수.
- 이미 환경변수에 값이 있으면 덮어쓰지 않는다(창에서 잠깐 바꾼 값이 우선).
- 형식: KEY=VALUE 한 줄씩, # 으로 시작하면 주석.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> dict[str, str]:
    """`.env`를 읽어 os.environ에 없는 키만 채우고, 읽은 값을 돌려준다."""
    env_path = path or REPO_ROOT / ".env"
    loaded: dict[str, str] = {}
    if not env_path.is_file():
        return loaded
    # utf-8-sig: 메모장이 붙이는 BOM이 있어도 첫 줄을 바르게 읽는다
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded
