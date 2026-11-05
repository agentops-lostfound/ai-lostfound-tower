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
        command += ["--candidate", record.get("container_candidate", record["container_dir"] + "/candidate")]
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


def preflight(record, expected_file, *, sync_goal=False, diagnose=False):
    if sync_goal:
        raise RuntimeError("--sync-goal 사용 중단: 목표값 기록이 토크를 켤 수 있습니다")
    if not record.get("patch_installed"):
        raise RuntimeError("기존 패치 적용 기록이 필요합니다")
    expected_file = Path(expected_file).resolve()
    saved = json.loads(expected_file.read_text(encoding="utf-8-sig"))
    if saved.get("serial") != "5B91030622":
        raise RuntimeError("새 팔로워의 최종 보정 파일이 아닙니다")
    checked = manager(record, "check")
    if checked.get("result") != "ALREADY_INSTALLED":
        raise RuntimeError("기존 패치 설치 상태가 다릅니다")
    for name in ("robot_start_preflight.py", "manage_robot_owner_patch.py"):
        execute("docker", "cp", str(ROOT / "tools" / name),
                CONTAINER + ":" + record["container_dir"] + "/" + name)
    target = record["container_dir"] + "/expected-follower-calibration.json"
    execute("docker", "cp", str(expected_file), CONTAINER + ":" + target)
    command = ["docker", "exec", "--user", "0", CONTAINER, "python",
               record["container_dir"] + "/robot_start_preflight.py",
               "--expected-file", target]
    if sync_goal:
        command.append("--sync-goal")
    if diagnose:
        command.append("--diagnose")
    result = json.loads(execute(*command))
    # 토크 OFF 목표값 동기화의 변경 전 기록도 Windows에 보존한다.
    if result.get("backup"):
        destination = Path(record["local_backup"]) / Path(result["backup"]).name
        execute("docker", "cp", CONTAINER + ":" + result["backup"], str(destination))
        result["windows_backup"] = str(destination)
    return result


