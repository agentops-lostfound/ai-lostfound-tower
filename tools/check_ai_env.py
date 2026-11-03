"""AI 관제탑 환경 점검 — LF-14~17 (docs/design/ai-environment.md).

한줄 설명: 이 PC에서 메인 AI·LLM 검토·MCP·디스코드 알림이 돌아갈 준비가 됐는지 한 번에 확인한다.

사용법 (저장소 폴더, .venv 켠 상태)
    python tools/check_ai_env.py            # 점검만(아무것도 설치·전송하지 않음)
    python tools/check_ai_env.py --no-ollama   # Ollama 확인을 건너뜀(Ollama 없는 PC)

- 결과: ✅ 통과 / ⚠️ 없어도 시험은 돌지만 기능 일부가 꺼짐 / ❌ 고쳐야 함. ❌가 하나라도 있으면 종료 코드 1
- 비밀값은 출력하지 않는다. .env 는 키가 채워졌는지만 본다(값·주소는 화면에 안 나옴)
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "✅", WARN: "⚠️", FAIL: "❌"}
MIN_PY = (3, 11)
DEFAULT_MODEL = "qwen3-vl:4b-instruct"

# 패키지 이름 → (없을 때 등급, 무엇이 꺼지나)
PACKAGES = {
    "langgraph": (WARN, "LangGraph판 흐름(agents/graph.py). 일반 흐름·시험은 돌아감"),
    "mcp": (WARN, "MCP 서버(agents/mcp_server.py)"),
    "fastapi": (WARN, "관제탑 API(agents/api.py) — 화면이 HTTP로 부를 수 없음"),
    "uvicorn": (WARN, "관제탑 API 실행기"),
    "psycopg": (WARN, "DB 부품·반환 기록(PostgreSQL) — TOWER_DB=1 불가"),
    "numpy": (WARN, "비전 채점 일부"),
}
WEBHOOK_KEYS = ["DISCORD_WEBHOOK_PROGRESS", "DISCORD_WEBHOOK_ALERT", "DISCORD_WEBHOOK_SCORE"]


@dataclass
class Check:
    name: str
    level: str
    detail: str

    def line(self) -> str:
        return f"{MARK[self.level]} {self.name}: {self.detail}"


def check_python(version: tuple = tuple(sys.version_info[:3])) -> Check:
    v = ".".join(str(x) for x in version[:3])
    if tuple(version[:2]) >= MIN_PY:
        return Check("Python", OK, v)
    return Check("Python", FAIL, f"{v} — 3.11 이상 필요")


def check_packages(importer: Callable[[str], object] = importlib.import_module) -> list[Check]:
    out = []
    for name, (level, what) in PACKAGES.items():
        try:
            mod = importer(name)
            out.append(Check(f"패키지 {name}", OK, getattr(mod, "__version__", "설치됨")))
        except Exception:   # 없음(ImportError) + 설치가 깨져 불러오다 실패한 경우
            out.append(Check(f"패키지 {name}", level, f"없음 → 꺼지는 것: {what} (pip install -r agents/requirements.txt)"))
    return out


def check_env(env: dict, env_file_exists: bool) -> list[Check]:
    """키가 채워졌는지만 본다. 값은 돌려주지 않는다."""
    out = []
    if not env_file_exists:
        out.append(Check(".env 파일", FAIL, "없음 → copy .env.example .env 후 값 채우기"))
    else:
        out.append(Check(".env 파일", OK, "있음"))
    filled = lambda k: bool(str(env.get(k, "")).strip())
    per_channel = [k for k in WEBHOOK_KEYS if filled(k)]
    if len(per_channel) == len(WEBHOOK_KEYS):
        out.append(Check("디스코드 웹후크", OK, "채널 3곳 모두 설정"))
    elif filled("DISCORD_WEBHOOK_URL"):
        missing = [k.split("_")[-1].lower() for k in WEBHOOK_KEYS if not filled(k)]
        out.append(Check("디스코드 웹후크", WARN, f"공용 웹후크로 대신 보냄(채널별 없음: {', '.join(missing)})"))
    else:
        out.append(Check("디스코드 웹후크", WARN, "없음 → 알림은 화면에만(--send 불가)"))
    model = str(env.get("MAIN_AI_MODEL", "")).strip()
    if not model:
        out.append(Check("MAIN_AI_MODEL", WARN, f"비어 있음 → 기본값 {DEFAULT_MODEL} 사용"))
    elif model == "qwen3-vl:4b":
        out.append(Check("MAIN_AI_MODEL", FAIL, "qwen3-vl:4b 는 생각 전용판(답마다 약 10초) → qwen3-vl:4b-instruct 로 바꾸기"))
    else:
        out.append(Check("MAIN_AI_MODEL", OK, model))
    return out


def _fetch_tags(url: str, timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(f"{url.rstrip('/')}/api/tags", timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def check_ollama(url: str, model: str, fetch: Callable[[str], dict] = _fetch_tags) -> list[Check]:
    try:
        data = fetch(url)
    except Exception as e:  # 꺼져 있음·주소 틀림
        return [Check("Ollama", WARN, f"응답 없음({type(e).__name__}) → LLM 검토를 켜면 모든 반환이 직원 확인. Ollama 실행 후 다시 점검")]
    names = [m.get("name", "") for m in data.get("models", [])]
    out = [Check("Ollama", OK, f"실행 중 · 모델 {len(names)}개")]
    want = model if ":" in model else f"{model}:latest"
    if want in names:
        out.append(Check("메인 AI 모델", OK, model))
    else:
        out.append(Check("메인 AI 모델", FAIL, f"{model} 없음 → ollama pull {model}"))
    return out


def check_db_port(host: str = "127.0.0.1", port: int = 5434, opener: Callable | None = None) -> Check:
    """팀 DB(docker compose) 포트가 열려 있는지만 본다(로그인·비밀번호는 쓰지 않음)."""
    import socket
    opener = opener or (lambda: socket.create_connection((host, port), timeout=2))
    try:
        opener().close()
        return Check("팀 DB(PostgreSQL)", OK, f"{host}:{port} 열림")
    except Exception as e:
        return Check("팀 DB(PostgreSQL)", WARN, f"{host}:{port} 응답 없음({type(e).__name__}) → docker compose up -d (TOWER_DB=1 일 때만 필요)")


DB_NAME = "팀 DB(PostgreSQL)"
TEAM_DB_MAJOR = 16   # docker-compose.yml 의 pgvector/pgvector:pg16


def _flag(env: dict, key: str) -> bool:
    return str(env.get(key, "")).strip().lower() in ("1", "true", "yes", "on")


def check_db(env: dict, connect: Callable | None = None) -> Check:
    """DATABASE_URL 로 실제 접속해 '우리 팀 DB 가 맞는지'까지 본다(비밀번호·주소는 출력하지 않음).

    포트만 열려 있는지 보면 같은 포트를 쓰는 다른 PostgreSQL(예: 수업용 18)을 팀 DB 로 착각한다(11/3 실제로 겪음).
    TOWER_DB=1 이면 실패를 ❌, 아니면 ⚠️ 로 낸다.
    """
    from urllib.parse import urlsplit
    bad = FAIL if _flag(env, "TOWER_DB") else WARN
    dsn = str(env.get("DATABASE_URL", "")).strip()
    if not dsn:
        return Check(DB_NAME, bad, "DATABASE_URL 비어 있음 → .env.example 처럼 채우기 (TOWER_DB=1 일 때 필요)")
    u = urlsplit(dsn)
    where = f"{u.hostname}:{u.port or 5432}"
    if connect is None:
        try:
            import psycopg
        except ImportError:
            return Check(DB_NAME, bad, "psycopg 없음 → pip install -r agents/requirements.txt 후 다시 점검")
        connect = lambda d: psycopg.connect(d, connect_timeout=3)  # noqa: E731
    try:
        with connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            major = int(str(cur.fetchone()[0])[:-4] or 0)
            cur.execute("SELECT to_regclass('public.item') IS NOT NULL")
            has_item = bool(cur.fetchone()[0])
            count = None
            if has_item:
                cur.execute("SELECT count(*) FROM item")
                count = cur.fetchone()[0]
    except Exception as e:
        msg = str(e).lower()
        if "password" in msg or "28p01" in msg:
            why = "비밀번호 거절 → 다른 PostgreSQL 에 접속했거나(포트 확인: docker port lostfound-db) .env 비밀번호가 DB 를 처음 만들 때와 다름"
        elif "does not exist" in msg:
            why = "DB 또는 사용자 이름이 없음 → 다른 PostgreSQL 에 접속했을 수 있음(포트 확인: docker port lostfound-db)"
        elif "timeout" in msg or "refused" in msg or "could not connect" in msg:
            why = "응답 없음 → Docker Desktop 켜고 docker compose up -d"
        else:
            why = f"접속 실패({type(e).__name__})"
        return Check(DB_NAME, bad, f"{where} {why}")
    if major and major != TEAM_DB_MAJOR:
        return Check(DB_NAME, bad, f"{where} 에 PostgreSQL {major} 이 답함 → 팀 DB(16)가 아님. 포트 확인: docker port lostfound-db")
    if not has_item:
        return Check(DB_NAME, bad, f"{where} 접속됨, 그런데 item 표가 없음 → 팀 DB 가 아니거나 schema.sql 이 안 들어감")
    return Check(DB_NAME, OK, f"{where} 접속됨 · PostgreSQL {major} · 물건 {count}개")


def check_gpu(runner: Callable[[list[str]], str] | None = None) -> Check:
    if runner is None:
        if not shutil.which("nvidia-smi"):
            return Check("GPU", WARN, "nvidia-smi 없음 → GPU 확인 불가(CPU면 LLM이 많이 느림)")
        runner = lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    try:
        line = runner(["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"]).strip()
        name, total, used = [x.strip() for x in line.splitlines()[0].split(",")]
        free_gb = (float(total) - float(used)) / 1024
        level = OK if free_gb >= 3.5 else WARN
        tip = "" if level == OK else " → Qwen3-VL-4B(약 3.3GB)와 다른 모델을 함께 올리지 않기"
        return Check("GPU", level, f"{name} · 남은 메모리 {free_gb:.1f}GB{tip}")
    except Exception as e:
        return Check("GPU", WARN, f"읽기 실패({type(e).__name__})")


def run_checks(skip_ollama: bool = False) -> list[Check]:
    from tools.envfile import REPO_ROOT, load_env
    env_path = REPO_ROOT / ".env"
    load_env(env_path)
    env = dict(os.environ)
    checks = [check_python(), *check_packages(), *check_env(env, env_path.is_file())]
    if not skip_ollama:
        model = str(env.get("MAIN_AI_MODEL", "")).strip() or DEFAULT_MODEL
        checks += check_ollama(env.get("OLLAMA_URL") or "http://localhost:11434", model)
    checks.append(check_db(env))
    checks.append(check_gpu())
    return checks


def summary(checks: list[Check]) -> str:
    n = {lv: sum(c.level == lv for c in checks) for lv in (OK, WARN, FAIL)}
    return f"통과 {n[OK]} · 주의 {n[WARN]} · 고칠 것 {n[FAIL]}"


def _utf8_stdout() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="AI 관제탑 환경 점검")
    ap.add_argument("--no-ollama", action="store_true", help="Ollama 확인 건너뛰기")
    a = ap.parse_args(argv)
    checks = run_checks(skip_ollama=a.no_ollama)
    for c in checks:
        print(c.line())
    print(summary(checks))
    return 1 if any(c.level == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
