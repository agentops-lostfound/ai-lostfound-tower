"""키오스크 사진 색 측정 — Qwen 색을 숫자로 확인 (LF-18 · 11/11 변재원)

한줄 설명: 사진에서 바닥(회색 펠트)과 다른 부분을 물건으로 골라, 바닥을 회색 기준으로 삼아 물건의 평균 색을 재고
색 이름(검정·흰색·빨강·파랑·분홍 …)을 정한다. 확신할 때만 Qwen 색을 바꾸고, 애매하면 Qwen 색을 그대로 둔다.

왜: 11/11 시험 — Qwen3-VL-2B 는 작은 립밤·연한 핸드크림 색을 자주 틀렸다(빨간 립밤 → 갈색·분홍, 분홍 크림 → 흰색).
    카메라 화이트밸런스가 바닥까지 연보라로 치우쳐 찍는데, 사람 눈과 달리 모델은 이 치우침을 못 걷어낸다.
    회색 펠트 바닥은 "원래 회색"이므로, 바닥 색으로 나누면 조명·카메라 치우침이 사라진다(회색 기준 화이트밸런스).

동작
1. 사진을 240 폭으로 줄이고, 바닥 밝기를 완만한 곡면(2차식)으로 맞춘다 — 렌즈 가장자리가 어두운 것(주변부 감광)까지 맞춤.
   곡면에서 크게 벗어난 점을 빼며 3번 다시 맞춘다(물건이 곡면을 끌어당기지 않게)
2. 바닥 대비 색 = 사진 ÷ 곡면 → 바닥 = (1,1,1). 1 에서 많이 벗어난 점을 이은 가장 큰 덩어리 = 물건
3. 물건의 밝기(바닥 대비)·평균 색 → 색 이름 + 확신 여부. 하얗게 날아간 점(최댓값 근처)은 색 계산에서 뺀다

numpy 와 PIL 만 쓴다(Qwen 가상환경에 OpenCV 가 없음). 사진·결과를 다른 곳으로 보내지 않는다.
11/11 사진(펠트 20장)으로 맞춘 기준이며, 노출·화이트밸런스를 고정(TOWER_KIOSK_EXPOSURE·TOWER_KIOSK_WB)한 뒤 다시 확인한다.
"""
from __future__ import annotations

import colorsys
from collections import deque

WIDTH = 240            # 측정용으로 줄이는 폭
DEV_OBJ = 0.16         # 바닥 대비 이만큼 벗어나면 물건 후보(색·밝기 합친 거리)
CLIP = 245             # 이 값 이상 채널이 있으면 '날아간' 점(원본 0~255)
SAT_COLOR = 0.12       # 이보다 채도가 높으면 유채색
MIN_AREA = 0.004       # 화면의 0.4% 보다 작으면 물건을 못 찾은 것으로 봄
FELT_TEXTURE = 3.5     # 바닥 잔무늬가 이보다 약하면 펠트가 아님(도화지 약 2, 펠트 약 10) → 측정하지 않음
COLORFUL = {"핸드크림", "립밤"}     # 포장 색이 다양한 품목 — 많이 날아갔으면 흰색이라 단정하지 않음


def _load(path):
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    small = im.resize((WIDTH, max(1, round(h * WIDTH / w))), Image.BILINEAR)
    return np.asarray(small, dtype=np.float32)


def _ring(h: int, w: int):
    """사진 바깥 띠(짧은 변의 10%). 키오스크는 물건 둘레에 여유를 40% 두고 자르므로(#220) 이 띠는 늘 바닥"""
    import numpy as np
    b = max(3, round(min(h, w) * 0.10))
    r = np.zeros((h, w), bool)
    r[:b] = r[-b:] = True
    r[:, :b] = r[:, -b:] = True
    return r


def _floor_model(img):
    """바닥 밝기 곡면(채널별 2차식). 바깥 띠에서 먼저 맞추고, 곡면에 맞는 안쪽 점(물건이 아닌 바닥)을 더해 2번 다시 맞춘다
    → (곡면, 바닥 대비 사진). 물건이 사진의 절반을 차지해도(잘라 키운 사진) 곡면이 물건 쪽으로 끌려가지 않게"""
    import numpy as np
    h, w, _ = img.shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    x, y = x / w * 2 - 1, y / h * 2 - 1
    A = np.stack([np.ones_like(x), x, y, x * x, y * y, x * y], axis=-1).reshape(-1, 6)
    px = img.reshape(-1, 3)
    ring = _ring(h, w).ravel()
    keep = ring.copy()
    model = None
    for i in range(3):
        coef, *_ = np.linalg.lstsq(A[keep], px[keep], rcond=None)
        model = np.clip(A @ coef, 1.0, None)
        dev = np.linalg.norm(px / model - 1, axis=1)
        thr = max(0.06, 3.0 * float(np.median(dev[ring])))
        keep = dev < thr
        if keep[ring].mean() < 0.5:                 # 띠의 절반도 안 맞으면(물건이 가장자리까지) 띠만 씀
            keep = ring & (dev < max(thr, float(np.percentile(dev[ring], 70))))
    model = model.reshape(h, w, 3)
    return model, img / model


