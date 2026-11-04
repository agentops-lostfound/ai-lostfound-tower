"""LF-12 소유자 패치의 확인·원본 백업·적용·복원. 장비 연결은 하지 않는다."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sysconfig
import tempfile
import uuid

EXPECTED_SOURCE = "fb01e47292a94c48fc00cb5e8ec42a4d6ec9d0987ecefaab0da6f60258a7b625"
FILES = ("_owner_worker.py", "_lf_command_gate.py", "_lf_owner_bridge.py")
SERIALS = ("5B91045573", "5B91030622")


def digest(content):
    return hashlib.sha256(content).hexdigest()


def read_candidate(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "PREPARED_NOT_INSTALLED" or manifest.get("source_sha256") != EXPECTED_SOURCE:
        raise RuntimeError("검토한 원본에서 생성한 후보가 아닙니다")
    if set(manifest.get("files", {})) != set(FILES):
        raise RuntimeError("후보 파일 목록 불일치")
    data = {}
    for name in FILES:
        content = (directory / name).read_bytes()
        if digest(content) != manifest["files"][name]:
            raise RuntimeError(f"후보 해시 불일치: {name}")
        compile(content, name, "exec")
        data[name] = content
    return manifest, data


def require_idle():
    """연결/목표값 쓰기 없이 프로세스와 열린 USB 파일만 조사한다."""
    root = Path("/proc")
    if not root.is_dir():
        raise RuntimeError("이 작업은 Linux 컨테이너에서 실행하세요")
    devices = set()
    for serial in SERIALS:
        path = Path(f"/dev/serial/by-id/usb-1a86_USB_Single_Serial_{serial}-if00")
        if path.exists():
            devices.add(str(path.resolve()))
    busy = set()
    for proc in root.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            command = (proc / "cmdline").read_bytes()
            if any(marker in command for marker in (
                b"physicalai.robot.transport._owner_worker",
                b"runtime.hosts.session_worker",
            )):
                busy.add(int(proc.name))
            for fd in (proc / "fd").iterdir():
                try:
                    if os.readlink(fd) in devices:
                        busy.add(int(proc.name))
                except FileNotFoundError:
                    pass
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as error:
            raise RuntimeError(f"프로세스 {proc.name} 사용 상태를 확인할 수 없습니다") from error
    if busy:
        raise RuntimeError(f"활성 소유자/세션/USB 사용 PID: {sorted(busy)}. 적용·복원 중단")


def check(candidate, transport):
    manifest, data = read_candidate(candidate)
    transport = Path(transport)
    owner = transport / FILES[0]
    if owner.is_symlink() or any((transport / name).is_symlink() for name in FILES[1:]):
        raise RuntimeError("패치 대상 심볼릭 링크는 지원하지 않습니다")
    current = owner.read_bytes()
    if digest(current) == manifest["files"][FILES[0]]:
        if any(not (transport / name).is_file() or digest((transport / name).read_bytes()) != manifest["files"][name]
               for name in FILES[1:]):
            raise RuntimeError("부분 설치 또는 파일 변경 감지")
        return manifest, data, "ALREADY_INSTALLED"
    if digest(current) != EXPECTED_SOURCE:
        raise RuntimeError("설치된 원본 소유자 해시가 검토본과 다릅니다")
    if any((transport / name).exists() for name in FILES[1:]):
        raise RuntimeError("기존 추가 모듈이 있어 자동 덮어쓰지 않습니다")
    return manifest, data, "READY_NOT_INSTALLED"


def backup(candidate, transport, directory):
    require_idle()
    manifest, data, status = check(candidate, transport)
    if status != "READY_NOT_INSTALLED":
        raise RuntimeError("새 백업은 원본 상태에서만 생성합니다")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    original = (Path(transport) / FILES[0]).read_bytes()
    if digest(original) != EXPECTED_SOURCE:
        raise RuntimeError("백업 직전 원본이 변경됐습니다")
    for name, content in {"original_owner.py": original, **data}.items():
        with (directory / name).open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    record = {"transport": str(Path(transport).resolve()), "source_sha256": EXPECTED_SOURCE,
              "installed_hashes": manifest["files"], "status": "BACKUP_READY"}
    with (directory / "backup.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    return record


def read_backup(directory, transport):
    directory = Path(directory)
    record = json.loads((directory / "backup.json").read_text(encoding="utf-8"))
    if record.get("transport") != str(Path(transport).resolve()) or record.get("source_sha256") != EXPECTED_SOURCE:
        raise RuntimeError("백업 대상 경로 또는 원본 해시 불일치")
    if set(record.get("installed_hashes", {})) != set(FILES):
        raise RuntimeError("백업 파일 목록 불일치")
    original = (directory / "original_owner.py").read_bytes()
    if digest(original) != EXPECTED_SOURCE:
        raise RuntimeError("원본 백업 해시 불일치")
    data = {}
    for name in FILES:
        content = (directory / name).read_bytes()
        if digest(content) != record["installed_hashes"][name]:
            raise RuntimeError(f"백업한 후보 해시 불일치: {name}")
        compile(content, name, "exec")
        data[name] = content
    return record, original, data


def atomic_write(path, content):
    path = Path(path)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    handle, temporary = tempfile.mkstemp(prefix=".lf-patch-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clear_bytecode(transport):
    cache = Path(transport) / "__pycache__"
    if cache.is_dir():
        for name in FILES:
            for path in cache.glob(Path(name).stem + ".*.pyc"):
                path.unlink()


def apply(backup_dir, transport):
    require_idle()
    record, original, data = read_backup(backup_dir, transport)
    transport = Path(transport)
    if any((transport / name).is_symlink() for name in FILES):
        raise RuntimeError("심볼릭 링크 대상으로 적용하지 않습니다")
    if digest((transport / FILES[0]).read_bytes()) != EXPECTED_SOURCE:
        raise RuntimeError("원본 상태가 아니므로 적용하지 않습니다")
    if any((transport / name).exists() for name in FILES[1:]):
        raise RuntimeError("추가 모듈이 이미 존재합니다")
    try:
        # 의존 모듈부터 배치하고 진입점은 마지막에 교체한다.
        for name in (*FILES[1:], FILES[0]):
            require_idle()
            atomic_write(transport / name, data[name])
        clear_bytecode(transport)
        if any(digest((transport / name).read_bytes()) != record["installed_hashes"][name] for name in FILES):
            raise RuntimeError("적용 후 해시 검증 실패")
    except Exception:
        # 실패하면 원본 진입점을 우선 복구한다. 실패를 숨기지 않는다.
        atomic_write(transport / FILES[0], original)
        for name in FILES[1:]:
            path = transport / name
            if path.exists() and digest(path.read_bytes()) == record["installed_hashes"][name]:
                path.unlink()
        clear_bytecode(transport)
        raise


def rollback(backup_dir, transport):
    require_idle()
    record, original, data = read_backup(backup_dir, transport)
    transport = Path(transport)
    for name in FILES:
        path = transport / name
        if path.is_symlink():
            raise RuntimeError("심볼릭 링크 대상으로 복원하지 않습니다")
        if not path.exists() and name != FILES[0]:
            continue
        allowed = {record["installed_hashes"][name]}
        if name == FILES[0]:
            allowed.add(EXPECTED_SOURCE)
        if digest(path.read_bytes()) not in allowed:
            raise RuntimeError(f"알 수 없는 변경이 있어 보존합니다: {name}")
    atomic_write(transport / FILES[0], original)
    for name in FILES[1:]:
        path = transport / name
        if path.exists():
            path.unlink()
    clear_bytecode(transport)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "backup", "apply", "rollback"))
    parser.add_argument("--candidate")
    parser.add_argument("--backup-dir")
    parser.add_argument("--transport-dir", default=str(Path(sysconfig.get_path("purelib")) / "physicalai/robot/transport"))
    args = parser.parse_args()
    transport = Path(args.transport_dir)
    if args.operation in ("check", "backup") and not args.candidate:
        parser.error("--candidate 필요")
    if args.operation in ("backup", "apply", "rollback") and not args.backup_dir:
        parser.error("--backup-dir 필요")
    if args.operation == "check":
        manifest, data, status = check(args.candidate, transport)
    elif args.operation == "backup":
        backup(args.candidate, transport, args.backup_dir)
        status = "BACKUP_READY_NOT_INSTALLED"
    elif args.operation == "apply":
        apply(args.backup_dir, transport)
        status = "PATCH_INSTALLED_NO_HARDWARE_CONNECTION"
    else:
        rollback(args.backup_dir, transport)
        status = "ORIGINAL_RESTORED_NO_HARDWARE_CONNECTION"
    print(json.dumps({"result": status, "transport_dir": str(transport),
                      "backup_dir": args.backup_dir, "hardware_connected": False}, indent=2))


if __name__ == "__main__":
    main()
