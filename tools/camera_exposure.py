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

11/11 교육원 웹캠은 OpenCV 노출 명령을 받지 않음(읽은 값 -1 = 지원 안 함, 값을 바꿔도 밝기 같음). 그럴 때:
    python tools/camera_exposure.py --props     # 이 웹캠이 받아들이는 설정 목록(DirectShow·Media Foundation 각각)
    python tools/camera_exposure.py --dialog    # 웹캠 드라이버 설정 창 + 미리보기(날아간 점 % 실시간) — 손으로 바꿔 보기
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
    if manual and all((r.get("state") or {}).get("now") == -1 for r in manual):
        return None, "카메라가 노출 값을 -1(지원 안 함)로 돌려줌 — OpenCV 로는 못 바꿈. --props 로 지원 목록, --dialog 로 드라이버 설정 창을 열어 보기"
    if len(manual) >= 2:
        levels = [r["m"]["mean"] for r in manual]
        if max(levels) - min(levels) < 8:
            return None, "노출 값을 바꿔도 밝기가 거의 같음 — 이 카메라(또는 열린 방식)가 노출 고정을 받아들이지 않는 것 같음(--dialog 로 드라이버 설정 창 열어 보기)"
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
    if all((r.get("state") or {}).get("now") == -1 for r in manual):
        return None, "카메라가 화이트밸런스 값을 -1(지원 안 함)로 돌려줌 — --dialog 로 드라이버 설정 창 열어 보기"
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
            from agents.kiosk_camera import is_dark
            frame, n = None, 0
            while n < settle * 3:                         # 다시 연 카메라는 처음 몇십 장이 까말 수 있음 → 밝은 영상이 settle 장 올 때까지
                ok, f = cap.read()
                n += 1
                if ok and f is not None and not is_dark(f):
                    frame = f
                    if n >= settle:
                        break
                time.sleep(0.03)
            if frame is None:
                rows.append({"value": v, "error": "영상이 까맘(카메라가 아직 준비 안 됨 — 다시 실행)", "state": st})
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


PROPS = ["AUTO_EXPOSURE", "EXPOSURE", "GAIN", "BRIGHTNESS", "CONTRAST", "SATURATION", "GAMMA", "SHARPNESS",
         "BACKLIGHT", "AUTO_WB", "WB_TEMPERATURE", "WHITE_BALANCE_BLUE_U", "HUE"]


def read_props(cap) -> dict:
    """카메라가 돌려주는 설정 값(-1 = 이 방식으로는 지원 안 함)"""
    import cv2
    out = {}
    for name in PROPS:
        pid = getattr(cv2, "CAP_PROP_" + name, None)
        if pid is None:
            continue
        try:
            out[name] = float(cap.get(pid))
        except Exception:
            out[name] = None
    return out


def show_props(cam) -> int:
    """DirectShow·Media Foundation 으로 각각 열어 지원 설정을 보여 줌(윈도우가 아니면 기본 방식 하나)"""
    import cv2
    backends = [("DirectShow", cv2.CAP_DSHOW), ("Media Foundation", cv2.CAP_MSMF)] if os.name == "nt" else [("기본", cv2.CAP_ANY)]
    for name, be in backends:
        cap = cv2.VideoCapture(cam, be) if cam != "fake" else None
        if cap is None or not cap.isOpened():
            print(f"[{name}] 열 수 없음")
            continue
        try:
            for _ in range(10):
                cap.read()
            props = read_props(cap)
            ok = [k for k, v in props.items() if v not in (None, -1.0)]
            print(f"[{name}] 지원(값이 있음): " + (", ".join(f"{k}={props[k]:g}" for k in ok) or "없음"))
            print(f"[{name}] 지원 안 함(-1): " + (", ".join(k for k, v in props.items() if v == -1.0) or "없음"))
        finally:
            cap.release()
    return 0


