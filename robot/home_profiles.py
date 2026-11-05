"""LF-11/12 Home 목표 설정. 장비/통신을 사용하지 않는 파일 설정 계층.

자세를 바꾸면 이전 경로 검증을 재사용하지 않는다. 이 모듈은 Home 이동을
실행하지 않으며, 복귀 경로가 없는 자세 설정을 실행 가능으로 표시하지 않는다.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = Path(__file__).with_name("config") / "home_pose.json"
DEFAULT_STORE = ROOT / "outputs/robot-home"
ROBOT_ID = "0f876b83-64cd-4bb9-9630-963eaeb3c0b7"
SERIAL = "5B91030622"
NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_pose(profile):
    if (profile.get("robot_id") != ROBOT_ID or profile.get("serial") != SERIAL
            or profile.get("unit") != "normalized" or profile.get("joint_order") != NAMES):
        raise ValueError("로봇 식별자·단위·관절 순서 불일치")
    values = profile.get("positions")
    if (not isinstance(values, list) or len(values) != 6
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)):
        raise ValueError("유한한 6개 관절 위치가 필요합니다")
    if any(not -100 <= value <= 100 for value in values[:5]) or not 0 <= values[5] <= 100:
        raise ValueError("정규화 관절 범위 밖입니다")
    fingerprint = profile.get("calibration_reference_sha256")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(x not in "0123456789abcdef" for x in fingerprint):
        raise ValueError("보정 기준 해시 오류")


def validate_profile(profile):
    validate_pose(profile)
    if (profile.get("schema") != "lf-home-profile-v1" or profile.get("pose_selected") is not True
            or type(profile.get("revision")) is not int or profile["revision"] < 1):
        raise ValueError("Home 설정 형식 오류")
    if profile.get("path_verified") is not False or profile.get("motion_enabled") is not False:
        raise ValueError("자세 설정만으로 복귀 경로를 승인하거나 실행할 수 없습니다")
    return profile


def load_home(store=DEFAULT_STORE):
    path = Path(store) / "active.json"
    default = validate_profile(read_json(DEFAULT_FILE))
    if not path.exists():
        return default
    profile = validate_profile(read_json(path))
    if profile["calibration_reference_sha256"] != default["calibration_reference_sha256"]:
        raise ValueError("활성 Home과 현재 보정 기준 불일치")
    return profile


def atomic_json(path, profile):
    handle, temporary = tempfile.mkstemp(prefix=".home-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def setting_lock(folder):
    path = folder / ".setting.lock"
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError("다른 Home 설정 작업이 진행 중이거나 확인이 필요한 잠금 파일이 있습니다") from error
    try:
        os.close(handle)
        yield
    finally:
        path.unlink()


def select_candidate(candidate_file, store=DEFAULT_STORE, *, name="접힌 대기 자세"):
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("Home 자세 이름은 1~100자로 지정하세요")
    candidate = read_json(candidate_file)
    validate_pose(candidate)
    if candidate.get("schema") != "lf-home-candidate-v1" or candidate.get("candidate_only") is not True:
        raise ValueError("기록 도구가 만든 Home 후보가 아닙니다")
    default = validate_profile(read_json(DEFAULT_FILE))
    if candidate["calibration_reference_sha256"] != default["calibration_reference_sha256"]:
        raise ValueError("후보와 현재 보정 기준 불일치: 재보정 후 이전 후보를 재사용할 수 없습니다")
    spans = candidate.get("observation_span_normalized")
    if (not isinstance(spans, list) or len(spans) != 6
            or any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 0.5 for x in spans)):
        raise ValueError("후보 자세 안정성 기록 오류")
    folder = Path(store)
    folder.mkdir(parents=True, exist_ok=True)
    active = folder / "active.json"
    with setting_lock(folder):
        current = load_home(folder)
        same = current["positions"] == candidate["positions"] and current.get("name") == name.strip()
        if active.exists() and same:
            return {"result": "HOME_POSE_ALREADY_CONFIGURED", "profile_file": str(active.resolve()),
                    "name": current["name"], "revision": current["revision"], "pose_selected": True,
                    "motion_enabled": False, "path_verified": False, "movement_commands_sent": 0}
        profile = deepcopy(default)
        profile.update({
            "name": name.strip(), "positions": list(candidate["positions"]),
            "revision": current["revision"] if same else current["revision"] + 1,
            "selected_by": "user", "selected_at": datetime.now(timezone.utc).isoformat(),
            "source_candidate": Path(candidate_file).name,
            "pose_selected": True, "path_verified": False, "motion_enabled": False,
        })
        profile.pop("selected_date", None)
        validate_profile(profile)
        history = folder / "history"
        history.mkdir(exist_ok=True)
        history_file = history / f"revision-{profile['revision']}-{uuid.uuid4().hex}.json"
        with history_file.open("x", encoding="utf-8") as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # 이력 저장이 실패하면 활성 설정을 교체하지 않는다.
        atomic_json(active, profile)
    return {"result": "HOME_POSE_CONFIGURED", "profile_file": str(active.resolve()),
            "history_file": str(history_file.resolve()), "name": profile["name"],
            "revision": profile["revision"], "positions": profile["positions"],
            "pose_selected": True, "path_verified": False, "motion_enabled": False,
            "movement_commands_sent": 0}
