"""키오스크 웹캠 노출 값 고르기 (LF-18 · 11/11 변재원) — .env TOWER_KIOSK_EXPOSURE 에 넣을 값 찾기

한줄 설명: 노출 값을 하나씩 바꿔 가며 같은 장면을 찍고, 하얗게 날아간 비율·밝기를 비교해 쓸 만한 값을 추천한다.

왜: 11/11 회색 펠트 위 사진에서 카메라 자동 노출이 화면을 밝게 올려 분홍·하늘색 핸드크림이 흰색으로 찍힘
(물건 픽셀의 40~87% 가 최댓값 255 근처 — 색 정보가 사라져 Qwen 도 색 측정도 맞출 수 없음).
LED 밝기를 3 → 10 으로 바꿔도 차이가 없던 것도 자동 노출이 다시 같은 밝기로 맞추기 때문(추정).

사용법 (저장소 폴더, .venv 켠 상태, **관제탑을 끈 상태** — 관제탑이 웹캠을 잡고 있으면 열리지 않음)
    1) 포토박스에 회색 펠트를 깔고 가장 잘 날아가는 물건(흰 폰 또는 하늘색 핸드크림)을 가운데 둔다
    2) python tools/camera_exposure.py                 # 카메라 0번, 값 auto,-4,-5,-6,-7,-8,-9
       python tools/camera_exposure.py --cam 1 --values auto,-5,-6,-7
    3) data/exposure_check/sheet.jpg 를 열어 물건 색이 가장 잘 보이는 값을 고른다(추천 값이 함께 나옴)
    4) .env 에 TOWER_KIOSK_EXPOSURE=고른값 → 관제탑을 다시 켠다
끝나면 카메라를 자동 노출로 되돌려 둔다(.env 를 비우면 예전과 같게).

화이트밸런스(11/11, 노출을 고른 뒤): 상자를 비우거나 펠트만 보이게 두고
    python tools/camera_exposure.py --exposure -6 --wb auto,4000,4600,5200,6000
    → 회색 펠트가 가장 회색으로(빨강·초록·파랑이 고르게) 찍히는 값 추천 → .env TOWER_KIOSK_WB=추천값
조명은 한 모드로 고정(11/11 흰색 권장) — 조명을 바꾸면 화이트밸런스를 다시 고른다.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLIP = 250            # 이 값 이상이면 '하얗게 날아간' 점으로 봄(0~255)
CLIP_OK = 0.001       # 화면 전체 대비 날아간 점이 이보다 적으면 통과
SETTLE_FRAMES = 25    # 값을 바꾼 뒤 버리는 장수(카메라가 새 노출로 바뀌는 시간)


def measure(frame) -> dict:
    """사진 한 장의 밝기 요약. 바닥 = 가장자리 띠의 가운데값, clipped = 화면 전체에서 하얗게 날아간 점의 비율,
    p99 = 가장 밝은 1% 의 밝기(255 에 붙으면 날아가기 직전).
    물건만 골라 세지 않는 까닭: 렌즈 가장자리가 어둡게 찍혀(주변부 감광) 바닥까지 물건으로 잡힘(11/11 빈 상자 사진에서 확인)"""
    import numpy as np
    lum = frame.astype(np.float32).mean(axis=2)
    h, w = lum.shape
    b = max(8, min(h, w) // 12)
    edge = np.concatenate([lum[:b].ravel(), lum[-b:].ravel(), lum[:, :b].ravel(), lum[:, -b:].ravel()])
    top = frame.max(axis=2)
    band = np.concatenate([frame[:b].reshape(-1, 3), frame[-b:].reshape(-1, 3),
                           frame[:, :b].reshape(-1, 3), frame[:, -b:].reshape(-1, 3)]).astype(np.float32)
    bgr = np.median(band, axis=0)
    cast = float((bgr.max() - bgr.min()) / max(1.0, bgr.mean()))    # 바닥(회색)의 색 치우침: 0 = 완전 회색
    return {"floor": round(float(np.median(edge)), 1), "mean": round(float(lum.mean()), 1),
            "clipped": round(float((top >= CLIP).mean()), 5), "p99": int(np.percentile(top, 99)),
            "cast": round(cast, 4), "floor_bgr": [int(x) for x in bgr]}


def recommend(rows: list[dict]):
    """날아간 점이 화면의 0.1% 미만이고(흰 폰이 화면의 약 13% → 폰 표면의 1% 안쪽) 바닥이 너무 어둡지 않은(60 이상) 값 중 가장 밝은 것.
    노출 값을 바꿔도 밝기가 거의 같으면 카메라가 고정을 무시하는 것 → None"""
    manual = [r for r in rows if r["value"] != "auto" and "m" in r]
    if len(manual) >= 2:
        levels = [r["m"]["mean"] for r in manual]
        if max(levels) - min(levels) < 8:
            return None, "노출 값을 바꿔도 밝기가 거의 같음 — 이 카메라(또는 열린 방식)가 노출 고정을 받아들이지 않는 것 같음"
    ok = [r for r in manual if r["m"]["clipped"] < CLIP_OK and r["m"]["floor"] >= 60]
    if not ok:
        return None, "날아간 점 0.1% 미만이면서 바닥 밝기 60 이상인 값이 없음 — 값 범위를 넓히거나 LED 밝기를 바꿔 다시"
    best = max(ok, key=lambda r: r["value"])           # 같은 조건이면 더 밝은(덜 음수) 값 — 어두운 물건(검정 폰)도 보이게
    return best["value"], "물건이 날아가지 않는 값 중 가장 밝은 값"


def recommend_wb(rows: list[dict]):
    """회색 펠트가 가장 회색인(색 치우침이 가장 작은) 고정값. 값을 바꿔도 치우침이 거의 같으면 카메라가 무시하는 것"""
    manual = [r for r in rows if r["value"] != "auto" and "m" in r]
    if not manual:
        return None, "시험한 고정값이 없음"
    casts = [r["m"]["cast"] for r in manual]
    if len(manual) >= 2 and max(casts) - min(casts) < 0.01:
        return None, "화이트밸런스 값을 바꿔도 색이 거의 같음 — 이 카메라가 화이트밸런스 고정을 받아들이지 않는 것 같음"
    best = min(manual, key=lambda r: r["m"]["cast"])
    return best["value"], f"회색 바닥의 색 치우침이 가장 작음({best['m']['cast'] * 100:.1f}%)"


def sheet(rows: list[dict], path: Path) -> None:
    """값별 사진을 한 장에 모아 저장(값·바닥 밝기·날아간 비율 글씨 포함)"""
    import cv2
    import numpy as np
    tiles = []
    for r in rows:
        if r.get("frame") is None:
            continue
        t = cv2.resize(r["frame"], (320, 240))
        m = r["m"]
        txt1 = f"{r.get('kind', 'exp')} {r['value']}"
        txt2 = f"floor {m['floor']:.0f} clip {m['clipped']*100:.2f}%"
        for y, s in ((22, txt1), (46, txt2)):
            cv2.putText(t, s, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(t, s, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(t)
    if not tiles:
        return
    cols = 4
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    cv2.imwrite(str(path), grid)


def parse_values(text: str, kind: str = "exp") -> list:
    from agents.kiosk_camera import EXPOSURE_MAX, EXPOSURE_MIN, WB_MAX, WB_MIN
    lo, hi = (WB_MIN, WB_MAX) if kind == "wb" else (EXPOSURE_MIN, EXPOSURE_MAX)
    out = []
    for s in text.split(","):
        s = s.strip().lower()
        if s == "auto":
            out.append("auto")
            continue
        try:
            v = float(s)
        except ValueError:
            raise SystemExit(f"값을 읽을 수 없음: {s!r} (예: auto,-5,-6,-7 · 화이트밸런스 auto,4600,5200)")
        if not lo <= v <= hi:
            raise SystemExit(f"범위 밖 값: {s} ({lo}~{hi})")
        out.append(int(v) if v.is_integer() else v)
    return out


def run(cam, values: list, out: Path, opener=None, settle: int = SETTLE_FRAMES, kind: str = "exp",
        exposure=None) -> list[dict]:
    """값마다: 카메라 열기 → 노출(kind='wb' 면 노출은 exposure 로 고정하고 화이트밸런스) 정하기 → settle 장 버리기 →
    한 장 저장·측정. 끝나면 자동으로 되돌림"""
    import cv2
    from agents.kiosk_camera import _open, apply_exposure, apply_wb, fit
    opener = opener or _open
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for v in values:
        cap = opener(cam)
        try:
            if cap is None or not cap.isOpened():
                rows.append({"value": v, "error": "카메라를 열 수 없음(관제탑이 켜져 있으면 끈 뒤 다시)"})
                continue
            if kind == "wb":
                apply_exposure(cap, exposure)
                st = apply_wb(cap, v)
            else:
                st = apply_exposure(cap, v)
            frame = None
            for _ in range(settle):
                ok, f = cap.read()
                if ok and f is not None:
                    frame = f
                time.sleep(0.03)
            if frame is None:
                rows.append({"value": v, "error": "영상이 들어오지 않음", "state": st})
                continue
            frame, _ = fit(frame)
            name = f"{kind}_{'auto' if v == 'auto' else str(v).replace('-', 'm')}.jpg"
            cv2.imwrite(str(out / name), frame)
            rows.append({"value": v, "kind": kind, "state": st, "m": measure(frame), "frame": frame, "file": name})
        finally:
            if cap is not None:
                try:
                    apply_exposure(cap, "auto")           # 다음 프로그램(관제탑)이 고정값을 물려받지 않게
                    if kind == "wb":
                        apply_wb(cap, "auto")
                    cap.release()
                except Exception:
                    pass
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="키오스크 웹캠 노출 값 고르기")
    ap.add_argument("--cam", default="0", help="OpenCV 카메라 번호(tools/list_cameras.py 로 확인, 기본 0)")
    ap.add_argument("--values", default="auto,-4,-5,-6,-7,-8,-9", help="시험할 노출 값(쉼표로, auto 포함 가능)")
    ap.add_argument("--wb", default="", help="화이트밸런스 시험(켈빈, 예 auto,4000,4600,5200,6000) — 이때 노출은 --exposure 로 고정")
    ap.add_argument("--exposure", default="auto", help="화이트밸런스 시험 중 쓸 노출 값(먼저 고른 값, 기본 auto)")
    a = ap.parse_args(argv)
    try:
        import cv2
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass
    cam = "fake" if a.cam == "fake" else int(a.cam)
    out = ROOT / "data" / "exposure_check"
    if a.wb:
        exp = parse_values(a.exposure)[0]
        rows = run(cam, parse_values(a.wb, "wb"), out, kind="wb", exposure=exp)
        print(f"{'값':>6} | 바닥 색(B,G,R)   | {'색 치우침':>8} | 카메라가 읽은 값   (노출 {exp})")
        for r in rows:
            if "error" in r:
                print(f"{str(r['value']):>6} | {r['error']}")
                continue
            m, st = r["m"], r.get("state") or {}
            print(f"{str(r['value']):>6} | {str(m['floor_bgr']):16s} | {m['cast'] * 100:7.1f}% | auto={st.get('auto')} wb={st.get('now')}")
        sheet(rows, out / "sheet_wb.jpg")
        best, why = recommend_wb(rows)
        print()
        print(f"추천 값 없음: {why}" if best is None else f"추천: TOWER_KIOSK_WB={best}  ({why})")
        print(f"사진 모음: {(out / 'sheet_wb.jpg').relative_to(ROOT)}")
        return 0
    rows = run(cam, parse_values(a.values), out)
    print(f"{'값':>6} | {'바닥':>5} | {'평균':>5} | {'밝은1%':>6} | {'날아간 점':>8} | 카메라가 읽은 값")
    for r in rows:
        if "error" in r:
            print(f"{str(r['value']):>6} | {r['error']}")
            continue
        m, st = r["m"], r.get("state") or {}
        print(f"{str(r['value']):>6} | {m['floor']:5.0f} | {m['mean']:5.0f} | {m['p99']:6d} | {m['clipped']*100:7.2f}% | "
              f"auto={st.get('auto')} exp={st.get('now')}")
    sheet(rows, out / "sheet.jpg")
    best, why = recommend(rows)
    print()
    if best is None:
        print(f"추천 값 없음: {why}")
    else:
        print(f"추천: TOWER_KIOSK_EXPOSURE={best}  ({why})")
    print(f"사진 모음: {(out / 'sheet.jpg').relative_to(ROOT)}")
    if os.name == "nt":
        print("사진 폴더 열기: explorer data\\exposure_check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