def dialog(cam) -> int:
    """웹캠 드라이버 설정 창(DirectShow) + 미리보기 창. 미리보기에 바닥 밝기·날아간 점 %·바닥 색 치우침을 실시간으로.
    키: s = 지금 사진 저장, q 또는 Esc = 끝(끝날 때 바뀐 설정 값을 출력)"""
    import cv2
    from agents.kiosk_camera import fit
    if cam == "fake":
        print("가짜 카메라에는 드라이버 설정 창이 없음")
        return 2
    cap = cv2.VideoCapture(cam, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
    if not cap.isOpened():
        print("카메라를 열 수 없음(관제탑을 끄고 다시)")
        return 2
    out = ROOT / "data" / "exposure_check"
    out.mkdir(parents=True, exist_ok=True)
    before = read_props(cap)
    ok_dialog = cap.set(cv2.CAP_PROP_SETTINGS, 1)
    print("드라이버 설정 창을 " + ("열었음" if ok_dialog else "열지 못함(이 카메라·방식은 설정 창이 없음)")
          + " — 노출(Exposure)의 '자동'을 끄고 값을 낮춰 보며, 미리보기의 clip % 가 0.1% 아래로 내려가는지 확인. s 저장 · q 끝")
    n = 0
    try:
        while True:
            ok, f = cap.read()
            if not ok or f is None:
                time.sleep(0.05)
                continue
            f, _ = fit(f)
            m = measure(f)
            view = f.copy()
            txt = f"floor {m['floor']:.0f}  clip {m['clipped'] * 100:.2f}%  cast {m['cast'] * 100:.1f}%"
            good = m["clipped"] < CLIP_OK
            cv2.putText(view, txt, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(view, txt, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 220, 80) if good else (60, 60, 255), 2, cv2.LINE_AA)
            cv2.imshow("kiosk camera (s: save, q: quit)", view)
            k = cv2.waitKey(30) & 0xFF
            if k == ord("s"):
                n += 1
                p = out / f"dialog_{n}.jpg"
                cv2.imwrite(str(p), f)
                print(f"저장 {p.relative_to(ROOT)} · {txt}")
            elif k in (ord("q"), 27):
                break
    finally:
        after = read_props(cap)
        cap.release()
        cv2.destroyAllWindows()
    changed = {k: (before.get(k), v) for k, v in after.items() if v != before.get(k)}
    print("바뀐 설정: " + (", ".join(f"{k} {a:g}→{b:g}" for k, (a, b) in changed.items() if a is not None and b is not None) or "없음(또는 읽을 수 없음)"))
    print("※ 드라이버 설정은 웹캠을 뽑았다 꽂거나 PC 를 다시 켜면 풀릴 수 있음(추정) — 시연 전에 다시 확인")
    return 0


def _backend(cap) -> str:
    try:
        return cap.getBackendName()
    except Exception:
        return "?"


def try_props(cam, text: str, opener=None, settle: int = SETTLE_FRAMES, mjpg: bool | None = None) -> dict:
    """영상 설정을 OpenCV 로 넣어 보고(관제탑과 같은 방식) 읽은 값·날아간 점 % 를 돌려준다 — 끝나면 원래 값으로 되돌림.
    11/11 교육원: 처음 연 카메라가 까만 영상만 줌 → 관제탑(CameraFeed)처럼 압축 형식(MJPG)을 빼고 다시 열어 한 번 더"""
    from agents.kiosk_camera import _open, apply_props, fit, is_dark, parse_props
    props = parse_props(text)
    if not props:
        raise SystemExit(f"설정을 읽을 수 없음: {text!r} (예: CONTRAST=200)")
    from agents.kiosk_camera import mjpg_default
    first = mjpg_default() if mjpg is None else mjpg
    tries = [lambda: (opener(cam) if opener else _open(cam, mjpg=first))]
    if opener is None:
        tries.append(lambda: _open(cam, mjpg=not first))
    out: dict = {}
    for n_try, op in enumerate(tries, 1):
        cap = op()
        if cap is None or not cap.isOpened():
            out = {"error": "카메라를 열 수 없음(관제탑을 끄고 다시)"}
            continue
        try:
            before = read_props(cap)
            state = apply_props(cap, props)
            frame, n = None, 0
            while n < settle * 3:
                ok, f = cap.read()
                n += 1
                if ok and f is not None and not is_dark(f):
                    frame = f
                    if n >= settle:
                        break
                time.sleep(0.03)
            m = measure(fit(frame)[0]) if frame is not None else None
            apply_props(cap, {k: before[k] for k in props if before.get(k) not in (None, -1.0)})   # 되돌림
            out = {"state": state, "m": m, "backend": _backend(cap), "mjpg": first if n_try == 1 else not first}
        finally:
            cap.release()
        if out.get("m") is not None:
            break
        time.sleep(0.4)                                   # 방금 놓은 카메라가 풀릴 시간
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="키오스크 웹캠 노출 값 고르기")
    ap.add_argument("--cam", default="0", help="OpenCV 카메라 번호(tools/list_cameras.py 로 확인, 기본 0)")
    ap.add_argument("--values", default="auto,-4,-5,-6,-7,-8,-9", help="시험할 노출 값(쉼표로, auto 포함 가능)")
    ap.add_argument("--wb", default="", help="화이트밸런스 시험(켈빈, 예 auto,4000,4600,5200,6000) — 이때 노출은 --exposure 로 고정")
    ap.add_argument("--exposure", default="auto", help="화이트밸런스 시험 중 쓸 노출 값(먼저 고른 값, 기본 auto)")
    ap.add_argument("--props", action="store_true", help="이 웹캠이 받아들이는 설정 목록만 보고 끝")
    ap.add_argument("--dialog", action="store_true", help="웹캠 드라이버 설정 창 + 미리보기(날아간 점 % 실시간)")
    ap.add_argument("--no-mjpg", action="store_true", help="--try 를 압축 형식(MJPG) 없이 열어 시험(.env TOWER_KIOSK_MJPG=0 과 같음)")
    ap.add_argument("--try", dest="try_", default="", help="영상 설정을 OpenCV 로 넣어 확인(예: CONTRAST=200) — .env TOWER_KIOSK_CAMPROPS 값 확인용")
    a = ap.parse_args(argv)
    try:
        import cv2
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass
    cam = "fake" if a.cam == "fake" else int(a.cam)
    if a.props:
        return show_props(cam)
    if a.dialog:
        return dialog(cam)
    if a.try_:
        r = try_props(cam, a.try_, mjpg=False if a.no_mjpg else None)
        if "error" in r:
            print(r["error"])
            return 2
        print(f"열린 방식: {r.get('backend')} · 압축 형식 MJPG {'켬' if r.get('mjpg') else '끔'}")
        for k, st in (r["state"] or {}).items():
            print(f"{k}: 넣은 값 {st.get('requested'):g} → 카메라가 읽은 값 {st.get('now')}")
        m = r["m"]
        if m is None:
            print("영상이 까맘(MJPG 끄고 다시 열어도) — 키오스크 화면·다른 프로그램이 웹캠을 쓰는지 확인 후 다시")
            return 2
        good = m["clipped"] < CLIP_OK
        print(f"바닥 {m['floor']:.0f} · 날아간 점 {m['clipped'] * 100:.2f}% · 색 치우침 {m['cast'] * 100:.1f}% → "
              + (f"좋음: .env 에 TOWER_KIOSK_CAMPROPS={a.try_}" + (" 와 TOWER_KIOSK_MJPG=0" if not r.get("mjpg") else "") if good
                 else "아직 날아감 — " + ("--no-mjpg 를 붙여 다시(MJPG 에서는 설정이 영상에 안 먹는 웹캠이 있음)" if r.get("mjpg") else "값을 더 낮춰 보기")))
        return 0
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