def floor_texture(img, rel=None) -> float:
    """바깥 띠 바닥의 잔무늬 세기(×1000). 회색 펠트 약 10, 매끈한 도화지·종이 약 2 (11/11 측정)"""
    import numpy as np
    if rel is None:
        _, rel = _floor_model(img)
    g = rel.mean(axis=2)
    tex = np.abs(g - _blur3(g))
    ring = _ring(*g.shape)
    flat = ring & (np.linalg.norm(rel - 1, axis=2) < 0.12)
    return float(np.median(tex[flat if flat.sum() > 50 else ring])) * 1000


def _blur3(a):
    import numpy as np
    p = np.pad(a, 1, mode="edge")
    return sum(p[dy:dy + a.shape[0], dx:dx + a.shape[1]] for dy in range(3) for dx in range(3)) / 9.0


def _grow(mask, n=1):
    import numpy as np
    m = mask.copy()
    for _ in range(n):
        p = np.pad(m, 1)
        m = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    return m


def _shrink(mask, n=1):
    return ~_grow(~mask, n)


def _components(mask):
    """4방향으로 이어진 덩어리 번호(0 = 바닥)"""
    import numpy as np
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    n = 0
    for sy, sx in zip(*np.nonzero(mask)):
        if lab[sy, sx]:
            continue
        n += 1
        lab[sy, sx] = n
        q = deque([(sy, sx)])
        while q:
            cy, cx = q.popleft()
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = n
                    q.append((ny, nx))
    return lab, n


def _fill_holes(mask):
    """가장자리에서 닿지 않는 바닥 = 물건 안의 구멍 → 메움"""
    import numpy as np
    outside = ~mask
    lab, _ = _components(outside)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    return mask | (outside & ~np.isin(lab, list(border)))


def find_object(img, rel=None):
    """→ (물건 마스크 또는 None, 바닥 대비 사진)"""
    import numpy as np
    if rel is None:
        _, rel = _floor_model(img)
    dev = _blur3(np.linalg.norm(rel - 1, axis=2))
    mask = _grow(_shrink(dev > DEV_OBJ, 1), 1)          # 작은 점(펠트 보풀) 지우기
    mask = _shrink(_grow(mask, 3), 3)                   # 물건 안 틈 메우기
    lab, n = _components(mask)
    if n == 0:
        return None, rel
    edge = np.zeros_like(mask)
    edge[0] = edge[-1] = True
    edge[:, 0] = edge[:, -1] = True
    score = []
    for k in range(1, n + 1):
        comp = lab == k
        s = float((dev[comp] ** 2).sum())
        if (comp & edge).any():                          # 사진 가장자리에 붙은 덩어리 = 상자 모서리·그림자일 때가 많음
            s *= 0.1
        score.append(s)
    obj = lab == (1 + int(np.argmax(score)))
    obj = _fill_holes(obj)
    if obj.mean() < MIN_AREA:
        return None, rel
    inner = _shrink(obj, 1)                             # 테두리(바닥과 섞인 점) 빼기
    return (inner if inner.sum() >= 30 else obj), rel


def _name(hue: float, sat: float, lum: float) -> str:
    """유채색 이름(계약 COLORS 안에서). hue 0~360, lum = 바닥 대비 밝기"""
    if hue >= 330 or hue < 15:
        return "분홍" if (lum > 1.1 or sat < 0.25) else "빨강"
    if hue < 45:
        return "노랑" if sat > 0.35 and lum > 1.0 else "갈색"
    if hue < 70:
        return "노랑"
    if hue < 165:
        return "초록"
    if hue < 255:
        return "남색" if lum < 0.6 else "파랑"          # 하늘색도 파랑(계약에 하늘색 없음)
    if hue < 300:
        return "기타"                                    # 보라(계약에 없음)
    return "분홍"


