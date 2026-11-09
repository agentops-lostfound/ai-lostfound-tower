"""WSL installer for the prepared overlay. Default is a read-only preflight.

Requires an idle Studio and the device paths required by its container before
--apply or --rollback. Never connects or commands a robot. Keeps a complete UI
and changed backend backup, including a record of previously absent files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

CONTAINER = "physical-ai-studio-cuda"
BACKEND = "/app/application/backend/src"
UI = "/app/application/ui/dist"
REVISION = "e5dd66a38cf1e682fdead3ca0fefa60f5bf3459d"


def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True)


def docker(*args, check=True):
    return run("docker", *args, check=check)


def sessions():
    with urllib.request.urlopen("http://localhost:7860/api/runtime/sessions", timeout=5) as response:
        return json.load(response)


def preflight(bundle, mutate=False):
    manifest = json.loads((bundle / "bundle.json").read_text())
    for name, digest in manifest["files"].items():
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("Bundle integrity check failed: " + name)
    info = json.loads(docker("inspect", CONTAINER).stdout)[0]
    if info["Config"]["Labels"].get("org.opencontainers.image.revision") != REVISION:
        raise RuntimeError("Studio version changed; rebuild and re-test the overlay")
    active = sessions()
    missing = [item["PathOnHost"] for item in info["HostConfig"].get("Devices", []) if not Path(item["PathOnHost"]).exists()]
    print(json.dumps({"bundle_verified": True, "runtime_sessions": len(active), "missing_restart_devices": missing}, indent=2))
    if mutate and (active or missing):
        raise RuntimeError("Installation requires no runtime sessions and all container USB devices available")
    return manifest


def backup_and_apply(bundle, manifest):
    # Refuse to overwrite later local edits since the inspected v4 snapshot.
    for name, digest in manifest["original_backend"].items():
        actual = docker("exec", CONTAINER, "sha256sum", BACKEND + "/" + name).stdout.split()[0]
        if actual != digest:
            raise RuntimeError("Installed source changed: " + name)
    backup = bundle.parent / ("backup-" + time.strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(exist_ok=False)
    docker("cp", CONTAINER + ":" + UI, str(backup / "dist"))
    absent = []
    for file in manifest["backend_files"]:
        path = BACKEND + "/" + file
        if docker("exec", CONTAINER, "test", "-f", path, check=False).returncode:
            absent.append(file)
            continue
        dest = backup / "backend" / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        docker("cp", CONTAINER + ":" + path, str(dest))
    (backup / "backup.json").write_text(json.dumps({"absent": absent, "backend_files": manifest["backend_files"]}, indent=2))
    print("Backup:", backup, flush=True)
    try:
        for name in manifest["backend_files"]:
            docker("cp", str(bundle / "backend" / name), CONTAINER + ":" + BACKEND + "/" + name)
        # Keep old hashed assets, so already-open tabs still resolve their files.
        docker("cp", str(bundle / "dist") + "/.", CONTAINER + ":" + UI + "/")
        restart_and_check()
    except Exception:
        restore(backup)
        raise


def restart_and_check():
    docker("restart", CONTAINER)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            sessions()
            print("Studio is healthy. No robot connection or movement was requested.")
            return
        except (OSError, ValueError):
            time.sleep(1)
    raise RuntimeError("Studio did not become healthy within 60 seconds")


def restore(backup):
    meta = json.loads((backup / "backup.json").read_text())
    # Validate recorded relative paths before any removal inside the container.
    for name in meta["backend_files"]:
        if Path(name).is_absolute() or ".." in Path(name).parts or not name.startswith(("runtime/", "api/")):
            raise RuntimeError("Invalid backup path")
        if name in meta["absent"]:
            docker("exec", "-u", "root", CONTAINER, "rm", "-f", "--", BACKEND + "/" + name)
        else:
            docker("cp", str(backup / "backend" / name), CONTAINER + ":" + BACKEND + "/" + name)
    docker("cp", str(backup / "dist") + "/.", CONTAINER + ":" + UI + "/")
    restart_and_check()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    manifest = preflight(args.bundle, mutate=args.apply or args.rollback is not None)
    if args.apply:
        backup_and_apply(args.bundle, manifest)
    elif args.rollback:
        restore(args.rollback)
    else:
        print("Read-only preflight complete. Use --apply only when ready to restart idle Studio.")


if __name__ == "__main__":
    main()
