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
- 11/8 GPU 6GB 안전(교육원 RTX 3050): 사진 한 장마다 GPU 사용권 'qwen' 을 받고(로봇 VLA 와 겹치지 않게) → Ollama 모델을
  그래픽카드에서 내리고 → 분석 → Qwen 을 내린 뒤 사용권을 돌려준다(docs/design/architecture.md 3-4 "Qwen 은 상주시키지 않는다").
  사진마다 모델을 다시 올리는 3~6초가 더 들지만 키오스크 접수 번호는 바로 나가므로 사람이 기다리지 않는다.
  그래픽카드가 넉넉한 PC(8GB 이상)는 QWEN_KEEP_MODEL=1 또는 --keep-model 로 계속 올려 둘 수 있다
- 관제탑이 아직 안 켜졌으면 끝내지 않고 5초마다 다시 연결한다(--check 는 바로 끝)
- 11/11 색 측정(agents/color_measure.py): Qwen 이 끝나면 같은 사진을 숫자로 재서(회색 펠트를 기준으로 색 치우침 제거)
  결과 요약을 함께 보낸다. 측정이 '확실'할 때만 관제탑이 색을 그 값으로 바꾼다. 바닥이 펠트가 아니면 재지 않음.
  끄기: .env TOWER_COLOR_MEASURE=0. 측정이 실패해도 Qwen 결과는 그대로 보낸다
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

    def send(self, item_id: str, features: dict, color_measure: dict | None = None) -> dict:
        body = {"qwen": features, "confidence": CONFIDENCE}
        if color_measure:
            body["color_measure"] = color_measure
        return self._call("POST", f"/api/kiosk/items/{item_id}/features", body)

    def stage(self, item_id: str, stage: str, detail: str = "") -> None:
        """11/10 지금 어느 단계인지 관제탑에 알림(통합 시연 화면의 '사진 분석' 카드). 알림이 안 돼도 분석은 계속한다"""
        try:
            self._call("POST", f"/api/admin/intake/analysis/{item_id}", {"stage": stage, "detail": detail[:100]})
        except Exception:
            pass


def qwen_analyzer(max_edge: int = 512):
    """진짜 Qwen 분석 함수(첫 호출 때 모델을 올리고 계속 재사용 — qwen/src/model_loader.py lru_cache)"""
    from dataclasses import replace
    # 11/8 집 PC 첫 실행: vision 폴더를 맨 앞에 두면 vision/config.py(파일)가 qwen/config(폴더)를 가려
    # "No module named 'config.settings'" → qwen 폴더만 앞에 두고 vision 은 패키지 이름으로 부른다
    for p in (str(ROOT), str(ROOT / "qwen")):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    from config.settings import Settings
    from vision.item_features import extract_item_features
    settings = replace(Settings(), max_edge=max_edge, log_dir=ROOT / "qwen" / "logs" / "intake")

    def analyze(path: Path) -> dict:
        return extract_item_features(str(path), settings)
    return analyze


def release_qwen() -> None:
    """Qwen 을 그래픽카드에서 내린다(모델 캐시 비우기 → 메모리 반환). 실패해도 조용히"""
    try:
        from src.model_loader import load_model
        load_model.cache_clear()
    except Exception:
        pass
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def gpu_guarded(analyze, keep_model: bool = False, wait: float = 120.0, lease=None, unload=None, release=None):
    """사진 한 장 분석을 GPU 사용권 안에서: 사용권 받기 → Ollama 내리기 → 분석 → (keep_model 아니면) Qwen 내리기 → 돌려주기.
    사용권을 못 받으면 GpuBusy(관제탑 반환·로봇이 GPU 사용 중) → 실패로 세지 않고 다음 차례에 다시"""
    if lease is None:
        from agents.gpu_lease import gpu_lease
        lease = lambda: gpu_lease("qwen", wait=wait)  # noqa: E731
    if unload is None:
        from agents.local_model import unload_local_models as unload
    release = release or release_qwen

    def run(path: Path) -> dict:
        with lease():
            unload()
            try:
                return analyze(path)
            finally:
                if not keep_model:
                    release()
    return run


def color_measure_on() -> bool:
    return str(os.environ.get("TOWER_COLOR_MEASURE", "1")).strip().lower() not in ("0", "false", "no", "off")


