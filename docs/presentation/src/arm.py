"""SO-101 로봇팔 그림 부품 — 마디 길이가 변하지 않는 옆모습(중첩 회전) + 위에서 본 방향 표시
4쪽(본센터 그림)과 14쪽(돌려받기 카드)에서 함께 쓴다."""
import math
from embeds import INK, ACC, ACCL


def _kf(name, frames):
    return "@keyframes %s{%s}" % (name, "".join("%s%%{%s}" % (round(p, 2), s) for p, s in frames))


def _ik(dx, dy, L1, L2):
    D = min(math.hypot(dx, dy), L1 + L2 - 0.5)
    a = math.atan2(dy, dx)
    b = math.acos(max(-1, min(1, (L1 * L1 + D * D - L2 * L2) / (2 * L1 * D))))
    t1 = a + b
    ex, ey = L1 * math.cos(t1), L1 * math.sin(t1)
    t2 = math.atan2(dy - ey, dx - ex)
    return math.degrees(t1), math.degrees(t2)


def _ease(u):
    return u * u * (3 - 2 * u)


def poses(L1, L2, hs, d_slot, d_box, hz, hov_s=104, hov_b=92, home_d=None):
    """시간표(%) → (손목 가로 거리, 손목 높이, 집게 절대각, 집게 간격). 높이는 바닥 기준, hs는 어깨 높이"""
    home = (home_d if home_d else 0.62 * d_slot, hs + 0.60 * 100 * hz, -62, 24)
    way = [
        (0, home), (8, home),
        (22, (d_slot, hz * hov_s, -90, 24)),
        (30, (d_slot, hz * 68, -90, 24)), (35, (d_slot, hz * 68, -90, 12)),
        (44, (d_slot, hz * hov_s, -90, 12)),
        (60, (d_box, hz * hov_b, -90, 12)),
        (66, (d_box, hz * 74, -90, 12)), (72, (d_box, hz * 74, -90, 12)), (73, (d_box, hz * 74, -90, 24)),
        (78, (d_box, hz * hov_b, -90, 24)),
        (92, home), (100, home),
    ]
    out = []
    ts = sorted(set([w[0] for w in way] + list(range(0, 101, 4))))
    for t in ts:
        for (t0, a), (t1_, b) in zip(way, way[1:]):
            if t0 <= t <= t1_:
                u = 0 if t1_ == t0 else _ease((t - t0) / (t1_ - t0))
                if a[3] != b[3] and t1_ - t0 <= 5:  # 집게는 짧은 구간에서만 움직임
                    g = a[3] + (b[3] - a[3]) * ((t - t0) / (t1_ - t0))
                else:
                    g = a[3] if t < t1_ else b[3]
                out.append((t, a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u, g))
                break
    return out


