"""실물 팔로워 관절값으로 가상 팔 그리기 (LF-18 · 11/11 변재원)

한줄 설명: 로봇 PC 의 읽기 전용 관절 조회(GET /v1/joints, 김건태 LF-21)를 관제탑 서버가 초당 최대 5번 읽어
/live·통합 시연 4번 '로봇 작업대'의 가상 SO-101 을 실제 팔로워 관절 그대로 움직인다. 관측이 없으면 단계 기록 따라가기
(agents/taught_mirror.py)로 돌아간다.

- 읽기만 한다: 로봇에 명령·arm·job·lease 를 보내지 않는다. 같은 Bearer 토큰(RemoteTowerRobot.request), 브라우저는 로봇 PC 를 부르지 않음
- 각도 맞추기: 로봇 PC 가 주는 degrees 는 Studio/LeRobot 관례(보정 범위 가운데 = 0°). 가상 팔은 공식 모델 관례(0° = 위팔 수직·
  아래팔 수평 'ㄱ' 자세, + = 앞·아래)라 관절마다 영점(+ 배율)을 더한다. 값(STUDIO_TO_SIM)은 11/11 보정값으로 바꾼 저장 자세 9개
  (pose_1~8_target · close)의 집게 끝이 가상 작업대의 그 칸·제출보관함에 오도록 맞춘 것 — 남는 차이 평균 약 28mm(그림용)
- 집게는 degrees 안에서도 0~100(%) 그대로
- 1초 넘은 관측·available:false·연결 실패 = 실시간 아님 → 이전 값을 새 관측으로 쓰지 않음

켜기: 원격 티칭 모드(TOWER_ROBOT_SEQUENCE=taught)에서 자동. 끄기 .env TOWER_LIVE_JOINTS=0
"""
from __future__ import annotations

import os
import threading
import time

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
# Studio 각도 → 가상 팔 각도: sim = studio × 배율 + 영점 (11/11 맞춤, 위 설명)
STUDIO_TO_SIM = {"shoulder_pan": (0.88, 2.5), "shoulder_lift": (1.0, 8.3), "elbow_flex": (1.0, -18.5),
                 "wrist_flex": (1.0, -14.1), "wrist_roll": (1.0, 0.0)}
# 위 영점은 칸 자세에 맞춘 것이라 접힌 원점에서는 덜 접혀 보인다(팔꿈치 약 78°) → 관측이 저장 자세 home 근처면
#   접힌 대기 자세(sim_world.REST_JOINTS, 실물 home 사진과 같은 모양)로 그린다
HOME_NEAR = 8.0                    # 위팔·팔꿈치·손목 normalized 차이가 모두 이 안이면 home 근처
FAST_S, SLOW_S = 0.2, 1.0          # 반환 중(또는 직후 10초) 초당 5번, 그 밖에는 초당 1번
FRESH_S = 1.5                      # 이 시간 안에 받은 관측만 '실시간'
BUSY_TAIL_S = 10.0


def to_sim(degrees: dict) -> dict | None:
    """로봇 PC degrees({관절.pos: 값}) → 가상 팔 관절(도, 집게 %) 또는 None(값이 모자람)"""
    if not isinstance(degrees, dict):
        return None
    from agents.sim_world import SO101_LIMITS
    out = {}
    for j in JOINTS:
        v = degrees.get(j + ".pos")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) > 1000:
            return None
        if j == "gripper":
            out[j] = round(max(0.0, min(100.0, float(v))), 1)
            continue
        k, o = STUDIO_TO_SIM[j]
        lo, hi = SO101_LIMITS[j]
        out[j] = round(max(lo - 30, min(hi + 30, float(v) * k + o)), 1)   # 그림이 뒤집히지 않을 만큼만 자름
    return out


class LiveJoints:
    """뒤에서 /v1/joints 를 읽어 세계의 팔(world.arm)에 실물 관절을 넣는다"""

    def __init__(self, robot, world, env: dict | None = None, clock=time.monotonic, sleep=time.sleep):
        self.robot, self.w = robot, world
        self.clock, self.sleep = clock, sleep
        self.busy_until = 0.0
        self.last_ok = None          # 마지막으로 받은 관측 시각(clock)
        self.last = None             # {"positions", "degrees", "read_at"}
        self.reason = ""
        self._stop = threading.Event()
        self._thread = None

    # ---------- 읽기 ----------
    def read_once(self) -> bool:
        """한 번 읽고 반영. 실시간 관측을 반영했으면 True"""
        try:
            r = self.robot.request("/v1/joints", timeout=1)
        except Exception as e:                      # 403·연결 실패·시간 초과 — 토큰·주소는 기록하지 않음
            self.reason = f"관절 조회 실패({type(e).__name__})"
            return False
        if not isinstance(r, dict) or r.get("available") is not True:
            self.reason = str((r or {}).get("reason") or "관측 없음")[:80] if isinstance(r, dict) else "응답 형식 오류"
            return False
        joints = to_sim(r.get("degrees"))
        if joints is None:
            self.reason = "각도(degrees) 없음 — 로봇 PC 보정 파일 확인"
            return False
        self.apply(joints, r)
        return True

    def apply(self, joints: dict, raw: dict) -> None:
        from agents.sim_world import REST_JOINTS, REST_REAL, so101_tip
        pos = raw.get("positions") if isinstance(raw.get("positions"), dict) else {}
        near = all(isinstance(pos.get(j + ".pos"), (int, float)) and abs(float(pos[j + ".pos"]) - REST_REAL[j]) <= HOME_NEAR
                   for j in ("shoulder_lift", "elbow_flex", "wrist_flex"))
        if near:
            joints = {**REST_JOINTS, "shoulder_pan": joints["shoulder_pan"], "wrist_roll": joints["wrist_roll"], "gripper": joints["gripper"]}
        arm = self.w.arm
        x, y, z = so101_tip(joints)
        arm.update(joints=joints, x=round(x, 1), y=round(y, 1), z=round(z, 1), gripper=joints["gripper"], rest=near)
        arm["live"] = {"read_at": str(raw.get("read_at") or "")[:40], "source": "follower",
                       "normalized": {k.split(".")[0]: round(float(v), 1) for k, v in pos.items()
                                      if isinstance(v, (int, float)) and not isinstance(v, bool)}}
        self.last_ok = self.clock()
        self.reason = ""
        self.w._touch()

    def fresh(self) -> bool:
        return self.last_ok is not None and self.clock() - self.last_ok <= FRESH_S

    def mark_busy(self) -> None:
        self.busy_until = self.clock() + 3600

    def mark_idle(self) -> None:
        self.busy_until = self.clock() + BUSY_TAIL_S

    # ---------- 뒤에서 돌기 ----------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="live-joints", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        fails = 0
        while not self._stop.is_set():
            ok = self.read_once()
            if not ok and not self.fresh() and self.w.arm.get("live"):
                self.w.arm["live"] = None                # 실시간이 끊김 → 단계 기록 따라가기로
                self.w._touch()
            fails = 0 if ok else min(fails + 1, 5)
            wait = FAST_S if self.clock() < self.busy_until else SLOW_S
            self.sleep(wait if ok else max(wait, min(5.0, 0.5 * fails)))


def enabled(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("TOWER_LIVE_JOINTS", "1")).strip().lower() not in ("0", "false", "no", "off")


__all__ = ["LiveJoints", "to_sim", "STUDIO_TO_SIM", "enabled"]