def measure_color(path: Path, feats: dict) -> dict | None:
    """11/11 같은 사진의 색을 숫자로 잼 → 관제탑에 보낼 요약(실패하면 None — Qwen 결과만 보냄)"""
    if not color_measure_on():
        return None
    try:
        from agents.color_measure import measure, summary
        from agents.vision_adapter import CATEGORY
        return summary(measure(path, CATEGORY.get((feats or {}).get("category"))))
    except Exception:
        return None


def process_once(tower, analyze, tries: dict, log=print, root: Path | None = None, measurer=None) -> int:
    """대기 물건 한 번 처리 → 보낸 개수. tries: 접수 번호 → 실패 횟수(같은 사진을 끝없이 다시 돌리지 않게)"""
    sent = 0
    for row in tower.pending():
        iid = row.get("item_id")
        if not iid or tries.get(iid, 0) >= MAX_TRIES:
            continue
        started = time.perf_counter()
        notify = getattr(tower, "stage", None) or (lambda *a, **k: None)     # 11/10 화면에 단계 알림(없는 연결이면 건너뜀)
        try:
            notify(iid, "analyze")
            path = resolve_photo(row.get("photo_path") or "", root)
            feats = analyze(path)
            cm = (measurer or measure_color)(path, feats)
            if cm:
                tower.send(iid, feats, cm)
            else:
                tower.send(iid, feats)
        except Exception as e:
            if type(e).__name__ == "GpuBusy":               # 로봇이 GPU 사용 중 → 실패로 세지 않고 다음 차례에
                log(f"[대기] {iid} {str(e)[:120]}")
                notify(iid, "wait_gpu", "로봇이 그래픽카드를 쓰는 중 — 끝나면 다시")
                continue
            if not isinstance(e, (urllib.error.URLError, OSError, ValueError, RuntimeError, TypeError)):
                raise
            tries[iid] = tries.get(iid, 0) + 1
            log(f"[실패 {tries[iid]}/{MAX_TRIES}] {iid} {type(e).__name__}: {str(e)[:120]}")
            notify(iid, "fail", f"{type(e).__name__} ({tries[iid]}/{MAX_TRIES}번째)")
            continue
        tries.pop(iid, None)
        sent += 1
        mtxt = f" · 색 측정 {cm.get('color') or '-'}({'확실' if cm.get('sure') else '애매'})" if cm else ""
        log(f"[완료] {iid} {feats.get('category')} {feats.get('colors')}{mtxt} ({time.perf_counter() - started:.1f}초)")
    return sent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="키오스크 사진 → Qwen 특징 → 관제탑")
    ap.add_argument("--check", action="store_true", help="모델 없이 관제탑 연결·대기 목록만 확인하고 끝")
    ap.add_argument("--once", action="store_true", help="한 번만 처리하고 끝")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--max-edge", type=int, default=int(os.environ.get("QWEN_MAX_EDGE", "512")))
    ap.add_argument("--keep-model", action="store_true", help="Qwen 을 그래픽카드에 계속 올려 둠(8GB 이상 PC, 기본은 사진마다 내림)")
    args = ap.parse_args(argv)
    load_env()
    keep = args.keep_model or str(os.environ.get("QWEN_KEEP_MODEL") or "").strip().lower() in ("1", "true", "yes", "on")
    tower = Tower()
    while True:
        try:
            waiting = tower.pending()
            break
        except urllib.error.HTTPError as e:
            print(f"관제탑이 거절함(HTTP {e.code}) — 401 이면 .env 의 LF_ADMIN_API_KEY 를 확인하세요")
            return 2
        except (urllib.error.URLError, OSError) as e:
            print(f"관제탑에 연결할 수 없음({type(e).__name__}) — 관제탑을 먼저 켜고 TOWER_URL 을 확인하세요"
                  + ("" if args.check else " · 5초 뒤 다시 시도(끄기: Ctrl+C)"))
            if args.check:
                return 2
            try:
                time.sleep(5)
            except KeyboardInterrupt:
                print("작업자 종료")
                return 0
    print(f"관제탑 연결 OK · 사진 분석 대기 {len(waiting)}건 · 사진 폴더 {photo_root()}")
    if args.check:
        return 0
    analyze = gpu_guarded(qwen_analyzer(args.max_edge), keep_model=keep,
                          wait=float(os.environ.get("QWEN_GPU_WAIT") or 120))
    print("Qwen 준비(사진이 오면 GPU 사용권을 받아 모델을 올립니다" + (", 계속 올려 둠" if keep else ", 분석 뒤 내림")
          + ") — 끄기: Ctrl+C")
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
