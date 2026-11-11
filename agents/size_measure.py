"""키오스크 사진 크기 측정 — Qwen 품목을 크기로 확인 (LF-18 · 11/11 변재원)

한줄 설명: 회색 펠트 위 물건의 길이·폭을 픽셀로 재서(카메라 높이가 고정이라 크기가 늘 같음) 립밤·핸드크림·휴대폰/보조배터리를
구별하고, Qwen 품목이 크기와 맞지 않을 때만 품목을 바꾼다.

왜: 11/11 Qwen 이 분홍 핸드크림을 립밤으로 읽어 립밤 열(R4)로 보냈다(A-20261111-0092). 키오스크는 물건 둘레만 잘라
    크게 키워 보내므로(#220) Qwen 은 물건의 실제 크기를 알 수 없다 — 작은 립밤과 짧은 크림 튜브가 비슷해 보인다.
    YOLO 는 위치만 찾고 품목을 정하지 않으므로, 품목을 맞춰 볼 수 있는 다른 근거는 크기뿐이다.

크기 단위: '720 화면 픽셀' — 카메라 영상(관제탑은 늘 960×720 으로 맞춤)의 세로를 720 으로 놓았을 때의 픽셀.
    키오스크가 잘라 키운 사진은 함께 저장한 자르기 정보(사진 옆 .json, agents/intake.py save_geom)로 되돌려 잰다.
    자르기 정보가 없고 사진이 잘리지 않은 960×720 이면 그대로 잰다. 그 밖에는 재지 않는다.

기준(11/11 회색 펠트 사진 22장, 같은 품목 안에서 ±2%):
    립밤 길이 약 215 · 폭 약 68 / 핸드크림 약 382 · 127 / 목업폰 약 455 · 218 / 보조배터리 약 420 · 210
    → 립밤·핸드크림·(휴대폰·보조배터리)는 크게 갈린다. 휴대폰과 보조배터리는 길이가 7% 차이라
      가운데 띠(PHONE_BATTERY_BAND)에서는 정하지 않는다(보조배터리 사진이 2장뿐 — 더 찍어 다시 맞춤)
    카메라 해상도·높이를 바꾸면 크기가 달라진다 → tools/size_check.py 로 다시 재서 .env TOWER_SIZE_SCALE 로 맞춘다
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FRAME_H = 720
# (품목, 길이 범위, 폭 범위) — 720 화면 픽셀. 측정값의 ±15% 정도 여유
GROUPS = [
    ("립밤", (170, 260), (50, 95)),
    ("핸드크림", (330, 430), (105, 155)),
    ("휴대폰·보조배터리", (390, 520), (180, 255)),
]
PHONE_LEN, BATTERY_LEN = 455, 420
PHONE_BATTERY_BAND = (430, 446)     # 이 길이 사이는 휴대폰인지 보조배터리인지 크기로 정하지 않음
CONFUSABLE = {"립밤", "핸드크림", "모형폰", "보조배터리"}


def scale_from_env(env: dict | None = None) -> float:
    env = os.environ if env is None else env
    try:
        v = float(str(env.get("TOWER_SIZE_SCALE") or "1"))
        return v if 0.3 <= v <= 3 else 1.0
    except ValueError:
        return 1.0


def size_measure_on(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("TOWER_SIZE_MEASURE", "1")).strip().lower() not in ("0", "false", "no", "off")


def load_geom(path) -> dict | None:
    """사진 옆 자르기 정보(.json) → {"crop": [x,y,w,h], "frame": [W,H], "up": 배수} 또는 None"""
    p = Path(path).with_suffix(".json")
    try:
        g = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return g if isinstance(g, dict) else None


def to_frame(photo_size: tuple[int, int], geom: dict | None) -> float | None:
    """사진 픽셀 1개 = 720 화면 픽셀 몇 개인가. 모르면 None"""
    pw, ph = photo_size
    if geom:
        try:
            up = float(geom.get("up") or 1)
            fh = float((geom.get("frame") or [0, 0])[1])
            if up <= 0 or fh <= 0:
                return None
            return FRAME_H / fh / up
        except (TypeError, ValueError, IndexError):
            return None
    if (pw, ph) == (960, 720):          # 잘리지 않은 관제탑 카메라 사진
        return 1.0
    return None


def classify(length: float, width: float) -> tuple[str | None, str]:
    """(크기로 본 품목 또는 묶음, 근거)"""
    hit = [name for name, (l0, l1), (w0, w1) in GROUPS if l0 <= length <= l1 and w0 <= width <= w1]
    if len(hit) != 1:
        return None, f"어느 품목 크기와도 맞지 않음(길이 {length:.0f}·폭 {width:.0f})"
    return hit[0], f"길이 {length:.0f}·폭 {width:.0f}(720 화면 픽셀) = {hit[0]} 크기"


def measure(path, env: dict | None = None) -> dict:
    """사진 한 장 → {'found','length','width','size_group','reason'}. 회색 펠트에서만 잰다(색 측정과 같은 물건 찾기)"""
    import numpy as np
    from PIL import Image
    from agents import color_measure as cm
    with Image.open(path) as im:
        size = im.size
    k = to_frame(size, load_geom(path))
    if k is None:
        return {"found": False, "reason": "잘린 사진인데 자르기 정보가 없음 — 크기를 잴 수 없음"}
    img = cm._load(path)
    _, rel = cm._floor_model(img)
    tex = cm.floor_texture(img, rel)
    if tex < cm.FELT_TEXTURE:
        return {"found": False, "reason": f"바닥이 회색 펠트가 아님(잔무늬 {tex:.1f}) — 물건 경계를 믿을 수 없어 재지 않음"}
    obj, _ = cm.find_object(img, rel)
    if obj is None:
        return {"found": False, "reason": "물건을 바닥과 구별하지 못함"}
    ys, xs = np.nonzero(obj)
    if len(xs) < 30:
        return {"found": False, "reason": "물건이 너무 작음"}
    pts = np.stack([xs, ys], 1).astype(float)
    pts -= pts.mean(0)
    _, vec = np.linalg.eigh(np.cov(pts.T))
    along, across = pts @ vec[:, 1], pts @ vec[:, 0]
    px = size[0] / img.shape[1] * k * scale_from_env(env)       # 측정 사진 픽셀 → 720 화면 픽셀
    length = float(np.percentile(along, 99.5) - np.percentile(along, 0.5)) * px
    width = float(np.percentile(across, 99.5) - np.percentile(across, 0.5)) * px
    group, why = classify(length, width)
    return {"found": True, "length": round(length), "width": round(width), "size_group": group, "reason": why}


def decide(qwen_category: str | None, m: dict | None) -> tuple[str | None, bool, str]:
    """Qwen 품목(한국어)과 크기 측정 → (쓸 품목, 바꿨나, 근거). 크기가 Qwen 품목과 확실히 다를 때만 바꾼다"""
    if not m or not m.get("found") or not m.get("size_group"):
        return qwen_category, False, "Qwen 품목 유지" + (f"(크기: {m.get('reason')})" if m and m.get("reason") else "")
    g, L = m["size_group"], float(m.get("length") or 0)
    if g in ("립밤", "핸드크림"):
        if qwen_category == g:
            return g, False, "Qwen·크기 같음"
        if qwen_category in CONFUSABLE or qwen_category in (None, "", "확인 불가"):
            return g, True, f"크기로 바꿈({m['reason']})"
        return qwen_category, False, "Qwen 품목 유지(운영 품목 밖)"
    # 휴대폰·보조배터리 묶음
    if qwen_category in ("모형폰", "보조배터리"):
        if qwen_category == "모형폰" and L < PHONE_BATTERY_BAND[0] or qwen_category == "보조배터리" and L > PHONE_BATTERY_BAND[1]:
            new = "보조배터리" if L < PHONE_BATTERY_BAND[0] else "모형폰"
            return new, True, f"크기로 바꿈(길이 {L:.0f} — 휴대폰 약 {PHONE_LEN}, 보조배터리 약 {BATTERY_LEN})"
        return qwen_category, False, "Qwen·크기 같음(휴대폰·보조배터리 크기)"
    if qwen_category in CONFUSABLE or qwen_category in (None, "", "확인 불가"):
        new = "모형폰" if abs(L - PHONE_LEN) < abs(L - BATTERY_LEN) else "보조배터리"
        return new, True, f"크기로 바꿈(길이 {L:.0f} — 립밤·핸드크림보다 훨씬 큼, 더 가까운 {new})"
    return qwen_category, False, "Qwen 품목 유지(운영 품목 밖)"


def summary(m: dict | None) -> dict | None:
    """관제탑으로 보낼 요약(숫자·근거만)"""
    if not isinstance(m, dict):
        return None
    return {k: m[k] for k in ("found", "length", "width", "size_group", "reason") if k in m}


def clean(m) -> dict | None:
    """관제탑이 받은 요약 검사 → 쓸 수 있는 모양만"""
    if not isinstance(m, dict):
        return None
    out = {"found": m.get("found") is True, "reason": str(m.get("reason") or "")[:100]}
    g = m.get("size_group")
    out["size_group"] = g if g in [n for n, *_ in GROUPS] else None
    for k in ("length", "width"):
        v = m.get(k)
        out[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < 5000 else None
    if out["size_group"] is None or out["length"] is None:
        out["found"] = out["found"] and False
    return out


def apply_to_features(feats: dict, m) -> dict:
    """계약 특징에 크기 측정 반영: 크기가 Qwen 품목과 확실히 다를 때만 품목을 바꾼다"""
    c = clean(m)
    if not c:
        return feats
    new, changed, _ = decide(feats.get("category"), c)          # 계약 특징의 품목은 한국어(vision_adapter.to_features)
    return {**feats, "category": new} if changed else feats


def view(m, qwen_category: str | None) -> dict | None:
    """화면용: Qwen 품목 → 크기 → 쓴 품목과 근거"""
    c = clean(m)
    if c is None:
        return None
    used, changed, why = decide(qwen_category, c)
    return {"qwen": qwen_category, "size": c.get("size_group"), "length": c.get("length"), "width": c.get("width"),
            "used": used, "changed": changed, "why": why[:120]}


__all__ = ["measure", "decide", "classify", "summary", "clean", "apply_to_features", "view", "load_geom", "to_frame"]
