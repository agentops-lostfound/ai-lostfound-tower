"""기존 소유자 패치의 연결부만 진단 버전으로 교체. 장비 연결 없음."""
import argparse
import json
from pathlib import Path

try:
    from .manage_robot_owner_patch import (
        FILES, atomic_write, check, clear_bytecode, digest, read_backup, require_idle,
    )
except ImportError:
    from manage_robot_owner_patch import (
        FILES, atomic_write, check, clear_bytecode, digest, read_backup, require_idle,
    )

BRIDGE = "_lf_owner_bridge.py"


def upgrade(candidate, backup, bridge_file, output):
    require_idle()
    manifest, installed, status = check(candidate, Path(json.loads(
        (Path(backup) / "backup.json").read_text())["transport"]))
    if status != "ALREADY_INSTALLED":
        raise RuntimeError("기존 패치가 설치된 상태에서만 진단 연결부를 갱신합니다")
    transport = Path(json.loads((Path(backup) / "backup.json").read_text())["transport"])
    record, original, previous = read_backup(backup, transport)
    if previous != installed:
        raise RuntimeError("설치 후보와 기존 백업이 다릅니다")
    content = Path(bridge_file).read_bytes()
    compile(content, BRIDGE, "exec")
    if b"lf-pan-goal-readback-v1" not in content:
        raise RuntimeError("검토한 목표 읽기 진단 연결부가 아닙니다")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    new_candidate, new_backup = output / "candidate", output / "backup"
    new_candidate.mkdir()
    new_backup.mkdir()
    data = {**previous, BRIDGE: content}
    hashes = {name: digest(value) for name, value in data.items()}
    for name, value in data.items():
        (new_candidate / name).write_bytes(value)
        (new_backup / name).write_bytes(value)
    (new_candidate / "manifest.json").write_text(json.dumps({**manifest, "files": hashes}), encoding="utf-8")
    (new_backup / "original_owner.py").write_bytes(original)
    (new_backup / "backup.json").write_text(json.dumps({**record, "installed_hashes": hashes}), encoding="utf-8")
    read_backup(new_backup, transport)
    require_idle()
    if check(candidate, transport)[2] != "ALREADY_INSTALLED":
        raise RuntimeError("교체 직전 설치 상태 변경")
    try:
        atomic_write(transport / BRIDGE, content)
        clear_bytecode(transport)
        if check(new_candidate, transport)[2] != "ALREADY_INSTALLED":
            raise RuntimeError("진단 연결부 교체 후 검증 실패")
    except Exception:
        atomic_write(transport / BRIDGE, previous[BRIDGE])
        clear_bytecode(transport)
        raise
    return {"result": "TELEMETRY_UPGRADED_NO_HARDWARE_CONNECTION",
            "container_candidate": str(new_candidate), "container_backup": str(new_backup),
            "hardware_connected": False}


def undo(old_backup, new_candidate):
    require_idle()
    record = json.loads((Path(old_backup) / "backup.json").read_text())
    transport = Path(record["transport"])
    _, _, previous = read_backup(old_backup, transport)
    if check(new_candidate, transport)[2] != "ALREADY_INSTALLED":
        raise RuntimeError("알 수 없는 변경이 있어 이전 진단 연결부를 자동 복원하지 않습니다")
    atomic_write(transport / BRIDGE, previous[BRIDGE])
    clear_bytecode(transport)
    if any(digest((transport / name).read_bytes()) != record["installed_hashes"][name] for name in FILES):
        raise RuntimeError("이전 연결부 복원 검증 실패")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--bridge-file")
    parser.add_argument("--output")
    parser.add_argument("--undo", action="store_true")
    args = parser.parse_args()
    if args.undo:
        undo(args.backup, args.candidate)
        result = {"result": "PREVIOUS_BRIDGE_RESTORED"}
    else:
        if not args.bridge_file or not args.output:
            parser.error("--bridge-file 및 --output 필요")
        result = upgrade(args.candidate, args.backup, args.bridge_file, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