def upgrade_telemetry(record, trial_file):
    if not record.get("patch_installed") or manager(record, "check").get("result") != "ALREADY_INSTALLED":
        raise RuntimeError("기존 패치 적용 상태가 다릅니다")
    sys.path.insert(0, str(ROOT))
    from tools.prepare_robot_owner_patch import patched_source, check_patched_loop
    original = (Path(record["local_backup"]) / "original_owner.py").read_bytes()
    if hashlib.sha256(original).hexdigest() != EXPECTED_SOURCE:
        raise RuntimeError("원본 Windows 백업 해시가 다릅니다")
    owner_source = patched_source(original.decode("utf-8"))
    check_patched_loop(owner_source)
    owner_digest = hashlib.sha256(owner_source.encode()).hexdigest()
    bridge_digest = hashlib.sha256((ROOT / "robot/owner_bridge.py").read_bytes()).hexdigest()
    if (record.get("telemetry_bridge_sha256") == bridge_digest
            and record.get("telemetry_owner_sha256") == owner_digest):
        return {"result": "TELEMETRY_ALREADY_INSTALLED", "hardware_connected": False}
    for name in ("upgrade_robot_owner_telemetry.py", "manage_robot_owner_patch.py"):
        execute("docker", "cp", str(ROOT / "tools" / name),
                CONTAINER + ":" + record["container_dir"] + "/" + name)
    staged_owner = Path(record["local_backup"]) / ("owner-manual-guard-" + uuid.uuid4().hex + ".py")
    staged_owner.write_text(owner_source, encoding="utf-8", newline="\n")
    owner_target = record["container_dir"] + "/telemetry-owner.py"
    execute("docker", "cp", str(staged_owner), CONTAINER + ":" + owner_target)
    bridge = record["container_dir"] + "/telemetry-bridge.py"
    execute("docker", "cp", str(ROOT / "robot/owner_bridge.py"), CONTAINER + ":" + bridge)
    identity = uuid.uuid4().hex
    helper = record["container_dir"] + "/upgrade_robot_owner_telemetry.py"
    output = "/app/storage/patches/lf-owner-safety-telemetry-" + identity
    previous = dict(record)
    result = json.loads(execute("docker", "exec", "--user", "0", CONTAINER, "python", helper,
        "--candidate", record.get("container_candidate", record["container_dir"] + "/candidate"),
        "--backup", record["container_backup"], "--bridge-file", bridge, "--output", output,
        "--owner-file", owner_target))
    destination = Path(record["local_backup"]) / ("telemetry-" + identity)
    try:
        execute("docker", "cp", CONTAINER + ":" + result["container_backup"], str(destination))
        metadata = json.loads((destination / "backup.json").read_text(encoding="utf-8"))
        if hashlib.sha256((destination / "original_owner.py").read_bytes()).hexdigest() != EXPECTED_SOURCE:
            raise RuntimeError("원본 Windows 사본 검증 실패")
        for name in FILES:
            if hashlib.sha256((destination / name).read_bytes()).hexdigest() != metadata["installed_hashes"][name]:
                raise RuntimeError("갱신된 Windows 사본 검증 실패")
        updated = {**record, "container_candidate": result["container_candidate"],
                   "container_backup": result["container_backup"], "telemetry_enabled": True,
                   "telemetry_bridge_sha256": bridge_digest, "telemetry_owner_sha256": owner_digest,
                   "previous_patch_records": [*record.get("previous_patch_records", []),
                       {key: record.get(key) for key in ("container_candidate", "container_backup")} ]}
        import os
        import tempfile
        handle, temporary = tempfile.mkstemp(prefix=".trial-", dir=Path(trial_file).resolve().parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(updated, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, trial_file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except Exception:
        execute("docker", "exec", "--user", "0", CONTAINER, "python", helper,
                "--undo", "--backup", previous["container_backup"],
                "--candidate", result["container_candidate"])
        raise
    return {**result, "windows_backup": str(destination), "trial_file": str(trial_file)}


def capture_home(record, expected_file, *, expected_session=None, expected_epoch=None):
    if not record.get("patch_installed") or manager(record, "check").get("result") != "ALREADY_INSTALLED":
        raise RuntimeError("기존 패치 적용 상태를 확인하지 못했습니다")
    expected_file = Path(expected_file).resolve()
    reference = json.loads(expected_file.read_text(encoding="utf-8-sig"))
    if reference.get("serial") != "5B91030622":
        raise RuntimeError("새 팔로워의 보정 기준이 아닙니다")
    for name in ("robot_home_snapshot.py", "robot_bounded_stop_trial.py", "test_robot_owner_zenoh.py"):
        execute("docker", "cp", str(ROOT / "tools" / name),
                CONTAINER + ":" + record["container_dir"] + "/" + name)
    target = record["container_dir"] + "/home-calibration-reference.json"
    execute("docker", "cp", str(expected_file), CONTAINER + ":" + target)
    output = record["container_dir"] + "/home-candidate-" + uuid.uuid4().hex + ".json"
    command = ["docker", "exec", CONTAINER, "python",
               record["container_dir"] + "/robot_home_snapshot.py", "--output-file", output,
               "--calibration-reference", target]
    if expected_session is not None:
        if type(expected_epoch) is not int:
            raise ValueError("현재 명령 세대가 필요합니다")
        command += ["--expected-session", expected_session, "--expected-epoch", str(expected_epoch)]
    result = json.loads(execute(*command))
    if result.get("result") != "HOME_CANDIDATE_SAVED" or result.get("movement_commands_sent") != 0:
        raise RuntimeError("후보 저장 결과 검증 실패")
    destination = Path(record["local_backup"]) / Path(output).name
    execute("docker", "cp", CONTAINER + ":" + output, str(destination))
    result["windows_file"] = str(destination)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "apply", "rollback", "panel", "preflight", "diagnose", "move-test", "home-offset", "capture-home", "telemetry-upgrade"))
    parser.add_argument("--candidate-dir")
    parser.add_argument("--trial")
    parser.add_argument("--expected-file", default=str(ROOT.parent / "soarm-setup/new-follower-calibration-complete.json"))
    parser.add_argument("--sync-goal", action="store_true")
    parser.add_argument("--confirm-ready", action="store_true")
    parser.add_argument("--home-side", choices=("positive", "negative"), default="positive")
    args = parser.parse_args()
    if args.operation == "prepare":
        if not args.candidate_dir:
            parser.error("--candidate-dir 필요")
        print(json.dumps(prepare(args.candidate_dir), ensure_ascii=True, indent=2))
        return
    if not args.trial:
        parser.error("--trial 필요")
    record = load_trial(args.trial)
    if args.operation == "telemetry-upgrade":
        print(json.dumps(upgrade_telemetry(record, args.trial), indent=2))
        return
    if args.operation == "capture-home":
        print(json.dumps(capture_home(record, args.expected_file), ensure_ascii=True, indent=2))
        return
    if args.operation in ("move-test", "home-offset"):
        if not args.confirm_ready:
            parser.error("실물 이동 시험입니다. 준비 확인 후 --confirm-ready가 필요합니다")
        if not record.get("patch_installed") or manager(record, "check").get("result") != "ALREADY_INSTALLED":
            raise RuntimeError("기존 패치 적용 상태를 확인하지 못했습니다")
        for name in ("robot_bounded_stop_trial.py", "test_robot_owner_zenoh.py"):
            execute("docker", "cp", str(ROOT / "tools" / name),
                    CONTAINER + ":" + record["container_dir"] + "/" + name)
        command = ["docker", "exec", CONTAINER, "python",
                   record["container_dir"] + "/robot_bounded_stop_trial.py", "--confirm-ready"]
        if args.operation == "home-offset":
            sys.path.insert(0, str(ROOT))
            from robot.home_profiles import load_home
            profile_file = Path(record["local_backup"]) / ("offset-profile-" + uuid.uuid4().hex + ".json")
            profile_file.write_text(json.dumps(load_home(), indent=2), encoding="utf-8")
            target = record["container_dir"] + "/offset-profile.json"
            execute("docker", "cp", str(profile_file), CONTAINER + ":" + target)
            execute("docker", "cp", str(ROOT / "robot/home_profiles.py"),
                    CONTAINER + ":" + record["container_dir"] + "/home_profiles.py")
            command += ["--home-profile", target, "--home-side", args.home_side]
        subprocess.run(command, check=True)
        return
    if args.operation in ("preflight", "diagnose"):
        print(json.dumps(preflight(record, args.expected_file, sync_goal=args.sync_goal, diagnose=args.operation == "diagnose"), ensure_ascii=True, indent=2))
        return
    if args.operation == "panel":
        if not record.get("patch_installed"):
            raise RuntimeError("패치 적용 확인 전에는 실제 조작 화면을 시작하지 않습니다")
        # 현재 컨테이너가 재생성되어 패치가 사라졌는지 먼저 확인한다.
        checked = manager(record, "check")
        if checked.get("result") != "ALREADY_INSTALLED":
            raise RuntimeError("설치 상태 불일치")
        for name in ("robot_stop_panel.py", "robot_home_return.py", "robot_bounded_stop_trial.py", "test_robot_owner_zenoh.py"):
            execute("docker", "cp", str(ROOT / "tools" / name),
                    CONTAINER + ":" + record["container_dir"] + "/" + name)
        execute("docker", "cp", str(ROOT / "robot/home_profiles.py"),
                CONTAINER + ":" + record["container_dir"] + "/home_profiles.py")
        subprocess.run([sys.executable, str(ROOT / "tools/robot_stop_panel.py"),
                        "--container-dir", record["container_dir"],
                        "--trial-file", str(Path(args.trial).resolve()),
                        "--expected-file", str(Path(args.expected_file).resolve())], check=True)
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
