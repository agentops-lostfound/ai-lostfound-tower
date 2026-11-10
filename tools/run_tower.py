"""관제탑 API 켜기 — 끌 때 반드시 꺼지게 하는 실행기 (LF-2, 11/10 변재원)

한줄 설명: `python -m uvicorn …` 과 똑같이 켜되, 서버가 멈춘 뒤 **프로그램이 남아 창이 먹통이 되는 일**이 없도록 마지막에 강제로 끝낸다.

왜: 11/10 교육원 PC 에서 Ctrl+C 를 누르면 "Finished server process" 까지 나온 뒤에도 파이썬이 끝나지 않아 터미널 탭이 멈췄다(두 번).
    서버는 이미 멈췄는데 뒤에서 돌던 일(웹캠 읽기 등)이 정리되지 않아 생긴 일로 본다(추정) — 그래서
    ① 열려 있는 웹캠을 먼저 놓고 ② 그래도 남는 것이 있어도 os._exit 로 프로그램을 끝낸다.
    서버가 멈추는 중에 걸려도(8초) 끝낸다.

사용: python tools/run_tower.py agents.api:app --host 127.0.0.1 --port 8100 …  (uvicorn 과 같은 인자, tools/start_tower.bat 가 부른다)
      코드가 바뀌면 다시 켜지는 개발 모드(--reload)는 예전처럼 python -m uvicorn 을 쓴다.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HARD_LIMIT_S = 8.0      # Ctrl+C 뒤 이 시간 안에 서버가 안 멈추면 그냥 끝낸다(uvicorn 의 연결 끊기 3초 + 여유)


def finish(code: int = 0) -> None:
    """웹캠을 놓고 프로그램을 끝낸다(남은 스레드를 기다리지 않음)"""
    try:
        from agents import kiosk_camera
        kiosk_camera.stop_all(1.5)
    except Exception:
        pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


def guard(seconds: float = HARD_LIMIT_S, exit_fn=finish) -> None:
    """끄라는 신호(Ctrl+C)를 받으면 시계를 켠다: seconds 뒤에도 살아 있으면 끝낸다. 원래 처리(uvicorn 의 정상 종료)는 그대로 부른다"""
    armed = threading.Event()

    def watchdog():
        time.sleep(seconds)
        print(f"[관제탑] {seconds:g}초 안에 꺼지지 않아 강제로 끝냅니다", flush=True)
        exit_fn(0)

    def wrap(sig):
        try:
            before = signal.getsignal(sig)
        except (ValueError, OSError):
            return

        def handler(signum, frame):
            if not armed.is_set():
                armed.set()
                threading.Thread(target=watchdog, daemon=True, name="tower-exit-guard").start()
            if callable(before):
                before(signum, frame)
            else:
                raise KeyboardInterrupt
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            wrap(getattr(signal, name))


def main(argv: list[str] | None = None) -> None:
    import uvicorn
    args = list(sys.argv[1:] if argv is None else argv)
    code = 0
    try:
        config_guard = os.environ.get("TOWER_EXIT_GUARD", "1") != "0"
        if config_guard:
            _serve_with_guard(uvicorn, args)
        else:
            uvicorn.main(args=args, standalone_mode=False)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
    except KeyboardInterrupt:
        code = 0
    except BaseException as e:                       # 켜다 실패: 이유를 보여 주고 끝낸다
        print(f"[관제탑] 실행 실패: {type(e).__name__}: {e}", flush=True)
        code = 1
    finish(code)


def _serve_with_guard(uvicorn, args: list[str]) -> None:
    """uvicorn 은 서버를 켤 때 자기 신호 처리를 건다 → 그 뒤에 시계를 덧씌우려고 서버가 켜진 직후(startup)에 guard 를 건다"""
    original = uvicorn.Server.startup

    async def startup(self, sockets=None):
        await original(self, sockets=sockets)
        guard()
    uvicorn.Server.startup = startup
    try:
        uvicorn.main(args=args, standalone_mode=False)
    finally:
        uvicorn.Server.startup = original


if __name__ == "__main__":
    main()
