"""부품 연결판(CompositeBackend) — LF-14 (docs/design/integration.md).

한줄 설명: 팀원이 만든 진짜 부품(비전·매칭·DB·로봇)을 하나씩 꽂고, 아직 없는 부품은 가짜로 채워 전체 흐름을 계속 돌린다.

    from agents.backends import CompositeBackend
    be = CompositeBackend(vision=VisionPart(), db=DbPart())   # 매칭·로봇은 아직 가짜
    print(be.sources())    # 함수마다 진짜/가짜 확인
    run_return(req, be, reporter)

- 부품이 갖춰야 할 함수 이름·입출력은 아래 Protocol 과 docs/contracts/mcp_tools.md 2장이 기준이다.
- 연결 전에 check_part(부품, "vision") 로 빠진 함수가 없는지 먼저 확인한다.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from agents.tools import MockBackend

# 부품 묶음 → 그 부품이 맡는 함수(담당은 docs/contracts/mcp_tools.md)
GROUPS: dict[str, tuple[str, ...]] = {
    "vision": ("vision_topview",),                                  # 김건태 LF-3
    "matcher": ("match_item",),                                     # 김건태 LF-20
    "db": ("db_get_item", "db_set_status", "db_list_active"),       # 변재원 LF-8
    "robot": ("robot_approach", "robot_grasp", "robot_verify_grasp",  # 김건태 LF-19·21, 이순필 LF-11
              "robot_deliver", "robot_stop"),
}
METHODS = tuple(m for names in GROUPS.values() for m in names)


@runtime_checkable
class Backend(Protocol):
    """반환 흐름이 부르는 함수 모양(본문 없음). 진짜 부품은 맡은 묶음의 함수만 있으면 된다."""
    def vision_topview(self) -> list[dict]: ...
    def match_item(self, query: dict, detections: list[dict]) -> dict: ...
    def db_get_item(self, item_id: str) -> dict | None: ...
    def db_set_status(self, item_id: str, status: str) -> dict: ...
    def db_list_active(self) -> list[dict] | None: ...
    def robot_approach(self, center: list) -> dict: ...
    def robot_grasp(self) -> dict: ...
    def robot_verify_grasp(self) -> dict: ...
    def robot_deliver(self) -> dict: ...
    def robot_stop(self) -> dict: ...


def check_part(part: object, group: str) -> list[str]:
    """부품이 그 묶음에 필요한 함수를 다 갖췄는지. 빠진 함수 이름 목록(빈 목록이면 연결 가능)."""
    if group not in GROUPS:
        raise ValueError(f"모르는 묶음: {group} (허용: {list(GROUPS)})")
    return [m for m in GROUPS[group] if not callable(getattr(part, m, None))]


class CompositeBackend:
    """묶음별로 진짜 부품을 꽂고, 없는 묶음은 fallback(기본 가짜 부품)으로 돌린다."""

    def __init__(self, vision=None, matcher=None, db=None, robot=None, fallback=None):
        self.fallback = fallback if fallback is not None else MockBackend()
        self._route: dict[str, object] = {}
        for group, part in (("vision", vision), ("matcher", matcher), ("db", db), ("robot", robot)):
            if part is None:
                continue
            missing = check_part(part, group)
            if missing:
                raise TypeError(f"{group} 부품에 함수가 없습니다: {missing}")
            for m in GROUPS[group]:
                self._route[m] = part

    def __getattr__(self, name: str):
        if name in METHODS:
            return getattr(self._route.get(name, self.fallback), name)
        # 시험용 확인 함수(robot_moved 등)는 가짜 부품 쪽 것을 쓴다
        return getattr(self.fallback, name)

    def sources(self) -> dict[str, str]:
        """함수마다 진짜(클래스 이름)인지 가짜인지."""
        return {m: (type(self._route[m]).__name__ if m in self._route else "가짜") for m in METHODS}

    def is_all_real(self) -> bool:
        return all(m in self._route for m in METHODS)


__all__ = ["Backend", "CompositeBackend", "GROUPS", "METHODS", "check_part"]