def side(pfx, cyc, ox, oy, ground_y, s=1.0, dark=False, with_badges=True, slot_d=128, box_d=176, labels=False, wc=270):
    """옆에서 본 SO-101. ox,oy = 어깨 축(받침 위) 좌표. 반환 (css, html)"""
    L1, L2 = 84 * s, 108 * s
    hs = (ground_y - oy)
    d_slot, d_box = slot_d * s, box_d * s
    P = poses(L1, L2, hs, d_slot, d_box, s)
    ku, kf_, kg, bu, bf, bg, jw = [], [], [], [], [], [], []
    for t, wd, wh, ga, g in P:
        t1, t2 = _ik(wd, wh - hs, L1, L2)
        ku.append((t, "transform:rotate(%.0fdeg)" % (-t1)))
        kf_.append((t, "transform:rotate(%.0fdeg)" % (-(t2 - t1))))
        kg.append((t, "transform:rotate(%.0fdeg)" % (-(ga - t2))))
        bu.append((t, "transform:rotate(%.0fdeg)" % t1))
        bf.append((t, "transform:rotate(%.0fdeg)" % t2))
        bg.append((t, "transform:rotate(%.0fdeg)" % ga))
        jw.append((t, "top:%.0fpx" % ((-9.5 - (g - 12) * 0.833) * s)))
    css = ""
    for n, k in (("u", ku), ("f", kf_), ("g", kg), ("bu", bu), ("bf", bf), ("bg", bg), ("jw", jw)):
        css += _kf(pfx + n, k)
    css += _kf(pfx + "h", [(0, "opacity:0"), (34, "opacity:0"), (35, "opacity:1"), (71, "opacity:1"), (72, "opacity:0"), (100, "opacity:0")])
    css += _kf(pfx + "b0", [(0, "opacity:1"), (34, "opacity:1"), (35, "opacity:0"), (97, "opacity:0"), (100, "opacity:1")])
    css += _kf(pfx + "b2", [(0, "opacity:0"), (70, "opacity:0"), (71, "opacity:1"), (93, "opacity:1"), (97, "opacity:0"), (100, "opacity:0")])
    link = "linear-gradient(180deg,#D7DDE5,#9EA8B6)" if not dark else "linear-gradient(180deg,#E3E8EF,#AEB8C6)"
    link2 = "linear-gradient(180deg,#CBD2DB,#8E99A8)" if not dark else "linear-gradient(180deg,#D5DBE4,#9DA8B7)"
    motor = "#2B3442" if not dark else "#566277"
    motor_edge = "#16202E" if not dark else "#8794A8"
    ground = "#C9C1B3" if not dark else "#4A5A70"
    pad = "#D6C9B5" if not dark else "#3A4A62"
    m = lambda w, h: f"position:absolute;left:{-w / 2:.1f}px;top:{-h / 2:.1f}px;width:{w:.1f}px;height:{h:.1f}px;border-radius:{min(w, h) * .28:.1f}px;background:{motor};border:{max(1.5, 2 * s):.1f}px solid {motor_edge}"
    bd = lambda n, col="#16202E": (f'<b style="position:absolute;left:-9px;top:-9px;width:18px;height:18px;border-radius:50%;background:{col};color:#fff;'
                                    f'font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;line-height:1;z-index:7">{n}</b>')
    ph = 28 * s  # 어깨 받침 높이 보정
    html = f'<i style="position:absolute;left:6px;top:{ground_y:.1f}px;width:{wc - 12}px;height:3px;background:{ground}"></i>'
    # 받침
    html += (f'<i style="position:absolute;left:{ox - 28 * s:.1f}px;top:{oy + 6 * s:.1f}px;width:{56 * s:.1f}px;height:{ground_y - oy - 6 * s:.1f}px;border-radius:{8 * s:.1f}px {8 * s:.1f}px 0 0;'
             f'background:{"#9AA6B8" if not dark else "#6D7B92"}"></i>')
    # 칸 받침 + 칸 안의 립밤, 제출보관함 받침 + 놓인 립밤
    sx, bx = ox + d_slot, ox + d_box
    bw, bh = 9 * s * 1.2, 22 * s * 1.1
    html += f'<i style="position:absolute;left:{sx - 20 * s:.1f}px;top:{ground_y - 8 * s:.1f}px;width:{40 * s:.1f}px;height:{8 * s:.1f}px;border-radius:3px 3px 0 0;background:{pad}"></i>'
    html += f'<i style="position:absolute;left:{bx - 25 * s:.1f}px;top:{ground_y - 16 * s:.1f}px;width:{50 * s:.1f}px;height:{16 * s:.1f}px;border:{max(2, 3 * s):.1f}px dashed {ACC};border-bottom:0;border-radius:6px 6px 0 0"></i>'
    balm = lambda cx, base_y, op: (f'<div style="position:absolute;left:{cx - bw / 2:.1f}px;top:{base_y - bh:.1f}px;width:{bw:.1f}px;height:{bh:.1f}px;border-radius:2px;animation:{pfx}{op} {cyc}s infinite;'
                                    f'background:linear-gradient(180deg,#E3264E 0 55%,#fff 55%);box-shadow:0 0 0 1px rgba(0,0,0,.18)"></div>')
    html += balm(sx, ground_y - 8 * s, "b0") + balm(bx, ground_y - 16 * s, "b2")
    if labels:
        lc = "#4A5568"
        html += (f'<p style="position:absolute;left:{sx - 24:.1f}px;top:{ground_y + 6:.1f}px;width:48px;margin:0;text-align:center;font-size:13px;font-weight:800;color:{lc}">R4-1</p>'
                 f'<p style="position:absolute;left:{bx - 30:.1f}px;top:{ground_y + 6:.1f}px;width:60px;margin:0;text-align:center;font-size:13px;font-weight:800;color:#B5500A">제출함</p>')
    # 어깨(②) → 위팔 → 팔꿈치(③) → 아래팔 → 손목(④) → 집게(⑥)
    html += f'<div style="position:absolute;left:{ox:.1f}px;top:{oy:.1f}px;width:0;height:0;animation:{pfx}u {cyc}s infinite">'
    html += f'<i style="position:absolute;left:0;top:{-7 * s:.1f}px;width:{L1:.1f}px;height:{14 * s:.1f}px;border-radius:{7 * s:.1f}px;background:{link}"></i>'
    html += f'<i style="{m(26 * s, 30 * s)}"></i>'
    if with_badges:
        html += f'<div style="position:absolute;left:0;top:0;animation:{pfx}bu {cyc}s infinite"><div style="position:absolute;left:{-4 * s:.1f}px;top:{-24 * s:.1f}px">{bd("②")}</div></div>'
    html += f'<div style="position:absolute;left:{L1:.1f}px;top:0;width:0;height:0;animation:{pfx}f {cyc}s infinite">'
    html += f'<i style="position:absolute;left:0;top:{-6 * s:.1f}px;width:{L2:.1f}px;height:{12 * s:.1f}px;border-radius:{6 * s:.1f}px;background:{link2}"></i>'
    html += f'<i style="{m(22 * s, 28 * s)}"></i>'
    if with_badges:
        html += f'<div style="position:absolute;left:0;top:0;animation:{pfx}bf {cyc}s infinite"><div style="position:absolute;left:{-2 * s:.1f}px;top:{-26 * s:.1f}px">{bd("③")}</div></div>'
    html += f'<div style="position:absolute;left:{L2:.1f}px;top:0;width:0;height:0;animation:{pfx}g {cyc}s infinite">'
    html += f'<i style="{m(18 * s, 24 * s)}"></i>'
    html += f'<i style="position:absolute;left:{8 * s:.1f}px;top:{-9 * s:.1f}px;width:{18 * s:.1f}px;height:{18 * s:.1f}px;border-radius:4px;background:{motor};border:{max(1.5, 2 * s):.1f}px solid {motor_edge}"></i>'
    # 고정 집게(아래쪽) · 움직이는 집게(위쪽)
    html += f'<i style="position:absolute;left:{24 * s:.1f}px;top:{7 * s - 2.5 * s:.1f}px;width:{32 * s:.1f}px;height:{5 * s:.1f}px;border-radius:3px;background:{motor};border:1px solid {motor_edge}"></i>'
    html += f'<i style="position:absolute;left:{24 * s:.1f}px;width:{32 * s:.1f}px;height:{5 * s:.1f}px;border-radius:3px;background:{motor};border:1px solid {motor_edge};animation:{pfx}jw {cyc}s infinite"></i>'
    html += (f'<div style="position:absolute;left:{30 * s:.1f}px;top:{-4 * s:.1f}px;width:{bh:.1f}px;height:{8 * s:.1f}px;border-radius:2px;animation:{pfx}h {cyc}s infinite;opacity:0;'
             f'background:linear-gradient(90deg,#E3264E 0 55%,#fff 55%);box-shadow:0 0 0 1px rgba(0,0,0,.18)"></div>')
    if with_badges:
        html += (f'<div style="position:absolute;left:0;top:0;animation:{pfx}bg {cyc}s infinite"><div style="position:absolute;left:{6 * s:.1f}px;top:{-26 * s:.1f}px">{bd("④")}</div>'
                 f'<div style="position:absolute;left:{36 * s:.1f}px;top:{-24 * s:.1f}px">{bd("⑥", "#F06A00")}</div></div>')
    html += "</div></div></div>"
    return css, html


