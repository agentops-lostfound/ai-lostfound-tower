"""실물 로봇팔을 따라 움직이는 가상 팔 (LF-18 · 11/11 변재원)

한줄 설명: 실물 원격 티칭 모드에서 로봇 PC 가 보내는 단계 기록(11단계마다 '이동 시작'·'도착')을 받아, /live·통합 시연 4번
'로봇 작업대'의 가상 SO-101 이 같은 자리로 같은 시간에 움직이게 한다. 들고 있는 물건도 집기·내려놓기 단계에 맞춰 옮긴다.

왜: 11/10 원격 티칭 연결 뒤 화면의 가상 팔은 원점에 멈춰 있었다(실시간 관절값이 없어 그림을 껐음). 물건도 보관 칸에 남아 보였다.
    로봇 PC 는 관절값을 계속 보내지 않지만, 단계마다 자세 이름(pose_1_target 등)과 시작·도착을 알려 준다.

어떻게
- 자세 이름 → 작업대 위치: pose_N(접근)·pose_N_open·_return = 그 칸 위(HOVER_Z) · pose_N_target·_close = 그 칸 바닥(PICK_Z)
  · outlet_return* = 제출보관함 위 · close*·open = 제출보관함 안(DROP_Z) · home = 원점. 칸은 robot/config/pick_sequences.json(pose_N → 칸)
- 집게 열림 = 저장 자세 파일(outputs/robot_panel_live/poses.json)의 gripper 값(0~100, 실물과 같은 값)
- '이동 시작' → 로봇 PC 의 이동 시간(TOWER_ROBOT_MOVE_SECONDS, 기본 3초) 동안 부드럽게 이동(뒤에서, 원격 연결을 막지 않음)
  · '도착' → 그 자리로 딱 맞춤. pose_N_close 도착 = 물건을 집게로 · open 도착 = 제출보관함으로
- 관절 각도 막대는 가상 팔의 계산 값(실제 관절값이 아님). 실물 저장 자세 값(normalized)은 따로 보여 준다(arm.real)

한계: 실제 관절을 실시간으로 읽는 것이 아니라 단계 기록을 따른다 — 한 단계 안의 실제 궤적·속도와는 다를 수 있다.
     로봇 PC 가 관절값을 내보내면(Studio 관측) 그 값으로 바꿀 수 있다(docs/design/studio-coordinate-bridge.md).
이 파일은 그림만 바꾼다. 로봇에 명령을 보내지 않고, 단계 기록 검사(agents/taught_return.py)에 끼어들지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def pose_slots(path: Path | None = None) -> dict[str, str]:
    """approach 자세 이름 → 칸 번호. 예: {'pose_1': 'R1-1', …}"""
    data = _load_json(path or ROOT / "robot" / "config" / "pick_sequences.json") or {}
    out = {}
    for prof in (data.get("sequences") or {}).values():
        if isinstance(prof, dict) and isinstance(prof.get("approach_pose"), str) and isinstance(prof.get("slot_id"), str):
            out[prof["approach_pose"]] = prof["slot_id"]
    return out


def pose_values(path: Path | None = None) -> dict[str, dict]:
    """저장 자세 이름 → {관절.pos: normalized 값}"""
    data = _load_json(path or ROOT / "outputs" / "robot_panel_live" / "poses.json") or {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


class TaughtMirror:
    """원격 로봇 부품의 robot_run_sequence 에 씌워(wrap) 단계 기록을 가상 팔로 옮긴다"""

    def __init__(self, world, env: dict | None = None, slots: dict | None = None, poses: dict | None = None):
        from agents import sim_world as sw
        self.w, self.sw = world, sw
        env = os.environ if env is None else env
        try:
            self.seconds = max(0.5, min(10.0, float(env.get("TOWER_ROBOT_MOVE_SECONDS") or 3)))
        except ValueError:
            self.seconds = 3.0
        self.slots = pose_slots() if slots is None else slots
        self.poses = pose_values() if poses is None else poses
        self.item = None
        self._gen = 0
        self._lock = threading.Lock()

    # ---------- 자세 이름 → 작업대 위치 ----------
    def place(self, pose: str) -> dict | None:
        """{'x','y','z','gripper','where'} 또는 None(모르는 자세 — 위치는 그대로)"""
        sw = self.sw
        grip = self._grip(pose)
        if pose == "home":
            return {"x": sw.HOME_MM[0], "y": sw.HOME_MM[1], "z": sw.HOME_Z, "gripper": grip, "where": "원점"}
        m = re.fullmatch(r"(pose_\d+)(?:_(open|target|close|return))?", pose)
        if m:
            slot = self.slots.get(m.group(1))
            if slot not in sw.SLOT_IDS:
                return None
            x, y = sw.SLOTS_MM[sw.SLOT_IDS.index(slot)]
            low = m.group(2) in ("target", "close")
            return {"x": x, "y": y, "z": sw.PICK_Z if low else sw.HOVER_Z, "gripper": grip,
                    "where": f"{slot} 칸 " + ("바닥" if low else "위")}
        bx, by = sw.BASKET_MM
        if pose.startswith("outlet_return"):
            return {"x": bx, "y": by, "z": sw.HOVER_Z, "gripper": grip, "where": "제출보관함 위"}
        if re.fullmatch(r"(close|open)(_\w+)?", pose):
            return {"x": bx, "y": by, "z": sw.DROP_Z, "gripper": grip, "where": "제출보관함 안"}
        return None

    def _grip(self, pose: str):
        v = (self.poses.get(pose) or {}).get("gripper.pos")
        return max(0.0, min(100.0, float(v))) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    # ---------- 단계 기록 ----------
    def begin(self, target: dict) -> None:
        self.item = target.get("item_id") if isinstance(target, dict) else None
        with self.w._lock:
            self.w.arm.update(stopped=False, target=self.item)

    def event(self, ev: dict) -> None:
        """로봇 PC 단계 기록 하나. 절대 예외를 내지 않는다(그림이 반환 흐름을 막지 않게)"""
        try:
            self._event(ev)
        except Exception:
            pass

    def _event(self, ev: dict) -> None:
        if not isinstance(ev, dict):
            return
        pose, kind = str(ev.get("pose_name") or ""), ev.get("event")
        i, n = ev.get("index"), ev.get("total")
        goal = self.place(pose)
        state = "도착" if kind == "stage_arrived" else "이동 중"
        arm = self.w.arm
        arm["real"] = {"pose": pose, "index": i, "total": n, "state": state,
                       "values": {k.split(".")[0]: round(float(v), 1) for k, v in (self.poses.get(pose) or {}).items()
                                  if isinstance(v, (int, float))}}
        arm["phase"] = f"실물 {i}/{n} · {pose} · {state}" + (f" ({goal['where']})" if goal else "")
        with self._lock:
            self._gen += 1
            gen = self._gen
        if goal is None:
            self.w._touch()
            return
        if kind == "stage_started":
            threading.Thread(target=self._glide, args=(goal, gen), daemon=True).start()
            return
        self._set(goal)
        if kind == "stage_arrived":
            self._carry(pose)

    def _glide(self, goal: dict, gen: int) -> None:
        arm = self.w.arm
        start = {k: float(arm[k]) for k in ("x", "y", "z", "gripper")}
        end = {k: (start[k] if goal.get(k) is None else float(goal[k])) for k in start}
        steps = max(6, int(self.seconds * 8))
        for s in range(1, steps + 1):
            if self._gen != gen:                      # 다음 기록(도착·다음 단계)이 오면 그만
                return
            t = s / steps
            t = t * t * (3 - 2 * t)
            self._set({k: start[k] + (end[k] - start[k]) * t for k in start})
            time.sleep(self.seconds / steps * 0.95)    # 실물보다 조금 먼저 닿게(도착 기록에서 맞춤)

    def _set(self, goal: dict) -> None:
        arm = self.w.arm
        for k in ("x", "y", "z", "gripper"):
            if goal.get(k) is not None:
                arm[k] = round(float(goal[k]), 1)
        arm["joints"] = self.sw.so101_joints(arm["x"], arm["y"], arm["z"], arm["gripper"])
        self.w._touch()

    def _carry(self, pose: str) -> None:
        """집기·내려놓기 단계에 맞춰 물건 위치를 옮김(그림·가상 세계). 반환 성공 여부는 반환 흐름이 따로 정한다"""
        iid, w, sw = self.item, self.w, self.sw
        if not iid or iid not in w.items:
            return
        if re.fullmatch(r"pose_\d+_close", pose) and w.items[iid].get("loc") == sw.LOC_BIN:
            w.move(iid, sw.LOC_GRIPPER)
            w.arm["holding"] = iid
        elif pose == "open" and w.items[iid].get("loc") == sw.LOC_GRIPPER:
            w.move(iid, sw.LOC_BASKET)
            w.arm["holding"] = None
        w._touch()

    def end(self, result) -> None:
        with self._lock:
            self._gen += 1
        arm = self.w.arm
        ok = isinstance(result, dict) and result.get("ok") is True
        arm["target"] = None
        if ok:
            arm["phase"] = "실물 티칭 완료 · 원점(직원 확인 대기)"
        else:
            why = str(result.get("reason") or "")[:60] if isinstance(result, dict) else ""
            arm["phase"] = "실물 시퀀스 중단" + (f" · {why}" if why else "") + " — 현장 확인"
        self.w._touch()

    def stopped(self) -> None:
        with self._lock:
            self._gen += 1
        self.w.arm["phase"] = "실물 정지 요청 · 현장 확인"
        self.w._touch()

    def homed(self, result) -> None:
        if isinstance(result, dict) and result.get("ok") is True:
            self._set(self.place("home"))
            self.w.arm["phase"] = "실물 원점 복귀"
            self.w.arm["real"] = {"pose": "home", "index": None, "total": None, "state": "도착", "values": {}}
            self.w._touch()


def attach(robot, world, env: dict | None = None) -> TaughtMirror | None:
    """원격 로봇 부품의 robot_run_sequence·robot_stop·robot_home 에 가상 팔 따라 움직이기를 씌움.
    로봇 부품의 결과·예외·단계 검사는 그대로(원래 progress 를 먼저 부르고, 그다음 그림)"""
    run = getattr(robot, "robot_run_sequence", None)
    if not callable(run):
        return None
    m = TaughtMirror(world, env)

    def robot_run_sequence(target, progress=None):
        m.begin(target)

        def both(ev):
            if progress is not None:
                progress(ev)                        # 단계 순서 검사가 먼저(틀리면 여기서 예외 → 원래대로 중단)
            m.event(ev)
        result = None
        try:
            result = run(target, progress=both)
            return result
        finally:
            m.end(result)
    robot.robot_run_sequence = robot_run_sequence
    stop, home = getattr(robot, "robot_stop", None), getattr(robot, "robot_home", None)
    if callable(stop):
        def robot_stop():
            m.stopped()
            return stop()
        robot.robot_stop = robot_stop
    if callable(home):
        def robot_home():
            r = home()
            m.homed(r)
            return r
        robot.robot_home = robot_home
    return m


__all__ = ["TaughtMirror", "attach", "pose_slots", "pose_values"]
