"""관제탑을 켜기 전에 로봇 모드(실물 / 가상)를 한 줄로 알려 주는 도구 (11/13).

한줄 설명: 회수 버튼이 진짜 로봇을 움직이는지, 화면 속 가상 팔만 움직이는지 켜는 순간 알게 한다.
- 실물 로봇 모드: `.env` 에 TOWER_ROBOT_SEQUENCE=taught · TOWER_ROBOT_TARGET=db ·
  TOWER_ROBOT_PART=robot.remote_client:RemoteTowerRobot · TOWER_REMOTE_ROBOT_URL · TOWER_REMOTE_ROBOT_TOKEN 이 모두 있을 때
- 가상 로봇 모드: 위 값이 비어 있거나, `tools\\start_tower.bat ... sim` 으로 켰을 때(.env 는 그대로 두고 이번 실행만 가상)
- `python tools/robot_mode.py real` 은 실물 값이 빠져 있으면 빠진 이름을 알려 주고 끝냄(종료 코드 2) — 값 자체는 출력하지 않는다
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REAL_PART = "robot.remote_client:RemoteTowerRobot"
NEEDS = (("TOWER_ROBOT_SEQUENCE", "taught"), ("TOWER_ROBOT_TARGET", "db"), ("TOWER_ROBOT_PART", REAL_PART),
         ("TOWER_REMOTE_ROBOT_URL", None), ("TOWER_REMOTE_ROBOT_TOKEN", None))


def missing(env) -> list[str]:
    """실물 로봇 모드에 필요한데 비었거나 다른 값인 설정 이름(값은 돌려주지 않음)"""
    out = []
    for key, want in NEEDS:
        value = str(env.get(key) or "").strip()
        if not value:
            out.append(f"{key}(비어 있음)")
        elif want and (value.lower() if key == "TOWER_ROBOT_TARGET" else value) != want:
            out.append(f"{key}(실물은 {want})")
    return out


def decide(env) -> tuple[str, list[str]]:
    """('real' | 'sim' | 'broken', 빠진 설정). broken = 일부만 채워져 관제탑이 켜지지 않거나 반쯤 실물인 상태"""
    lack = missing(env)
    if not lack:
        return "real", []
    started = any(str(env.get(key) or "").strip() for key, _ in NEEDS[:3])
    return ("broken" if started else "sim"), lack


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    want = (argv[0] if argv else "").strip().lower()
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    mode, lack = decide(os.environ)
    if want == "real" and mode != "real":
        print("[ROBOT] 실물 로봇 모드로 켤 수 없습니다 — .env 에서 아래 값을 채운 뒤 다시 켜세요(값은 공유하지 않음)")
        for name in lack:
            print(f"         - {name}")
        return 2
    if mode == "real":
        print("[ROBOT] 실물 로봇 모드 — 본센터 키오스크 회수와 [직원 확인 후 진행]이 진짜 로봇을 움직입니다.")
        print("         로봇 옆에서 정지 수단을 확인한 사람이 있을 때만 쓰세요. 가상으로 켜려면: tools\\start_tower.bat lan sim")
    elif mode == "sim":
        print("[ROBOT] 가상 로봇 모드 — 로봇은 움직이지 않습니다(화면 속 가상 팔만)."
              + (" 이번 실행만 가상(sim)이고 .env 는 그대로입니다." if want == "sim" else ""))
    else:
        print("[ROBOT] 로봇 설정이 일부만 채워져 있습니다 — 실물로 쓰려면 아래를 채우고, 가상으로 켜려면 끝에 sim 을 붙이세요")
        for name in lack:
            print(f"         - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