def top(cx, cy, cyc, h_pan=None):
    """위에서 본 방향 표시: 받침(①) → 팔이 향하는 방향 · 집게 위치.
    팔 몸통을 그리지 않는다(위에서는 ②③④ 굽힘이 길이 변화로만 보여 늘어나 보이므로). 반환 (css, html)"""
    P = [(0, -35, 62), (8, -35, 62), (22, 40, 398), (44, 40, 398), (60, 0, 482), (78, 0, 482), (92, -35, 62), (100, -35, 62)]
    css = _kf("tpan", [(t, "transform:rotate(%ddeg)" % a) for t, a, _ in P])
    css += _kf("tbm", [(t, "top:%dpx;height:%dpx" % (-L, L)) for t, _, L in P])
    css += _kf("tcr", [(t, "transform:rotate(%ddeg)" % -a) for t, a, _ in P])
    css += _kf("tjw", [(0, "gap:26px"), (30, "gap:26px"), (35, "gap:13px"), (72, "gap:13px"), (73, "gap:26px"), (100, "gap:26px")])
    css += _kf("thd", [(0, "opacity:0"), (34, "opacity:0"), (35, "opacity:1"), (71, "opacity:1"), (72, "opacity:0"), (100, "opacity:0")])
    css += _kf("trg", [(0, "opacity:0"), (28, "opacity:0"), (30, "opacity:1;transform:scale(1.25)"), (36, "opacity:1;transform:scale(.9)"), (38, "opacity:0"),
                       (64, "opacity:0"), (66, "opacity:1;transform:scale(1.25)"), (72, "opacity:1;transform:scale(.9)"), (74, "opacity:0"), (100, "opacity:0")])
    html = f'<div style="position:absolute;left:{cx}px;top:{cy}px;width:0;height:0;animation:tpan {cyc}s infinite;z-index:4">'
    html += (f'<div style="position:absolute;left:-7px;width:14px;border-radius:7px 7px 0 0;animation:tbm {cyc}s infinite;'
             f'background:linear-gradient(0deg,rgba(240,106,0,.0),rgba(240,106,0,.26))">'
             # 집게: 손목 + 두 손가락
             f'<div style="position:absolute;left:-19px;top:-8px;width:52px;display:flex;flex-direction:column;align-items:center">'
             f'<div style="display:flex;gap:26px;animation:tjw {cyc}s infinite"><i style="display:block;width:7px;height:26px;border-radius:3px;background:#2B3442"></i>'
             f'<i style="display:block;width:7px;height:26px;border-radius:3px;background:#2B3442"></i></div>'
             f'<i style="display:block;width:40px;height:16px;margin-top:-3px;border-radius:6px;background:#4B5568;border:2px solid #2B3442"></i></div>'
             f'<i style="position:absolute;left:-19px;top:-20px;width:52px;height:52px;border-radius:50%;border:5px solid {ACC};animation:trg {cyc}s infinite;opacity:0;box-sizing:border-box"></i>'
             f'<div style="position:absolute;left:7px;top:6px;width:0;height:0;animation:thd {cyc}s infinite;opacity:0"><div style="position:absolute;left:0;top:0;animation:tcr {cyc}s infinite;width:0;height:0">@@BALM@@</div></div>'
             f'</div>')
    html += "</div>"
    return css, html


