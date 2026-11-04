"""LF-12 Windows용 실물 시험 준비. 장비 자동 연결/토크 조작 없음."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

try:
    from .manage_robot_owner_patch import EXPECTED_SOURCE, FILES, read_candidate
except ImportError:
    from manage_robot_owner_patch import EXPECTED_SOURCE, FILES, read_candidate

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "physical-ai-studio-cuda"


def execute(*arguments):
    result = subprocess.run(list(arguments), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "명령 실행 실패")
    return result.stdout


def manager(record, operation):
    # 프로세스 조사/코드 백업에만 관리자 권한을 사용한다.
    # 상태·정지 화면과 장비 제어 작업자는 기존 사용자로 실행한다.
    command = ["docker", "exec", "--user", "0", CONTAINER, "python", record["container_dir"] + "/manage_robot_owner_patch.py", operation]
    if operation in ("check", "backup"):
        command += ["--candidate", record["container_dir"] + "/candidate"]
    if operation in ("backup", "apply", "rollback"):
        command += ["--backup-dir", record["container_backup"]]
    return json.loads(execute(*command))


def prepare(candidate):
    candidate = Path(candidate).resolve()
    read_candidate(candidate)
    identity = uuid.uuid4().hex
    output = ROOT / "outputs/robot-owner-trial" / identity
    output.mkdir(parents=True)
    record = {
        "container": CONTAINER,
        "container_dir": "/tmp/lf-owner-trial-" + identity,
        "container_backup": "/app/storage/patches/lf-owner-safety-" + identity,
        "local_backup": str(output / "backup"),
        "patch_installed": False,
        "hardware_connected": False,
    }
    # 폴더만 생성하며 SDK나 로봇은 불러오지 않는다.
    execute("docker", "exec", CONTAINER, "python", "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).mkdir()", record["container_dir"])
    for name in ("manage_robot_owner_patch.py", "robot_stop_panel.py", "test_robot_owner_zenoh.py"):
        execute("docker", "cp", str(ROOT / "tools" / name),
                CONTAINER + ":" + record["container_dir"] + "/" + name)
    execute("docker", "cp", str(candidate), CONTAINER + ":" + record["container_dir"] + "/candidate")
    checked = manager(record, "check")
    if checked.get("result") != "READY_NOT_INSTALLED":
        raise RuntimeError("원본 상태가 아닙니다: " + json.dumps(checked))
    backed = manager(record, "backup")
    if backed.get("result") != "BACKUP_READY_NOT_INSTALLED":
        raise RuntimeError("원본 백업 실패")
    execute("docker", "cp", CONTAINER + ":" + record["container_backup"], record["local_backup"])
    # Windows 사본까지 검증한 뒤에만 적용 가능한 기록을 만든다.
    folder = Path(record["local_backup"])
    metadata = json.loads((folder / "backup.json").read_text(encoding="utf-8"))
    if hashlib.sha256((folder / "original_owner.py").read_bytes()).hexdigest() != EXPECTED_SOURCE:
        raise RuntimeError("Windows 원본 백업 검증 실패")
    for name in FILES:
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != metadata["installed_hashes"][name]:
            raise RuntimeError("Windows 후보 백업 검증 실패: " + name)
    record["backup_copy_verified"] = True
    trial = output / "trial.json"
    trial.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"result": "READY_FOR_APPLY", "trial_file": str(trial),
            "windows_backup": record["local_backup"], "hardware_connected": False}


def load_trial(path):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if (record.get("container") != CONTAINER or not record.get("backup_copy_verified")
            or not record.get("container_dir", "").startswith("/tmp/lf-owner-trial-")
            or not record.get("container_backup", "").startswith("/app/storage/patches/lf-owner-safety-")):
        raise RuntimeError("이 도구가 준비한 시험 기록이 아닙니다")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "apply", "rollback", "panel"))
    parser.add_argument("--candidate-dir")
    parser.add_argument("--trial")
    args = parser.parse_args()
    if args.operation == "prepare":
        if not args.candidate_dir:
            parser.error("--candidate-dir 필요")
        print(json.dumps(prepare(args.candidate_dir), ensure_ascii=True, indent=2))
        return
    if not args.trial:
        parser.error("--trial 필요")
    record = load_trial(args.trial)
    if args.operation == "panel":
        if not record.get("patch_installed"):
            raise RuntimeError("패치 적용 확인 전에는 실제 조작 화면을 시작하지 않습니다")
        # 현재 컨테이너가 재생성되어 패치가 사라졌는지 먼저 확인한다.
        checked = manager(record, "check")
        if checked.get("result") != "ALREADY_INSTALLED":
            raise RuntimeError("설치 상태 불일치")
        subprocess.run([sys.executable, str(ROOT / "tools/robot_stop_panel.py"),
                        "--container-dir", record["container_dir"]], check=True)
        return
    result = manager(record, args.operation)
    record["patch_installed"] = args.operation == "apply"
    Path(args.trial).write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