def measure(path, category: str | None = None) -> dict:
    """사진 한 장 → {'found', 'color', 'sure', 'reason', 'lum', 'sat', 'hue', 'clipped', 'area'}.
    sure=True 일 때만 Qwen 색 대신 쓴다. category(한국어 품목)는 '많이 날아간 흰색'을 믿을지 정할 때만 쓴다"""
    import numpy as np
    img = _load(path)
    _, rel = _floor_model(img)
    tex = floor_texture(img, rel)
    if tex < FELT_TEXTURE:
        return {"found": False, "color": None, "sure": False, "texture": round(tex, 1),
                "reason": f"바닥이 회색 펠트가 아님(잔무늬 {tex:.1f}) — 회색 기준을 쓸 수 없어 측정 안 함"}
    obj, rel = find_object(img, rel)
    if obj is None:
        return {"found": False, "color": None, "sure": False, "reason": "물건을 바닥과 구별하지 못함"}
    raw = img[obj]
    r = rel[obj]
    ok = raw.max(axis=1) < CLIP
    clipped = float(1 - ok.mean())
    lum = float(np.median(r.mean(axis=1)))
    if ok.sum() >= 20:
        m = r[ok].mean(axis=0)
        c = m / max(1e-6, float(m.max()))
        hue, sat, _ = colorsys.rgb_to_hsv(*[float(v) for v in c])
        hue *= 360
    else:                                   # 거의 다 날아감 — 남은 색 정보가 없음(바닥 치우침으로 나누면 없던 색이 생김)
        hue, sat = 0.0, 0.0
    out = {"found": True, "texture": round(tex, 1), "lum": round(lum, 3), "sat": round(sat, 3), "hue": round(hue, 1),
           "clipped": round(clipped, 3), "area": round(float(obj.mean()), 4)}
    if sat >= SAT_COLOR:
        name = _name(hue, sat, lum)
        sure = sat >= 0.18 and clipped < 0.5 and name != "기타"
        why = f"유채색(색 계열 {hue:.0f}°, 채도 {sat * 100:.0f}%)"
    elif lum < 0.8:
        name, sure, why = "검정", lum < 0.75, f"바닥보다 어두움({lum:.2f}배)"
    elif lum > 1.12:
        name = "흰색"
        sure = sat < 0.06 and lum > 1.2 and not (clipped > 0.3 and category in COLORFUL)
        why = f"바닥보다 밝고 색이 거의 없음({lum:.2f}배, 채도 {sat * 100:.0f}%)"
        if clipped > 0.3 and category in COLORFUL:
            why += f" — 하얗게 날아간 점 {clipped * 100:.0f}%(연한 색일 수 있음)"
    else:
        name, sure, why = "회색", False, f"바닥과 비슷한 밝기({lum:.2f}배)"
    out.update(color=name, sure=bool(sure), reason=why)
    return out


def summary(m: dict | None) -> dict | None:
    """관제탑으로 보낼 측정 요약(숫자·색 이름·근거만 — 사진은 보내지 않음)"""
    if not isinstance(m, dict):
        return None
    keep = ("found", "color", "sure", "reason", "lum", "sat", "hue", "clipped", "area", "texture")
    return {k: m[k] for k in keep if k in m}


def clean(cm) -> dict | None:
    """관제탑이 받은 측정 요약 검사 → 쓸 수 있는 모양만(색은 계약 COLORS 안, 근거는 80자)"""
    from agents.contracts import COLORS
    if not isinstance(cm, dict):
        return None
    color = cm.get("color")
    out = {"color": color if isinstance(color, str) and color in COLORS else None,
           "sure": cm.get("sure") is True, "reason": str(cm.get("reason") or "")[:80]}
    if out["color"] is None:
        out["sure"] = False
    return out


def apply_to_features(feats: dict, cm) -> dict:
    """계약 특징에 측정 결과 반영: 측정이 확실할 때만 색을 바꾼다(그 밖의 칸은 그대로)"""
    c = clean(cm)
    if not c or not c["sure"]:
        return feats
    return {**feats, "color": c["color"]}


def view(cm, qwen_color: str | None) -> dict | None:
    """화면용: Qwen 색 → 측정 색 → 쓴 색과 근거"""
    c = clean(cm)
    if c is None:
        return None
    used, why = decide(qwen_color, c)
    return {"qwen": qwen_color, "measured": c["color"], "sure": c["sure"], "used": used, "why": why[:100]}


def decide(qwen_color: str | None, m: dict | None) -> tuple[str | None, str]:
    """Qwen 색(한국어)과 측정 결과 → (쓸 색, 근거). 측정이 확실할 때만 측정 색"""
    if m and m.get("sure") and m.get("color"):
        if m["color"] == qwen_color:
            return qwen_color, "Qwen·색 측정 같음"
        return m["color"], f"색 측정으로 바꿈({m.get('reason', '')})"
    return qwen_color, "Qwen 색 유지" + (f"(측정 애매: {m.get('reason')})" if m and m.get("reason") else "")


__all__ = ["measure", "decide", "find_object", "floor_texture", "summary", "clean", "apply_to_features", "view"]
