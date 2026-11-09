"""관제탑 ↔ 로봇팔 계약 (11/5 재정립) — 설명서 docs/contracts/robot_api.md

한줄 설명: 관제탑이 로봇에게 보내는 의미 명령 6개와, 로봇이 돌려주는 상태(단계·정지·관절 6개)의 모양을 한 곳에 모은다.
가상 로봇(agents/sim_world.py SimRobot)과 진짜 로봇 부품이 같은 이름·같은 결과 모양을 쓰는지 여기서 검사한다.
표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import math

# 반환 흐름(supervisor)이 부르는 순서대로. 결과는 모두 {ok, reason} (contracts.robot_result)
ROBOT_COMMANDS = ("robot_approach", "robot_grasp", "robot_verify_grasp", "robot_deliver", "robot_stop", "robot_home")
ROBOT_OPTIONAL = ("robot_state", "robot_go_pose")   # 11/5 robot_state: 화면용 상태 읽기 · 11/9 robot_go_pose(pose_name, slot_id): DB 칸 모드 접근

# SO-101 관절(번호·이름은 sim_world.SO101_JOINTS 와 같다). 각도 °, 집게 %
JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
STATE_KEYS = {"phase", "stopped", "holding", "joints", "source"}


def validate_robot_result(r: object) -> list[str]:
    """명령 결과 {ok: bool, reason: str} 검사. 빈 목록이면 통과."""
    if not isinstance(r, dict):
        return ["결과는 {ok, reason} 객체"]
    errs = []
    if not isinstance(r.get("ok"), bool):
        errs.append("ok: true/false")
    if not isinstance(r.get("reason", ""), str):
        errs.append("reason: 글자")
    return errs


def validate_robot_state(s: object) -> list[str]:
    """robot_state() 결과 검사. 빈 목록이면 통과.
    {phase: 글자, stopped: bool, holding: 접수 번호|None, joints: {이름: 숫자 6개}, source: "sim"|"real"}"""
    if not isinstance(s, dict):
        return ["상태는 객체"]
    errs = []
    missing = STATE_KEYS - set(s)
    if missing:
        errs.append(f"빠진 칸: {sorted(missing)}")
    if "phase" in s and not isinstance(s["phase"], str):
        errs.append("phase: 글자")
    if "stopped" in s and not isinstance(s["stopped"], bool):
        errs.append("stopped: true/false")
    if "holding" in s and s["holding"] is not None and not isinstance(s["holding"], str):
        errs.append("holding: 접수 번호 또는 null")
    if "source" in s and s["source"] not in ("sim", "real"):
        errs.append("source: sim | real")
    j = s.get("joints")
    if "joints" in s:
        if not isinstance(j, dict) or set(j) != set(JOINT_NAMES):
            errs.append(f"joints: {list(JOINT_NAMES)} 6개")
        else:
            for k, v in j.items():
                if type(v) not in (int, float) or not math.isfinite(v):
                    errs.append(f"joints.{k}: 유한한 숫자")
            if not errs and not 0 <= j["gripper"] <= 100:
                errs.append("joints.gripper: 0~100 %")
    return errs


def check_robot_part(part: object) -> dict:
    """진짜 로봇 부품 연결 전 점검: 빠진 명령 함수와 상태 함수가 있는지."""
    return {"missing": [m for m in ROBOT_COMMANDS if not callable(getattr(part, m, None))],
            "has_state": callable(getattr(part, "robot_state", None))}


__all__ = ["ROBOT_COMMANDS", "ROBOT_OPTIONAL", "JOINT_NAMES", "validate_robot_result", "validate_robot_state",
           "check_robot_part"]
