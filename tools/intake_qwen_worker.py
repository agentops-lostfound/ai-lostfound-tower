"""키오스크 사진 → Qwen3-VL 특징 → 관제탑(LF-3, 11/7 변재원).

한줄 설명: 습득물 등록기계(키오스크)가 찍은 사진을 관제탑 PC 그래픽카드의 Qwen 으로 분석해, 물건 종류·색 같은 특징을
관제탑에 채워 넣는 상주 프로그램. 가상 시연(TOWER_SIM=1)에서는 특징이 들어오는 순간 회수 → 보관함 장면이 이어진다.

흐름(2초마다 반복)
1. GET  {TOWER_URL}/api/admin/intake/pending-photos   — 사진은 있는데 특징이 비어 있는 물건(관리자 키 필요 시 X-Admin-Key)
2. 사진 파일(TOWER_PHOTO_DIR 또는 저장소 data/ 아래 상대 경로)을 Qwen 으로 분석 — vision/item_features.py extract_item_features
3. POST {TOWER_URL}/api/kiosk/items/{접수 번호}/features  {"qwen": 특징, "confidence": 0.85}

실행(관제탑 PC, 저장소 폴더) — Qwen 전용 가상환경 파이썬으로:
    .\\.venv-qwen\\Scripts\\python.exe tools\\intake_qwen_worker.py
    (모델 없이 연결만 확인: --check)
- 관제탑과 같은 PC 에서 돈다(사진 파일을 직접 읽음). 사진·특징을 다른 곳으로 보내지 않는다
- 실패한 사진은 2번까지 다시 시도하고, 그래도 안 되면 건너뛴다(관제탑 화면에는 '사진 분석 결과 없음 — 직원 확인'으로 보임)
- .env 의 TOWER_URL(비움 = http://127.0.0.1:8100), LF_ADMIN_API_KEY(관리자 로그인을 켠 경우) 를 읽는다. 값은 출력하지 않는다
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_TRIES = 2
CONFIDENCE = 0.85


def load_env() -> None:
    sys.path.insert(0, str(ROOT))
    try:
        from tools.envfile import load_env as _load
        _load()
    except Exception:
        pass


def photo_root() -> Path:
    return Path(os.environ.get("TOWER_PHOTO_DIR") or ROOT / "data")


def resolve_photo(rel: str, root: Path | None = None) -> Path:
    """DB 의 상대 경로 → 실제 파일. 사진 폴더 밖(../ 등)은 거부"""
    root = (root or photo_root()).resolve()
    path = (root / rel).resolve()
    if root not in path.parents:
        raise ValueError("사진 경로가 사진 폴더 밖입니다")
    if not path.is_file():
        raise FileNotFoundError("사진 파일이 없습니다")
    return path


class Tower:
    """관제탑 주소 두 개만 부르는 작은 연결(표준 라이브러리만 — Qwen 가상환경에 패키지를 더 깔지 않게)"""

    def __init__(self, url: str | None = None, key: str | None = None, timeout: float = 10.0):
        self.url = (url or os.environ.get("TOWER_URL") or "http://127.0.0.1:8100").rstrip("/")
        self.key = key if key is not None else os.environ.get("LF_ADMIN_API_KEY", "")
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None):
        headers = {"content-type": "application/json"}
        if self.key:
            headers["x-admin-key"] = self.key
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode() or "null")

    def pending(self, limit: int = 5) -> list[dict]:
        return self._call("GET", f"/api/admin/intake/pending-photos?limit={limit}") or []

    def send(self, item_id: str, features: dict) -> dict:
        return self._call("POST", f"/api/kiosk/items/{item_id}/features", {"qwen": features, "confidence": CONFIDENCE})


def qwen_analyzer(max_edge: int = 512):
    """진짜 Qwen 분석 함수(첫 호출 때 모델을 올리고 계속 재사용 — qwen/src/model_loader.py lru_cache)"""
    from dataclasses import replace
    sys.path.insert(0, str(ROOT / "qwen"))
    sys.path.insert(0, str(ROOT / "vision"))
    from config.settings import Settings
    from item_features import extract_item_features
    settings = replace(Settings(), max_edge=max_edge, log_dir=ROOT / "qwen" / "logs" / "intake")

    def analyze(path: Path) -> dict:
        return extract_item_features(str(path), settings)
    return analyze


def process_once(tower, analyze, tries: dict, log=print, root: Path | None = None) -> int:
    """대기 물건 한 번 처리 → 보낸 개수. tries: 접수 번호 → 실패 횟수(같은 사진을 끝없이 다시 돌리지 않게)"""
    sent = 0
    for row in tower.pending():
        iid = row.get("item_id")
        if not iid or tries.get(iid, 0) >= MAX_TRIES:
            continue
        started = time.perf_counter()
        try:
            feats = analyze(resolve_photo(row.get("photo_path") or "", root))
            tower.send(iid, feats)
        except (urllib.error.URLError, OSError, ValueError, RuntimeError, TypeError) as e:
            tries[iid] = tries.get(iid, 0) + 1
            log(f"[실패 {tries[iid]}/{MAX_TRIES}] {iid} {type(e).__name__}: {str(e)[:120]}")
            continue
        tries.pop(iid, None)
        sent += 1
        log(f"[완료] {iid} {feats.get('category')} {feats.get('colors')} ({time.perf_counter() - started:.1f}초)")
    return sent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="키오스크 사진 → Qwen 특징 → 관제탑")
    ap.add_argument("--check", action="store_true", help="모델 없이 관제탑 연결·대기 목록만 확인하고 끝")
    ap.add_argument("--once", action="store_true", help="한 번만 처리하고 끝")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--max-edge", type=int, default=int(os.environ.get("QWEN_MAX_EDGE", "512")))
    args = ap.parse_args(argv)
    load_env()
    tower = Tower()
    try:
        waiting = tower.pending()
    except urllib.error.HTTPError as e:
        print(f"관제탑이 거절함(HTTP {e.code}) — 401 이면 .env 의 LF_ADMIN_API_KEY 를 확인하세요")
        return 2
    except (urllib.error.URLError, OSError) as e:
        print(f"관제탑에 연결할 수 없음({type(e).__name__}) — 관제탑을 먼저 켜고 TOWER_URL 을 확인하세요")
        return 2
    print(f"관제탑 연결 OK · 사진 분석 대기 {len(waiting)}건 · 사진 폴더 {photo_root()}")
    if args.check:
        return 0
    analyze = qwen_analyzer(args.max_edge)
    print("Qwen 준비(첫 사진에서 모델을 올립니다, 수십 초 걸릴 수 있음) — 끄기: Ctrl+C")
    tries: dict[str, int] = {}
    try:
        while True:
            try:
                process_once(tower, analyze, tries)
            except (urllib.error.URLError, OSError) as e:
                print(f"관제탑 연결 끊김({type(e).__name__}) — 다시 시도")
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("작업자 종료")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