def top2(cx, cy, cyc, balm_html):
    """위에서 본 SO-101: 옆모습과 같은 관절 계산(IK)에서 마디의 수평 투영 길이를 구해 그린다.
    높이가 달라지면 위에서는 짧아 보이는 것이 정상이며, 팔꿈치는 높이에 따라 크게(원근) 보인다."""
    L1, L2, hs, G = 84.0, 108.0, 34.0, 56.0
    P = poses(L1, L2, hs, 128.0, 176.0, 1.0)
    tbl = [(0.0, 0.0), (79.4, 150.0), (128.0, 398.0), (176.0, 482.0)]

    def rad(wd):
        for (a, ra), (b, rb) in zip(tbl, tbl[1:]):
            if wd <= b:
                return ra + (rb - ra) * (wd - a) / (b - a)
        return tbl[-1][1]

    up, fo, el, wr, ws = [], [], [], [], []
    for t, wd, wh, ga, g in P:
        t1, t2 = _ik(wd, wh - hs, L1, L2)
        ex = L1 * math.cos(math.radians(t1))
        ey = hs + L1 * math.sin(math.radians(t1))
        rw = rad(wd)
        re = ex / wd * rw
        up.append((t, "top:%dpx;height:%dpx" % (-max(0, re), abs(re))))
        fo.append((t, "top:%dpx;height:%dpx" % (-max(re, rw), abs(rw - re))))
        el.append((t, "top:%dpx;transform:scale(%.2f)" % (-re, 1 + 0.35 * ey / (hs + L1))))
        wr.append((t, "top:%dpx" % -rw))
    css = ""
    for n, k in (("tu", up), ("tf", fo), ("te", el), ("tw", wr)):
        css += _kf(n, k)
    Pn = [(0, -35), (8, -35), (22, 40), (44, 40), (60, 0), (78, 0), (92, -35), (100, -35)]
    css += _kf("tpan", [(t, "transform:rotate(%ddeg)" % a) for t, a in Pn])
    css += _kf("tcr", [(t, "transform:rotate(%ddeg)" % -a) for t, a in Pn])
    css += _kf("tjw", [(0, "gap:26px"), (30, "gap:26px"), (35, "gap:13px"), (72, "gap:13px"), (73, "gap:26px"), (100, "gap:26px")])
    css += _kf("thd", [(0, "opacity:0"), (34, "opacity:0"), (35, "opacity:1"), (71, "opacity:1"), (72, "opacity:0"), (100, "opacity:0")])
    css += _kf("trg", [(0, "opacity:0"), (28, "opacity:0"), (30, "opacity:1;transform:scale(1.25)"), (36, "opacity:1;transform:scale(.9)"), (38, "opacity:0"),
                       (64, "opacity:0"), (66, "opacity:1;transform:scale(1.25)"), (72, "opacity:1;transform:scale(.9)"), (74, "opacity:0"), (100, "opacity:0")])
    A = f"animation-duration:{cyc}s;animation-iteration-count:infinite"
    link = "radial-gradient(circle,#5E6A7C 0 2.2px,transparent 2.8px) 50% 0/100% 44px repeat-y,linear-gradient(90deg,#8794A6,#DCE2EA 40%,#C9D1DB 60%,#8794A6)"
    tp = "clip-path:polygon(14% 0,86% 0,100% 100%,0 100%);"
    mot = "background:radial-gradient(circle,#16202E 0 3px,#B7C0CC 3.5px 8px,transparent 9px),linear-gradient(#3A4658,#2B3442);border:3px solid #16202E;border-radius:9px"
    bd = lambda n, col="#16202E": (f'<b style="position:absolute;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:{col};color:#fff;'
                                    f'font-size:14px;font-weight:800;display:flex;align-items:center;justify-content:center;z-index:9">{n}</b>')
    cr = lambda inner, dx, dy: f'<div style="position:absolute;left:0;top:0;width:0;height:0;animation:tcr {cyc}s infinite"><div style="position:absolute;left:{dx}px;top:{dy}px">{inner}</div></div>'
    h = f'<div style="position:absolute;left:0;top:0;width:0;height:0;filter:drop-shadow(7px 10px 6px rgba(22,32,46,.30));z-index:4"><div style="position:absolute;left:{cx}px;top:{cy}px;width:0;height:0;animation:tpan {cyc}s infinite">'
    # 위팔 · 아래팔(길이는 투영이라 변함) — 마디는 납작한 판, 관절은 검은 모터
    h += f'<i style="position:absolute;left:-17px;width:34px;border-radius:12px;background:{link};{tp}animation:tu {cyc}s infinite"></i>'
    h += f'<i style="position:absolute;left:-14px;width:28px;border-radius:10px;background:{link};{tp}animation:tf {cyc}s infinite"></i>'
    h += f'<i style="position:absolute;left:-23px;top:-26px;width:46px;height:52px;{mot}"></i>'  # 어깨 모터
    h += cr(bd("②"), -30, -30)
    h += f'<div style="position:absolute;left:0;top:0;width:0;height:0;animation:te {cyc}s infinite"><i style="position:absolute;left:-20px;top:-17px;width:40px;height:34px;{mot}"></i>{cr(bd("③"), 0, -28)}</div>'
    # 손목 + 집게
    h += (f'<div style="position:absolute;left:0;top:0;width:0;height:0;animation:tw {cyc}s infinite">'
          f'<i style="position:absolute;left:-16px;top:-12px;width:32px;height:26px;{mot}"></i>{cr(bd("④"), -24, 10)}'
          f'<div style="position:absolute;left:-26px;top:-38px;width:52px;display:flex;justify-content:center;animation:tjw {cyc}s infinite">'
          f'<i style="display:block;width:10px;height:34px;clip-path:polygon(30% 0,70% 0,100% 100%,0 100%);background:linear-gradient(0deg,#2B3442,#8794A6)"></i><i style="display:block;width:10px;height:34px;clip-path:polygon(30% 0,70% 0,100% 100%,0 100%);background:linear-gradient(0deg,#2B3442,#8794A6)"></i></div>'
          f'<i style="position:absolute;left:-19px;top:-26px;width:52px;height:52px;border-radius:50%;border:5px solid {ACC};box-sizing:border-box;animation:trg {cyc}s infinite;opacity:0"></i>'
          f'<div style="position:absolute;left:0;top:-18px;width:0;height:0;animation:thd {cyc}s infinite;opacity:0"><div style="position:absolute;left:0;top:0;width:0;height:0;animation:tcr {cyc}s infinite">{balm_html}</div></div>'
          f'{cr(bd("⑥", "#F06A00"), 34, 4)}</div>')
    h += "</div></div>"
    return css, h


