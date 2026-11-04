"""GPU 사용권(잠금) — LF-16 (11/4, 김건태 GPU 순서안 반영).

한줄 설명: 시연 PC 의 GPU(RTX 3050 6GB)는 한 번에 한 모델만 쓴다. GPU 를 쓰려는 프로그램(STT·Qwen·VLA·LLM 검토)은
           먼저 이 "열쇠"를 받고, 다 쓰면(모델을 내린 뒤) 돌려준다. 열쇠가 없으면 정해진 시간만 기다리고 포기한다.

순서(김건태 11/4): STT 입력 확정 → STT 해제 → 탑뷰 촬영·Qwen → Qwen 해제 → CPU 전처리·매칭 → 사전 접근·VLA 집기

쓰는 법 (각 모듈 코드, 표준 라이브러리만 써서 어느 .venv 에서나 import 됨)
    from agents.gpu_lease import gpu_lease, GpuBusy
    try:
        with gpu_lease("qwen", wait=120):          # 최대 120초 기다림
            model = load_model(); run(model)
            del model; torch.cuda.empty_cache()     # 열쇠를 돌려주기 전에 반드시 GPU 메모리를 비운다
    except GpuBusy as e:
        print(e)                                    # 예: "GPU 사용 중(vla, 35초째) — 120초 기다렸지만 받지 못함"

- 같은 PC 의 모든 프로그램이 같은 잠금 파일을 본다(기본: 임시 폴더 agentops_gpu.lock, 바꾸려면 .env GPU_LEASE_FILE)
- 운영체제 파일 잠금을 쓰므로 프로그램이 죽으면 열쇠가 자동으로 풀린다(남은 열쇠 때문에 영원히 막히지 않음)
- need_free_mb: 열쇠를 받은 뒤 GPU 남은 메모리가 이만큼 될 때까지 기다린다(앞 모델이 메모리를 안 비웠을 때 잡기). nvidia-smi 로 읽음
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

USERS = ("stt", "qwen", "vla", "reviewer", "test")


def default_path() -> Path:
    return Path(os.environ.get("GPU_LEASE_FILE") or Path(tempfile.gettempdir()) / "agentops_gpu.lock")


class GpuBusy(RuntimeError):
    """정해진 시간 안에 GPU 사용권을 받지 못함(또는 메모리가 비지 않음)."""

    def __init__(self, message: str, holder: dict | None = None):
        super().__init__(message)
        self.holder = holder


def _try_lock(fh) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _open(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o666)
    fh = os.fdopen(fd, "r+b")
    if os.fstat(fd).st_size == 0:      # Windows 잠금은 1바이트 구간을 잠그므로 내용이 있어야 함
        fh.write(b"\0")
        fh.flush()
    return fh


def _info_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".json")


def holder(path: Path | None = None) -> dict | None:
    """지금 열쇠를 가진 쪽 {user, pid, since, seconds} 또는 None. 잠금이 실제로 잡혀 있는지 확인하고 답한다."""
    path = Path(path) if path else default_path()
    try:
        fh = _open(path)
    except OSError:
        return None
    try:
        if _try_lock(fh):          # 잡을 수 있다 = 아무도 안 씀(죽은 프로그램이 남긴 정보는 무시)
            _unlock(fh)
            return None
    finally:
        fh.close()
    try:
        info = json.loads(_info_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"user": "알 수 없음"}
    if isinstance(info, dict) and info.get("since"):
        info["seconds"] = round(time.time() - float(info["since"]), 1)
    return info if isinstance(info, dict) and info.get("user") else {"user": "알 수 없음"}


def gpu_free_mb(runner=None) -> float | None:
    """nvidia-smi 로 GPU 남은 메모리(MB). 읽을 수 없으면 None."""
    try:
        if runner is None:
            def runner(cmd):
                return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
        out = runner(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"])
        return float(str(out).strip().splitlines()[0])
    except Exception:
        return None


class GpuLease:
    """with 문으로 쓰는 GPU 사용권. acquire() 실패하면 GpuBusy."""

    def __init__(self, user: str, wait: float = 60.0, path: Path | None = None, poll: float = 0.5,
                 need_free_mb: float | None = None, free_mb=gpu_free_mb, clock=time.monotonic, sleep=time.sleep):
        if user not in USERS:
            raise ValueError(f"user 는 {USERS} 중 하나")
        self.user, self.wait, self.poll = user, max(0.0, float(wait)), poll
        self.path = Path(path) if path else default_path()
        self.need_free_mb, self.free_mb = need_free_mb, free_mb
        self.clock, self.sleep = clock, sleep
        self._fh = None

    def acquire(self) -> "GpuLease":
        fh = _open(self.path)
        deadline = self.clock() + self.wait
        while not _try_lock(fh):
            if self.clock() >= deadline:
                fh.close()
                h = holder(self.path)
                who = f"{h.get('user')}, {int(h.get('seconds', 0))}초째" if h else "알 수 없음"
                raise GpuBusy(f"GPU 사용 중({who}) — {int(self.wait)}초 기다렸지만 받지 못함", h)
            self.sleep(self.poll)
        self._fh = fh
        try:
            _info_path(self.path).write_text(json.dumps({"user": self.user, "pid": os.getpid(), "since": time.time()}),
                                             encoding="utf-8")
        except OSError:
            pass
        if self.need_free_mb:
            while True:
                free = self.free_mb()
                if free is None or free >= self.need_free_mb:   # 못 읽으면 막지 않음(nvidia-smi 없는 PC)
                    break
                if self.clock() >= deadline:
                    self.release()
                    raise GpuBusy(f"GPU 메모리가 비지 않음(남은 {int(free)}MB < 필요 {int(self.need_free_mb)}MB) — "
                                  "앞 모델이 메모리를 비웠는지 확인")
                self.sleep(self.poll)
        return self

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            _info_path(self.path).write_text("{}", encoding="utf-8")
        except OSError:
            pass
        _unlock(self._fh)
        self._fh.close()
        self._fh = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    def __enter__(self) -> "GpuLease":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


def gpu_lease(user: str, **kw) -> GpuLease:
    return GpuLease(user, **kw)


def lease_from_env(env: dict | None = None):
    """관제탑용: TOWER_GPU_LEASE=0 이면 None(끔). 아니면 user → GpuLease 를 만드는 함수.
    TOWER_GPU_WAIT(기본 60초), TOWER_GPU_FREE_MB(기본 없음 = 메모리 확인 안 함)."""
    env = os.environ if env is None else env
    if str(env.get("TOWER_GPU_LEASE") or "1").strip().lower() in ("0", "false", "no", "off"):
        return None

    def num(key, default):
        try:
            return float(str(env.get(key) or default))
        except ValueError:
            return float(default) if default is not None else None
    wait = num("TOWER_GPU_WAIT", 60)
    free = num("TOWER_GPU_FREE_MB", 0) or None
    return lambda user: GpuLease(user, wait=wait, need_free_mb=free)


__all__ = ["GpuLease", "GpuBusy", "gpu_lease", "holder", "gpu_free_mb", "lease_from_env", "default_path", "USERS"]
