"""Package already-tested artifacts and original hashes for a guarded install."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(stage):
    bundle = stage / "bundle"
    if bundle.exists():
        raise FileExistsError("Use a new package directory; do not silently overwrite an installation bundle")
    bundle.mkdir()
    shutil.copytree(stage / "backend", bundle / "backend")
    shutil.copytree(stage / "build/dist", bundle / "dist")
    backend_files = sorted(json.loads((stage / "backend/manifest.json").read_text()))
    originals = {}
    for name in backend_files:
        source = stage / "original/backend" / ("runtime_ws.py" if name == "api/runtime_ws.py" else name)
        if source.exists():
            originals[name] = digest(source)
    manifest = {
        "studio_revision": "e5dd66a38cf1e682fdead3ca0fefa60f5bf3459d",
        "status": "built_tested_not_installed",
        "backend_files": backend_files,
        "original_backend": originals,
        "files": {file.relative_to(bundle).as_posix(): digest(file) for file in sorted(bundle.rglob("*")) if file.is_file()},
    }
    (bundle / "bundle.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(bundle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    package(parser.parse_args().stage)