def top3(cx, cy, cyc, balm_html, k=0.26, sc=3.11):
    """비스듬히 위에서 본 SO-101(높이를 화면 위쪽으로 k배 올려 그림).
    옆모습과 같은 관절 계산으로 3차원 위치를 구한 뒤 투영해서, 팔꿈치가 들리고 굽는 모습이 보이게 한다.
    바닥에는 팔의 그림자(위에서 본 직선)를 깐다."""
    L1, L2, hs, G = 84.0, 108.0, 34.0, 56.0
    P = poses(L1, L2, hs, 128.0, 155.0, 1.0, hov_s=84, hov_b=80, home_d=76)
    pw = [(0, -88), (8, -88), (22, 40), (44, 40), (60, 0), (78, 0), (92, -88), (100, -88)]

    def pan(t):
        for (a, pa), (b, pb) in zip(pw, pw[1:]):
            if a <= t <= b:
                return pa + (pb - pa) * _ease((t - a) / (b - a))
        return pw[-1][1]

    def scr(phi, r, z):
        f = math.radians(phi)
        return cx + r * sc * math.sin(f), cy - r * sc * math.cos(f) - k * z * sc

    def seg(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx))

    ks = {n: [] for n in ("su", "sf", "sg", "se", "sw", "ssh")}
    last = {}

    def unwrap(n, a):
        if n in last:
            while a - last[n] > 180:
                a -= 360
            while a - last[n] < -180:
                a += 360
        last[n] = a
        return a

    for t, wd, wh, ga, g in P:
        phi = pan(t)
        t1, t2 = _ik(wd, wh - hs, L1, L2)
        ex, ez = L1 * math.cos(math.radians(t1)), hs + L1 * math.sin(math.radians(t1))
        tx, tz = wd + G * math.cos(math.radians(ga)), wh + G * math.sin(math.radians(ga))
        S, E, W, T = scr(phi, 0, hs), scr(phi, ex, ez), scr(phi, wd, wh), scr(phi, tx, tz)
        for n, p, q in (("su", S, E), ("sf", E, W)):
            ln, a = seg(p, q)
            ks[n].append((t, "transform:translate(%dpx,%dpx) rotate(%ddeg);width:%dpx" % (p[0], p[1], unwrap(n, a), ln)))
        ln, a = seg(W, T)
        ks["sg"].append((t, "transform:translate(%dpx,%dpx) rotate(%ddeg)" % (W[0], W[1], unwrap("sg", a))))
        ks["se"].append((t, "transform:translate(%dpx,%dpx)" % E))
        ks["sw"].append((t, "transform:translate(%dpx,%dpx)" % T))
        B, F = scr(phi, 0, 0), scr(phi, wd, 0)
        ln, a = seg(B, F)
        ks["ssh"].append((t, "transform:translate(%dpx,%dpx) rotate(%ddeg);width:%dpx" % (B[0], B[1], unwrap("ssh", a), ln)))
    css = "".join(_kf(n, v) for n, v in ks.items())
    css += _kf("tjw", [(0, "gap:24px"), (30, "gap:24px"), (35, "gap:12px"), (72, "gap:12px"), (73, "gap:24px"), (100, "gap:24px")])
    css += _kf("thd", [(0, "opacity:0"), (34, "opacity:0"), (35, "opacity:1"), (71, "opacity:1"), (72, "opacity:0"), (100, "opacity:0")])
    css += _kf("trg", [(0, "opacity:0"), (28, "opacity:0"), (30, "opacity:1;transform:scale(1.25)"), (36, "opacity:1;transform:scale(.9)"), (38, "opacity:0"),
                       (64, "opacity:0"), (66, "opacity:1;transform:scale(1.25)"), (72, "opacity:1;transform:scale(.9)"), (74, "opacity:0"), (100, "opacity:0")])
    css += (".lk{position:absolute;left:0;top:0;transform-origin:0 50%;border-radius:14px;"
            "background:radial-gradient(circle,#5E6A7C 0 2.2px,transparent 2.8px) 0 50%/40px 100% repeat-x,linear-gradient(180deg,#8794A6,#DCE2EA 40%,#C9D1DB 60%,#8794A6)}"
            ".mo{position:absolute;border:3px solid #16202E;border-radius:9px;background:radial-gradient(circle,#16202E 0 3px,#B7C0CC 3.5px 8px,transparent 9px),linear-gradient(#3A4658,#2B3442)}"
            ".bd{position:absolute;width:22px;height:22px;border-radius:50%;background:#16202E;color:#fff;font-size:14px;font-weight:800;display:flex;align-items:center;justify-content:center;z-index:9}")
    an = lambda n: f"animation:{n} {cyc}s infinite"
    hx, hy = cx, cy - k * hs * sc
    h = ""
    # 바닥 그림자(위에서 본 팔 방향 = ① 어깨 회전)
    h += f'<i style="position:absolute;left:0;top:0;height:22px;margin-top:-11px;transform-origin:0 50%;border-radius:11px;background:rgba(22,32,46,.16);filter:blur(3px);{an("ssh")}"></i>'
    h += f'<div style="position:absolute;left:0;top:0;filter:drop-shadow(4px 8px 5px rgba(22,32,46,.28));z-index:4">'
    # 어깨 기둥(받침 → 어깨 높이)
    h += f'<i style="position:absolute;left:{cx - 24}px;top:{hy:.0f}px;width:48px;height:{cy - hy + 10:.0f}px;border-radius:10px;background:linear-gradient(90deg,#4B5568,#7D8899 50%,#4B5568)"></i>'
    h += f'<i class="lk" style="height:32px;margin-top:-16px;{an("su")}"></i>'
    h += f'<i class="mo" style="left:{hx - 24:.0f}px;top:{hy - 24:.0f}px;width:48px;height:48px"></i><b class="bd" style="left:{hx - 46:.0f}px;top:{hy - 40:.0f}px">②</b>'
    h += f'<i class="lk" style="height:26px;margin-top:-13px;{an("sf")}"></i>'
    h += f'<div style="position:absolute;left:0;top:0;{an("se")}"><i class="mo" style="left:-21px;top:-19px;width:42px;height:38px"></i><b class="bd" style="left:-11px;top:-48px">③</b></div>'
    # 손목 → 집게(손목 블록 + 두 손가락, 손가락은 집게 방향으로)
    h += (f'<div style="position:absolute;left:0;top:0;width:0;height:0;transform-origin:0 0;{an("sg")}">'
          f'<i class="mo" style="left:-15px;top:-14px;width:40px;height:28px"></i>'
          f'<div style="position:absolute;left:24px;top:-30px;width:44px;height:60px;display:flex;flex-direction:column;justify-content:center;{an("tjw")}">'
          f'<i style="display:block;width:44px;height:9px;clip-path:polygon(0 0,100% 30%,100% 70%,0 100%);background:linear-gradient(90deg,#2B3442,#8794A6)"></i>'
          f'<i style="display:block;width:44px;height:9px;clip-path:polygon(0 0,100% 30%,100% 70%,0 100%);background:linear-gradient(90deg,#2B3442,#8794A6)"></i></div>'
          f'</div>')
    h += (f'<div style="position:absolute;left:0;top:0;{an("sw")}">'
          f'<i style="position:absolute;left:-26px;top:-26px;width:52px;height:52px;border-radius:50%;border:5px solid {ACC};box-sizing:border-box;animation:trg {cyc}s infinite;opacity:0"></i>'
          f'<div style="position:absolute;left:0;top:-6px;animation:thd {cyc}s infinite;opacity:0">{balm_html}</div>'
          f'<b class="bd" style="left:18px;top:-30px;background:#F06A00">⑥</b></div>')
    h += "</div>"
    return css, h
