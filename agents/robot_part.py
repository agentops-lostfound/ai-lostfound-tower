"""진짜 로봇팔 부품 꽂기 (LF-8 · 11/9 변재원)

한줄 설명: `.env` 의 `TOWER_ROBOT_PART=모듈:클래스` 로 로봇 쪽(김건태·이순필)이 만든 부품 클래스를 관제탑 반환 흐름에 꽂는다.
없으면 예전처럼 가짜 로봇(시연용)을 쓴다.

- 부품 클래스는 인자 없이 만들 수 있어야 하고, 필수 함수 6개(agents/robot_api.py ROBOT_COMMANDS)를 가져야 한다
- DB 칸 모드(TOWER_ROBOT_TARGET=db)로 움직이려면 선택 함수 robot_go_pose(pose_name, slot_id) 도 있어야 한다
- 안내: docs/contracts/robot_db_target.md 9장
"""
from __future__ import annotations

import importlib
import os
import re

SPEC_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


class RobotPartError(RuntimeError):
    """TOWER_ROBOT_PART 값이 틀렸거나 부품에 필수 함수가 없음 — 관제탑을 켤 때 바로 알린다"""


def load_robot_part(spec: str):
    """"robot.tower_part:TowerRobot" → 부품 객체. 형식·필수 함수를 확인한다"""
    from agents.robot_api import check_robot_part
    if not SPEC_RE.match(spec or ""):
        raise RobotPartError(f"TOWER_ROBOT_PART 형식은 '모듈:클래스'(예: robot.tower_part:TowerRobot) — 지금 값: {spec!r}")
    mod_name, cls_name = spec.split(":")
    try:
        cls = getattr(importlib.import_module(mod_name), cls_name)
    except (ImportError, AttributeError) as e:
        raise RobotPartError(f"TOWER_ROBOT_PART 를 불러오지 못함({type(e).__name__}: {e})") from e
    part = cls()
    missing = check_robot_part(part)["missing"]
    if missing:
        raise RobotPartError(f"로봇 부품 {spec} 에 필수 함수가 없음: {missing}")
    return part


def robot_part_from_env():
    """.env TOWER_ROBOT_PART 가 있으면 부품, 없으면 None(가짜 로봇)"""
    spec = (os.environ.get("TOWER_ROBOT_PART") or "").strip()
    return load_robot_part(spec) if spec else None


__all__ = ["RobotPartError", "load_robot_part", "robot_part_from_env"]
