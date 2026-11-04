"""MCP 도구 목록과 가짜 부품(MockBackend) — LF-16.

한줄 설명: 메인 AI가 누를 수 있는 "버튼" 목록을 정하고, 진짜 모듈이 나오기 전까지 같은 입·출력을 흉내 내는 가짜 부품을 준다.

- 진짜 부품으로 바꿀 때는 MockBackend 와 같은 이름·입력·출력을 가진 클래스를 만들어 agents/backends.py 의 CompositeBackend 에 꽂는다.
- 도구 설명(TOOLS)은 docs/contracts/mcp_tools.md 와 같아야 한다.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from agents.contracts import (
    ACTIVE_STATUSES, FEATURE_FIELDS, MATCH_NONE, MATCH_OK, MATCH_UNCERTAIN, UNKNOWN, robot_result,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    owner: str          # 진짜 부품 담당(Jira)
    summary: str
    inputs: dict        # 이름 → 설명
    output: str
    on_fail: str


TOOLS: list[ToolSpec] = [
    ToolSpec("vision_topview", "김건태 LF-3", "탑뷰 카메라로 공용 보관함을 찍어 물건마다 박스·중심·특징 JSON을 낸다",
             {}, "detections: [{box, center, features}]", "빈 목록 + reason → 메인 AI가 직원 확인으로 넘김"),
    ToolSpec("match_item", "김건태 LF-20", "접수 때 저장한 특징과 탑뷰 물건들의 특징을 비교해 가장 유력한 물건을 고른다",
             {"query": "특징 JSON", "detections": "vision_topview 결과"},
             "{status: matched|uncertain|none, index, score, margin, ranking}", "uncertain·none 이면 자동 반환하지 않음"),
    ToolSpec("db_get_item", "변재원 LF-8", "접수 번호로 물건 기록(특징 JSON·상태)을 읽는다",
             {"item_id": "접수 번호"}, "{item_id, status, features}", "없으면 None"),
    ToolSpec("db_set_status", "변재원 LF-8", "물건 상태를 바꾸고 기록을 남긴다",
             {"item_id": "접수 번호", "status": "contracts.ITEM_STATUS 중 하나"}, "{ok, reason}", "실패하면 로봇을 움직이지 않음"),
    ToolSpec("db_list_active", "변재원 LF-8", "보관함에 있을 수 있는 물건(contracts.ACTIVE_STATUSES) 목록 — 닮은 물건 검사용",
             {}, "[{item_id, status, features}]", "None → 닮은 물건 검사 불가, 자동 반환하지 않음"),
    ToolSpec("robot_approach", "김건태 LF-21", "작업대 mm 좌표를 로봇 좌표로 바꿔 Home → 경유점 → 접근 자세로 이동",
             {"center_mm": "[x, y] 작업대 기준 mm (탑뷰 ArUco 보정 결과). 없으면 관제탑이 부르지 않음"}, "{ok, reason}", "정지 + #관제-알림"),
    ToolSpec("robot_grasp", "김건태 LF-19", "접근 자세에서 SmolVLA로 집고 안전한 높이까지 들기",
             {}, "{ok, reason}", "1번만 다시 시도, 그래도 실패하면 정지"),
    ToolSpec("robot_verify_grasp", "김건태 LF-19", "그리퍼 닫힘 정도 + 탑뷰 재확인으로 집기 성공 확인",
             {}, "{ok, reason}", "실패로 처리"),
    ToolSpec("robot_deliver", "이순필 LF-11", "저장한 경로로 바구니까지 옮겨 그리퍼 열기",
             {}, "{ok, reason}", "정지 + #관제-알림"),
    ToolSpec("robot_stop", "이순필 LF-11", "즉시 정지하고 Home 으로 복귀", {}, "{ok, reason}", "직원 호출"),
    ToolSpec("notify", "변재원 LF-17", "디스코드 관제 채널에 알림(개인정보 없이 물건 번호만)",
             {"channel": "progress|alert|score", "text": "내용"}, "{ok}", "알림 실패는 흐름을 멈추지 않음"),
]


# ---------- 매칭 자리표시(진짜는 LF-20) ----------
def feature_similarity(a: dict, b: dict) -> float:
    """두 특징 JSON의 일치도(0~1). 양쪽 모두 아는 항목만 비교한다."""
    agree = total = 0.0
    for f in FEATURE_FIELDS:
        x, y = a.get(f), b.get(f)
        if x in (None, "", UNKNOWN) or y in (None, "", UNKNOWN):
            continue
        weight = 2.0 if f in ("mark", "visible_text") else 1.0   # 비공개 특징이 구별력이 큼
        total += weight
        agree += weight if x == y else 0.0
    return agree / total if total else 0.0


def simple_match(query: dict, detections: list[dict], threshold: float = 0.6, margin: float = 0.15) -> dict:
    ranking = sorted(((feature_similarity(query, d["features"]), i) for i, d in enumerate(detections)), reverse=True)
    if not ranking or ranking[0][0] < threshold:
        return {"status": MATCH_NONE, "index": None, "score": ranking[0][0] if ranking else 0.0, "margin": 0.0,
                "ranking": [i for _, i in ranking]}
    top = ranking[0][0]
    second = ranking[1][0] if len(ranking) > 1 else 0.0
    status = MATCH_OK if top - second >= margin else MATCH_UNCERTAIN
    return {"status": status, "index": ranking[0][1], "score": round(top, 3), "margin": round(top - second, 3),
            "ranking": [i for _, i in ranking]}


# ---------- 가짜 부품 ----------
@dataclass
class MockBackend:
    """시험·시연 준비용 가짜 부품. 진짜 부품과 같은 메서드 이름을 쓴다.

    bin_items: 공용 보관함 안 물건 [{object_id, features, center}]
    db: 접수 번호 → {status, features, object_id}
    grasp_plan: 집기 시도마다 성공 여부(예: [False, True] = 첫 시도 실패, 재시도 성공)
    """
    bin_items: list[dict] = field(default_factory=list)
    db: dict = field(default_factory=dict)
    grasp_plan: list[bool] = field(default_factory=lambda: [True])
    approach_ok: bool = True
    deliver_ok: bool = True
    stop_ok: bool = True
    status_fail: set = field(default_factory=set)   # 실패시킬 상태 이름(시험용, 예: {"반환 중"})
    list_ok: bool = True                            # False 면 db_list_active 가 None(목록 읽기 실패 시험용)
    calls: list[str] = field(default_factory=list)
    _grasp_no: int = 0
    _last_grasp: bool = False

    def vision_topview(self) -> list[dict]:
        self.calls.append("vision_topview")
        out = []
        for it in self.bin_items:
            cx, cy = it.get("center", [320, 240])
            det = {"box": [cx - 40, cy - 30, cx + 40, cy + 30], "center": [cx, cy],
                   "features": {"category": "지갑", "confidence": 0.9, **copy.deepcopy(it["features"])},
                   "object_id": it.get("object_id")}
            mm = it.get("center_mm", [float(cx), float(cy)])   # 가짜: 보정됐다고 치고 픽셀 값을 mm 로. None 이면 보정 안 됨 시험
            if mm is not None:
                det["center_mm"] = mm
            out.append(det)
        return out

    def match_item(self, query: dict, detections: list[dict]) -> dict:
        self.calls.append("match_item")
        return simple_match(query, detections)

    def db_get_item(self, item_id: str) -> dict | None:
        self.calls.append("db_get_item")
        rec = self.db.get(item_id)
        return None if rec is None else {"item_id": item_id, **copy.deepcopy(rec)}

    def db_set_status(self, item_id: str, status: str) -> dict:
        self.calls.append(f"db_set_status:{status}")
        if item_id not in self.db:
            return robot_result(False, "물건 기록 없음")
        if status in self.status_fail:
            return robot_result(False, "DB 쓰기 실패")
        self.db[item_id]["status"] = status
        return robot_result(True)

    def db_list_active(self) -> list[dict] | None:
        self.calls.append("db_list_active")
        if not self.list_ok:
            return None
        return [{"item_id": k, "status": v.get("status"), "features": copy.deepcopy(v.get("features", {}))}
                for k, v in self.db.items() if v.get("status") in ACTIVE_STATUSES]

    def robot_approach(self, center_mm) -> dict:
        self.calls.append("robot_approach")
        self.last_approach = center_mm      # 시험에서 무엇을 넘겼는지 확인
        return robot_result(self.approach_ok, "접근 실패")

    def robot_grasp(self) -> dict:
        self.calls.append("robot_grasp")
        ok = self.grasp_plan[self._grasp_no] if self._grasp_no < len(self.grasp_plan) else False
        self._grasp_no += 1
        self._last_grasp = ok
        return robot_result(ok, "집기 실패")

    def robot_verify_grasp(self) -> dict:
        self.calls.append("robot_verify_grasp")
        return robot_result(self._last_grasp, "그리퍼가 비어 있음")

    def robot_deliver(self) -> dict:
        self.calls.append("robot_deliver")
        return robot_result(self.deliver_ok, "바구니 이동 실패")

    def robot_stop(self) -> dict:
        self.calls.append("robot_stop")
        return robot_result(self.stop_ok, "정지 명령 실패")

    def robot_moved(self) -> bool:
        return any(c.startswith("robot_") and c != "robot_stop" for c in self.calls)

    def delivered(self) -> bool:
        return "robot_deliver" in self.calls and self.deliver_ok


__all__ = ["TOOLS", "ToolSpec", "MockBackend", "simple_match", "feature_similarity"]
