"""11/12 3차 움직이는 그림 — 표지 · 문제 · 해결 · 전체 구성(보관함 R 설명) · 한 바퀴 · 맡기기 5단계
x-embed 는 시스템 글꼴, CSS @keyframes 만 사용. 각 embed 16KB 이하."""
import re
from embeds import BASE, wrap, INK, CARD, LINE, SUB, ACC, ACCL, SOFT

DARK2 = "#0F1724"
# 물건 모양(위에서 본 모습) — 크기는 w,h
ITEM = {
    "phone": (34, 60, "border-radius:9px;background:linear-gradient(160deg,#3A4658 0%,#111827 45%,#05070B 100%);border:3px solid #4B5568;box-shadow:inset 0 0 0 2px #0B0F16"),
    "white": (34, 60, "border-radius:9px;background:linear-gradient(160deg,#FFFFFF,#E3E6EB);border:3px solid #C9CED6"),
    "balm": (20, 58, "border-radius:3px;background:linear-gradient(90deg,rgba(255,255,255,0) 10%,rgba(255,255,255,.5) 30%,rgba(255,255,255,0) 50%),linear-gradient(to bottom,#E3264E 0,#C4173C 66%,#9AA0A8 66% 69%,#FFFFFF 69%,#E6E7EA 100%)"),
    "cream": (34, 76, "background:transparent"),
    "batt": (34, 52, "border-radius:9px;background:linear-gradient(160deg,#FFFFFF,#DADFE6);border:2px solid #B9C0CA"),
}
ICSS = "".join(f".i-{k}{{position:absolute;width:{w}px;height:{h}px;margin-left:-{w // 2}px;margin-top:-{h // 2}px;{s};box-shadow:0 6px 14px rgba(0,0,0,.28)}}"
               for k, (w, h, s) in ITEM.items())
ICSS += (".i-cream{box-shadow:none!important;filter:drop-shadow(0 5px 7px rgba(0,0,0,.3))}"
         ".i-cream:before{content:'';position:absolute;left:9px;bottom:0;width:16px;height:8px;border-radius:2px;background:#1E2A44}"
         ".i-cream:after{content:'';position:absolute;left:12px;bottom:7px;width:10px;height:7px;background:#2C3A5C}"
         ".i-cream .cb{position:absolute;left:0;top:0;width:34px;height:63px;clip-path:polygon(0 0,100% 0,100% 12%,86% 100%,14% 100%,0 12%);"
         "background:repeating-linear-gradient(90deg,rgba(0,0,0,.12) 0 2px,transparent 2px 5px) top/100% 11% no-repeat,"
         "linear-gradient(#FFFFFF,#FFFFFF) 50% 45%/62% 17% no-repeat,"
         "radial-gradient(circle,rgba(255,255,255,.95) 0 1.6px,transparent 2px) 0 0/9px 9px,"
         "linear-gradient(90deg,rgba(255,255,255,0) 10%,rgba(255,255,255,.4) 32%,rgba(255,255,255,0) 54%),"
         "linear-gradient(to bottom,#BFE4F8,#9FD0EF)}")
KIOSK = (".kio{position:absolute;width:86px;height:120px;border-radius:12px;background:#E9EDF2;border:3px solid #9AA6B8}"
         ".kio:before{content:'';position:absolute;left:10px;top:10px;width:60px;height:46px;border-radius:6px;background:#16202E}"
         ".kio:after{content:'';position:absolute;left:18px;top:74px;width:44px;height:8px;border-radius:4px;background:#9AA6B8}")


def item(kind, x, y, extra=""):
    inner = '<i class="cb"></i>' if kind == "cream" else ""
    return f'<div class="i-{kind}" style="left:{x}px;top:{y}px;{extra}">{inner}</div>'


def kf(name, frames):
    return f"@keyframes {name}{{" + "".join(f"{p}%{{{v}}}" for p, v in frames) + "}"


# ───────── 표지: 양 옆 역에서 본센터로 물건이 들어온다 ─────────
def cover():
    W, H, CYC = 1664, 180, 8
    L, C, R, Y = 168, 836, 1488, 105
    css = ICSS
    css += f".ln{{position:absolute;left:{L}px;top:{Y - 6}px;width:{R - L}px;height:12px;border-radius:6px;background:linear-gradient(90deg,{ACC},#FF9A3D 50%,{ACC})}}"
    css += f".st{{position:absolute;top:{Y}px;width:48px;height:48px;margin:-24px 0 0 -24px;border-radius:50%;background:{DARK2};border:8px solid {ACC}}}"
    css += f".hub{{position:absolute;left:{C}px;top:{Y}px;width:72px;height:72px;margin:-36px 0 0 -36px;border-radius:50%;background:{ACCL};border:10px solid #F7F5F1;animation:hp 2.5s infinite;z-index:2}}"
    css += kf("hp", [(0, "box-shadow:0 0 0 0 rgba(246,161,91,.55)"), (70, "box-shadow:0 0 0 26px rgba(246,161,91,0)"), (100, "box-shadow:0 0 0 0 rgba(246,161,91,0)")])
    fade = [(0, "opacity:0;filter:blur(10px)"), (16, "opacity:1;filter:blur(0)"), (80, "opacity:1;filter:blur(0)"), (97, "opacity:0;filter:blur(7px)"), (100, "opacity:0;filter:blur(7px)")]
    css += kf("fa", fade)
    css += kf("gl", [(0, f"transform:translateX({L}px) scale(.8)"), (16, f"transform:translateX({L + 100}px) scale(1.2)"), (80, f"transform:translateX({C - 150}px) scale(1.2)"), (100, f"transform:translateX({C - 45}px) scale(.6)")])
    css += kf("gr", [(0, f"transform:translateX({R}px) scale(.8)"), (16, f"transform:translateX({R - 100}px) scale(1.2)"), (80, f"transform:translateX({C + 150}px) scale(1.2)"), (100, f"transform:translateX({C + 45}px) scale(.6)")])
    body = f'<div class="ln"></div><div class="st" style="left:{L}px"></div><div class="st" style="left:{R}px"></div><div class="hub"></div>'
    left = [("phone", 0), ("balm", -4)]
    right = [("batt", -2), ("cream", -6)]
    for side, lst in (("gl", left), ("gr", right)):
        for k, d in lst:
            body += (f'<div style="position:absolute;left:0;top:{Y - 44}px;animation:{side} {CYC}s linear infinite;animation-delay:{d}s">'
                     f'<div style="position:relative;animation:fa {CYC}s linear infinite;animation-delay:{d}s;opacity:0">{item(k, 0, 0)}</div></div>')
    return wrap(W, H, css, body)


# ───────── 문제 3장: 카드 안 그림 ─────────
def prob(n):
    W, H, CYC = 445, 180, 6
    css = ICSS + KIOSK + BASE.split("@keyframes dash")[0][:0]
    css += f".q{{position:absolute;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;background:{SOFT};border:3px solid {ACC};color:{ACC};font-size:26px;font-weight:900;display:flex;align-items:center;justify-content:center;opacity:0}}"
    css += f".ok{{position:absolute;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;background:#2E9E5B;color:#fff;font-size:28px;font-weight:900;display:flex;align-items:center;justify-content:center;opacity:0}}"
    body = ""
    if n == 0:  # 주운 사람: ? 가 뜨다가 키오스크에 넣는다
        css += kf("ph", [(0, "transform:translate(80px,95px);opacity:0"), (6, "transform:translate(80px,95px);opacity:1"), (22, "transform:translate(80px,85px)"),
                         (38, "transform:translate(80px,95px)"), (48, "transform:translate(80px,90px);opacity:1"), (68, "transform:translate(352px,96px) scale(.55);opacity:1"),
                         (74, "transform:translate(352px,96px) scale(.4);opacity:0"), (100, "transform:translate(352px,96px) scale(.4);opacity:0")])
        for i, (x, y) in enumerate([(30, 40), (130, 28), (170, 92)]):
            s = 8 + i * 9
            css += kf(f"q{i}", [(0, "opacity:0;transform:scale(.4)"), (s, "opacity:0;transform:scale(.4)"), (s + 4, "opacity:1;transform:scale(1)"), (44, "opacity:1;transform:scale(1)"), (50, "opacity:0;transform:scale(.6)"), (100, "opacity:0")])
            body += f'<div class="q" style="left:{x}px;top:{y}px;animation:q{i} {CYC}s infinite">?</div>'
        css += kf("kg", [(0, "box-shadow:none"), (66, "box-shadow:none"), (72, "box-shadow:0 0 0 10px rgba(240,106,0,.35)"), (92, "box-shadow:0 0 0 10px rgba(240,106,0,.35)"), (98, "box-shadow:none"), (100, "box-shadow:none")])
        css += kf("ck", [(0, "opacity:0"), (74, "opacity:0;transform:scale(.4)"), (80, "opacity:1;transform:scale(1)"), (95, "opacity:1"), (100, "opacity:0")])
        body += '<div class="kio" style="left:310px;top:36px;animation:kg 6s infinite"></div>'
        body += f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0"><path d="M200 96 L290 96" stroke="#C9C1B3" stroke-width="4" stroke-dasharray="8 8" fill="none"/></svg>'
        body += f'<div style="position:absolute;left:0;top:0;animation:ph {CYC}s infinite">{item("phone", 0, 0)}</div>'
        body += f'<div class="ok" style="left:396px;top:40px;animation:ck {CYC}s infinite">✓</div>'
    elif n == 1:  # 잃어버린 사람: 역을 하나씩 뒤지다가, 한 번에 검색
        xs = [72, 222, 372]
        css += f".s{{position:absolute;top:110px;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;background:{CARD};border:7px solid {LINE}}}"
        css += f".lb{{position:absolute;top:140px;width:140px;margin:0 0 0 -70px;text-align:center;white-space:nowrap;font-size:22px;font-weight:800;color:{SUB}}}"
        css += f".mg{{position:absolute;left:0;top:0;width:60px;height:60px;margin:-30px 0 0 -30px;border-radius:50%;border:7px solid {INK};background:rgba(255,255,255,.6)}}.mg:after{{content:'';position:absolute;left:46px;top:46px;width:26px;height:8px;border-radius:4px;background:{INK};transform:rotate(45deg)}}"
        css += kf("mv", [(0, f"transform:translate({xs[0]}px,52px);opacity:1"), (12, f"transform:translate({xs[0]}px,52px)"), (20, f"transform:translate({xs[1]}px,52px)"),
                         (32, f"transform:translate({xs[1]}px,52px)"), (40, f"transform:translate({xs[2]}px,52px)"), (50, f"transform:translate({xs[2]}px,52px);opacity:1"), (55, f"transform:translate({xs[2]}px,52px);opacity:0"), (100, "opacity:0")])
        css += kf("all", [(0, f"border-color:{LINE}"), (56, f"border-color:{LINE};box-shadow:none"), (60, f"border-color:{ACC};box-shadow:0 0 0 10px rgba(240,106,0,.3)"), (94, f"border-color:{ACC};box-shadow:0 0 0 10px rgba(240,106,0,.3)"), (100, f"border-color:{LINE}")])
        css += kf("tag", [(0, "opacity:0"), (58, "opacity:0;transform:translateY(8px)"), (63, "opacity:1;transform:none"), (94, "opacity:1"), (100, "opacity:0")])
        body += f'<div style="position:absolute;left:{xs[0]}px;top:107px;width:{xs[2] - xs[0]}px;height:6px;background:{LINE};border-radius:3px"></div>'
        for i, (x, nm) in enumerate(zip(xs, ["중앙역", "부산역", "초량역"])):
            s = i * 20
            css += kf(f"qq{i}", [(0, "opacity:0"), (s + 6, "opacity:0"), (s + 9, "opacity:1"), (s + 16, "opacity:1"), (s + 19, "opacity:0"), (100, "opacity:0")])
            body += f'<div class="s" style="left:{x}px;animation:all {CYC}s infinite"></div><p class="lb" style="left:{x}px">{nm}</p>'
            body += f'<div class="q" style="left:{x + 34}px;top:26px;animation:qq{i} {CYC}s infinite">?</div>'
        body += f'<div style="position:absolute;left:0;top:0;animation:mv {CYC}s infinite"><div class="mg"></div></div>'
        body += f'<p style="position:absolute;left:0;top:6px;width:{W}px;margin:0;text-align:center;font-size:24px;font-weight:800;color:#fff;animation:tag {CYC}s infinite;opacity:0"><span style="background:{ACC};border-radius:999px;padding:4px 18px">모든 역 한 번에</span></p>'
    else:  # 보관하는 쪽: 똑같은 두 휴대폰 → 확인 질문 → 주인 확인
        css += kf("qx", [(0, "opacity:0"), (6, "opacity:1"), (30, "opacity:1"), (34, "opacity:0"), (100, "opacity:0")])
        css += kf("card", [(0, "opacity:0;transform:translateY(10px)"), (34, "opacity:0;transform:translateY(10px)"), (40, "opacity:1;transform:none"), (90, "opacity:1"), (96, "opacity:0")])
        css += kf("pick", [(0, "box-shadow:none"), (55, "box-shadow:none"), (60, "box-shadow:0 0 0 10px rgba(46,158,91,.45)"), (94, "box-shadow:0 0 0 10px rgba(46,158,91,.45)"), (100, "box-shadow:none")])
        css += kf("dim", [(0, "opacity:1"), (55, "opacity:1"), (60, "opacity:.35"), (94, "opacity:.35"), (100, "opacity:1")])
        css += kf("ck", [(0, "opacity:0"), (58, "opacity:0;transform:scale(.4)"), (63, "opacity:1;transform:scale(1)"), (94, "opacity:1"), (100, "opacity:0")])
        body += f'<div style="position:absolute;left:0;top:0;width:100px;height:100px">{item("phone", 70, 100, f"animation:pick {CYC}s infinite")}</div>'
        body += f'<div style="position:absolute;left:0;top:0;animation:dim {CYC}s infinite">{item("phone", 170, 100)}</div>'
        body += f'<div class="q" style="left:120px;top:40px;animation:qx {CYC}s infinite">?</div>'
        body += f'<div class="ok" style="left:100px;top:60px;animation:ck {CYC}s infinite">✓</div>'
        body += (f'<div style="position:absolute;left:225px;top:34px;width:210px;padding:14px 16px;border-radius:16px;background:{INK};color:#F7F5F1;font-size:21px;line-height:1.35;animation:card {CYC}s infinite;opacity:0">'
                 f'<b style="color:{ACCL};font-size:18px">확인 질문</b><br>뒷면 스티커는<br>무슨 색인가요?</div>')
    return wrap(W, H, css, body)


# ───────── 해결: ①~④를 지나며 단계마다 관제탑과 주고받는다 ─────────
def solution():
    W, H, CYC = 1664, 540, 16
    xs = [172, 612, 1052, 1492]
    LY = 330
    logs = ["① 습득 접수 → 물건 1행 기록", "② 품목 줄 R4-1 칸 배정", "③ 확인 질문 통과 → 찾기 번호", "④ 반환 승인 → 로봇 실행"]
    names = [("① 맡기기", "역 키오스크 · 자동 촬영"), ("② 보관", "본센터 · 품목별 칸"), ("③ 찾기", "웹 · 챗봇 · 확인 질문"), ("④ 돌려받기", "본센터 키오스크 · 로봇팔")]
    css = ICSS
    css += f".tw{{position:absolute;left:100px;top:0;width:1464px;height:134px;border-radius:28px;background:{INK};display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;animation:tg {CYC / 4}s infinite}}"
    css += ".tw b{font-size:44px;color:#F7F5F1}"
    css += kf("tg", [(0, "box-shadow:0 8px 24px rgba(22,32,46,.12)"), (45, "box-shadow:0 8px 24px rgba(22,32,46,.12)"), (52, "box-shadow:0 0 0 12px rgba(240,106,0,.35)"), (80, "box-shadow:0 0 0 12px rgba(240,106,0,.35)"), (90, "box-shadow:0 8px 24px rgba(22,32,46,.12)"), (100, "box-shadow:0 8px 24px rgba(22,32,46,.12)")])
    css += f".lg{{position:absolute;left:100px;top:84px;width:1464px;text-align:center;margin:0;font-size:28px;color:{ACCL};font-weight:700;opacity:0}}"
    css += f".ln{{position:absolute;left:{xs[0]}px;top:{LY - 10}px;width:{xs[-1] - xs[0]}px;height:20px;border-radius:10px;background:{ACC}}}"
    css += f".st{{position:absolute;top:{LY}px;width:68px;height:68px;margin:-34px 0 0 -34px;border-radius:50%;background:{CARD};border:12px solid {ACC}}}"
    css += f".nm{{position:absolute;top:{LY + 56}px;width:340px;margin-left:-170px;text-align:center}}.nm h3{{margin:0;font-size:44px;color:{INK}}}.nm p{{margin:4px 0 0;font-size:28px;color:{SUB}}}"
    css += f".pu{{position:absolute;width:24px;height:24px;margin:-12px 0 0 -12px;border-radius:50%;opacity:0}}"
    body = f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0">'
    for x in xs:
        body += f'<line x1="{x}" y1="134" x2="{x}" y2="{LY - 34}" stroke="#8A93A3" stroke-width="3" stroke-dasharray="8 8"/>'
    body += "</svg>"
    body += '<div class="tw"><b style="margin-bottom:34px">AI 관제탑</b></div><div class="ln"></div>'
    # 물건 이동
    mv = [(0, f"transform:translate({xs[0]}px,{LY - 62}px);opacity:0;filter:blur(8px)"), (4, f"opacity:1;filter:blur(0)")]
    for p in range(1, 4):
        s = p * 25
        mv += [(s, f"transform:translate({xs[p - 1]}px,{LY - 62}px)"), (s + 6, f"transform:translate({xs[p]}px,{LY - 62}px)")]
    mv += [(94, f"transform:translate({xs[3]}px,{LY - 62}px);opacity:1;filter:blur(0)"), (100, f"transform:translate({xs[3]}px,{LY - 62}px);opacity:0;filter:blur(8px)")]
    css += kf("it", mv)
    for p in range(4):
        s = p * 25
        x = xs[p]
        css += kf(f"up{p}", [(0, f"opacity:0;transform:translate({x}px,{LY - 40}px)"), (s + 7, f"opacity:0;transform:translate({x}px,{LY - 40}px)"), (s + 8, f"opacity:1;transform:translate({x}px,{LY - 40}px)"),
                             (s + 12, f"opacity:1;transform:translate({x}px,140px)"), (s + 13, f"opacity:0;transform:translate({x}px,140px)"), (100, "opacity:0")])
        css += kf(f"dn{p}", [(0, f"opacity:0;transform:translate({x}px,140px)"), (s + 15, f"opacity:0;transform:translate({x}px,140px)"), (s + 16, f"opacity:1;transform:translate({x}px,140px)"),
                             (s + 20, f"opacity:1;transform:translate({x}px,{LY - 40}px)"), (s + 21, f"opacity:0;transform:translate({x}px,{LY - 40}px)"), (100, "opacity:0")])
        css += kf(f"lg{p}", [(0, "opacity:0"), (s + 12, "opacity:0;transform:translateY(8px)"), (s + 14, "opacity:1;transform:none"), (s + 24, "opacity:1"), (s + 25, "opacity:0"), (100, "opacity:0")]) if p < 3 else \
            kf(f"lg{p}", [(0, "opacity:0"), (s + 12, "opacity:0;transform:translateY(8px)"), (s + 14, "opacity:1;transform:none"), (96, "opacity:1"), (100, "opacity:0")])
        css += kf(f"sf{p}", [(0, f"background:{CARD}"), (s + 20, f"background:{CARD}"), (s + 21, f"background:{ACCL}"), (97, f"background:{ACCL}"), (100, f"background:{CARD}")])
        css += kf(f"nh{p}", [(0, "opacity:.45"), (s, "opacity:.45"), (s + 2, "opacity:1"), (97, "opacity:1"), (100, "opacity:.45")])
        body += f'<div class="st" style="left:{x}px;animation:sf{p} {CYC}s infinite"></div>'
        body += f'<div class="nm" style="left:{x}px;animation:nh{p} {CYC}s infinite"><h3>{names[p][0]}</h3><p>{names[p][1]}</p></div>'
        body += f'<div class="pu" style="left:0;top:0;background:{ACC};box-shadow:0 0 0 7px rgba(240,106,0,.25);animation:up{p} {CYC}s infinite"></div>'
        body += f'<div class="pu" style="left:0;top:0;background:#2E9E5B;box-shadow:0 0 0 7px rgba(46,158,91,.25);animation:dn{p} {CYC}s infinite"></div>'
        body += f'<p class="lg" style="animation:lg{p} {CYC}s infinite">{logs[p]}</p>'
    body += f'<div style="position:absolute;left:0;top:0;animation:it {CYC}s infinite">{item("phone", 0, 0)}</div>'
    body += (f'<div style="position:absolute;left:0;width:{W}px;justify-content:center;top:{H - 36}px;display:flex;gap:28px;font-size:22px;color:{SUB}">'
             f'<span><i style="display:inline-block;width:16px;height:16px;border-radius:50%;background:{ACC};margin-right:8px"></i>단계 → 관제탑: 보고</span>'
             f'<span><i style="display:inline-block;width:16px;height:16px;border-radius:50%;background:#2E9E5B;margin-right:8px"></i>관제탑 → 단계: 기록 · 확인</span></div>')
    return wrap(W, H, css, body)


# ───────── 전체 구성: 역 · 관제탑 · 본센터(보관함 R 줄 설명) ─────────
def system():
    W, H, CYC = 1664, 650, 36
    css = ICSS + KIOSK
    css += f".bx{{position:absolute;border-radius:26px;padding:22px 26px}}.bx h4{{margin:0;font-size:24px;font-weight:800;color:#B5500A}}.bx h3{{margin:2px 0 0;font-size:28px;color:{INK};white-space:nowrap}}"
    css += f".ch{{background:#24324A;color:#F7F5F1;border-radius:12px;padding:9px 12px;font-size:21px;font-weight:700;white-space:nowrap}}.ch small{{display:block;color:{ACCL};font-weight:600;font-size:17px}}"
    css += f".cell{{position:absolute;width:165px;height:92px;border-radius:14px;background:#FFFDF9;border:2px dashed #D6C9B5}}"
    css += f".hd{{position:absolute;top:60px;width:165px;text-align:center;margin:0}}.hd b{{display:block;font-size:30px;color:{INK}}}.hd span{{font-size:20px;color:{SUB}}}"
    css += f".rw{{position:absolute;left:840px;width:96px;margin:0;font-size:20px;color:{SUB};line-height:1.25;font-weight:700}}"
    css += f".lb{{position:absolute;margin:0;font-size:22px;font-weight:800;color:{INK};text-align:center}}"
    css += ".dot{position:absolute;left:0;top:0;width:18px;height:18px;border-radius:50%;background:" + ACC + ";box-shadow:0 0 0 6px rgba(240,106,0,.25);animation:mv 2.2s linear infinite}"
    css += "@keyframes mv{from{offset-distance:0%}to{offset-distance:100%}}"
    base = css
    # 왼쪽: 역 키오스크 · 분실인 휴대폰
    body = f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0">'
    paths = ["M300 170 C340 170 340 250 380 250", "M300 500 C340 500 340 400 380 400", "M720 330 C760 330 760 520 800 520"]
    for d in paths:
        body += f'<path d="{d}" fill="none" stroke="#C9C1B3" stroke-width="4" stroke-dasharray="8 8"/>'
    body += "</svg>"
    body += (f'<div class="bx" style="left:0;top:20px;width:300px;height:300px;background:{CARD};border:2px solid {LINE}"><h4>역 2곳</h4><h3>습득물 등록기계</h3></div>'
             f'<div class="kio" style="left:40px;top:140px"></div><div class="kio" style="left:170px;top:140px"></div>'
             f'<p class="lb" style="left:20px;top:268px;width:130px">중앙역</p><p class="lb" style="left:150px;top:268px;width:130px">초량역</p>')
    body += (f'<div class="bx" style="left:0;top:360px;width:300px;height:280px;background:{CARD};border:2px solid {LINE}"><h4>분실인</h4><h3>휴대폰 웹 · 챗봇</h3></div>'
             f'<div style="position:absolute;left:110px;top:470px;width:80px;height:140px;border-radius:16px;background:#16202E;border:4px solid #4B5568">'
             f'<div style="margin:16px 8px;height:20px;border-radius:8px;background:{ACCL}"></div><div style="margin:0 8px 8px;height:14px;border-radius:6px;background:#4B5568"></div><div style="margin:0 8px;height:14px;width:40px;border-radius:6px;background:#4B5568"></div></div>')
    # 가운데: 관제탑 PC
    chips = [("관제탑 서버", "포트 8100"), ("팀 DB", "PostgreSQL"), ("sLLM", "Mi:dm 2.0 mini"), ("VLM", "Qwen3-VL"), ("기록 · 알림", "Langfuse·디스코드")]
    body += (f'<div class="bx" style="left:380px;top:20px;width:340px;height:620px;background:{INK};display:flex;flex-direction:column;gap:12px;animation:tp 2.6s infinite">'
             f'<h4 style="color:{ACCL}">관제탑 PC</h4><h3 style="color:#F7F5F1;margin-bottom:10px">AI 관제탑</h3>'
             + "".join(f'<div class="ch">{a}<small>{b}</small></div>' for a, b in chips) + "</div>")
    css += kf("tp", [(0, "box-shadow:0 0 0 0 rgba(240,106,0,.45)"), (70, "box-shadow:0 0 0 18px rgba(240,106,0,0)"), (100, "box-shadow:0 0 0 0 rgba(240,106,0,0)")])
    for d in paths:
        for k in (0, 1):
            body += f'<div class="dot" style="offset-path:path(\'{d}\');animation-delay:{-1.1 * k}s"></div>'
    _bl, _cl = body, css
    body, css = "", base
    # 오른쪽: 본센터 — 실제 작업대처럼 위 제출보관함 · 가운데 보관함 · 아래 로봇팔
    body += f'<div class="bx" style="left:800px;top:0;width:864px;height:650px;background:{SOFT};border:3px solid {ACC}"><h4>부산역 본센터</h4><h3>보관 · 반환 구역</h3></div>'
    css += kf("ob", [(0, "box-shadow:none"), (60, "box-shadow:none"), (64, "box-shadow:0 0 0 10px rgba(240,106,0,.3)"), (90, "box-shadow:0 0 0 10px rgba(240,106,0,.3)"), (96, "box-shadow:none"), (100, "box-shadow:none")])
    body += (f'<div style="position:absolute;left:1205px;top:26px;width:170px;height:104px;border-radius:14px;background:#FFFFFF;border:4px dashed {ACC};animation:ob {CYC}s infinite"></div>'
             f'<p class="lb" style="left:1390px;top:54px;width:150px;text-align:left;font-size:22px;color:#B5500A">제출보관함</p>')
    cols = [("R1", "휴대폰"), ("R2", "보조배터리"), ("R3", "핸드크림"), ("R4", "립밤")]
    gx = [946, 1119, 1292, 1465]
    for i, (r, nm) in enumerate(cols):
        body += f'<p class="hd" style="left:{gx[i]}px;top:136px"><b style="{"color:" + ACC if r == "R4" else ""}">{r}</b><span>{nm}</span></p>'
        for j in range(2):
            body += f'<div class="cell" style="left:{gx[i]}px;top:{210 + j * 102}px;{"animation:c41 36s infinite" if (i, j) == (3, 0) else ""}"></div>'
    body += '<p class="rw" style="top:232px">-1<br>먼 칸</p><p class="rw" style="top:334px">-2<br>로봇 쪽</p>'
    fill = {(0, 0): "phone", (0, 1): "white", (1, 0): "batt", (2, 0): "cream"}
    for (i, j), k in fill.items():
        rot = "transform:rotate(45deg)"  # 휴대폰·보조배터리·핸드크림 모두 '/'(핸드크림은 뚜껑이 왼쪽 아래)
        body += item(k, gx[i] + 82, 210 + j * 102 + 46, rot)
    css += kf("c41", [(0, "border:2px dashed #D6C9B5"), (4, f"border:4px solid {ACC};box-shadow:0 0 0 8px rgba(240,106,0,.25)"), (34, f"border:4px solid {ACC};box-shadow:0 0 0 8px rgba(240,106,0,.25)"), (40, "border:2px dashed #D6C9B5;box-shadow:none"), (100, "border:2px dashed #D6C9B5")])
    css += kf("tip", [(0, "opacity:0;transform:translateY(6px)"), (5, "opacity:1;transform:none"), (34, "opacity:1"), (39, "opacity:0"), (100, "opacity:0")])
    body += (f'<div style="position:absolute;left:1452px;top:388px;padding:6px 10px;border-radius:12px;background:{INK};color:#F7F5F1;font-size:17px;font-weight:700;white-space:nowrap;animation:tip {CYC}s infinite;opacity:0;z-index:3">'
             f'<b style="color:{ACCL}">R4-1</b> = 4번 줄 · 먼 칸</div>')
    # 칸에 있는 립밤(집기 전) · 제출보관함의 립밤(놓은 뒤)
    css += kf("b0", [(0, "opacity:1"), (40.4, "opacity:1"), (40.9, "opacity:0"), (97, "opacity:0"), (100, "opacity:1")])
    css += kf("b2", [(0, "opacity:0"), (74.5, "opacity:0"), (75.0, "opacity:1"), (93, "opacity:1"), (97, "opacity:0"), (100, "opacity:0")])
    body += f'<div style="position:absolute;left:0;top:0;animation:b0 {CYC}s infinite">{item("balm", 1547, 256)}</div>'
    body += f'<div style="position:absolute;left:0;top:0;animation:b2 {CYC}s infinite">{item("balm", 1290, 78)}</div>'
    # SO-101 로봇팔: 위에서는 ① 어깨 회전(방향)만, 옆에서는 ②③④ 굽힘(마디 길이 고정)
    import arm
    body += (f'<div style="position:absolute;left:1238px;top:508px;width:104px;height:104px;border-radius:50%;background:radial-gradient(circle,#4B5568 0 28%,#C3CBD6 29% 62%,#E3E8EF 63% 100%);border:4px solid #9AA6B8;box-shadow:inset 0 0 0 8px #D9DEE6"></div>'
             f'<b style="position:absolute;left:1322px;top:498px;width:24px;height:24px;border-radius:50%;background:#16202E;color:#fff;font-size:15px;font-weight:800;display:flex;align-items:center;justify-content:center;z-index:6">①</b>'
                          f'<p style="position:absolute;left:990px;top:616px;width:236px;margin:0;text-align:right;font-size:16px;font-weight:700;color:#4A5568">비스듬히 위에서 본 모습 · <span style="color:#B5500A">① 받침</span></p>')
    tacss, tahtml = arm.top3(1290, 560, CYC, item("balm", 0, 0))
    scss, shtml = arm.side("a", CYC, 46, 119, 148, s=0.86, labels=True, wc=288)
    sidecard = (f'<div style="position:absolute;left:0;top:0;width:288px;height:176px;border-radius:16px;background:#FFFFFF;border:2px solid #E3D6C4;box-sizing:border-box;overflow:hidden">{shtml}'
                f'<p style="position:absolute;left:12px;top:152px;margin:0;font-size:15px;font-weight:800;color:#B5500A">옆에서 본 모습</p></div>')
    body += (f'<p style="position:absolute;left:1368px;top:612px;width:290px;margin:0;font-size:14px;line-height:1.3;color:#4A5568;font-weight:700">① 어깨 회전 ② 어깨 ③ 팔꿈치<br>④ 손목 굽힘 ⑤ 손목 회전 ⑥ 집게</p>')
    # 본센터 키오스크(왼쪽 아래)
    css += kf("ka", [(0, "opacity:0"), (80, "opacity:0;transform:scale(.4)"), (84, "opacity:1;transform:scale(1)"), (93, "opacity:1"), (99, "opacity:0")])
    body += (f'<div class="kio" style="left:858px;top:440px"></div><p class="lb" style="left:826px;top:572px;width:150px;font-size:20px">본센터<br>키오스크</p>'
             f'<div style="position:absolute;left:924px;top:424px;width:44px;height:44px;border-radius:50%;background:#2E9E5B;color:#fff;font-size:26px;font-weight:900;display:flex;align-items:center;justify-content:center;animation:ka {CYC}s infinite;opacity:0">✓</div>')
    return (wrap(800, H, _cl, _bl), wrap(864, H, css, '<div style="position:absolute;left:-800px;top:0;width:1664px;height:650px">' + body + "</div>"), wrap(288, 176, ICSS + scss, sidecard), wrap(864, H, re.search(r'\.i-balm\{[^}]*\}', ICSS).group(0) + tacss, '<div style="position:absolute;left:-800px;top:0;width:1664px;height:650px">' + tahtml + "</div>"))


# ───────── 한 바퀴: 검은 휴대폰이 서서히 나타나 다섯 정거장을 지나 사라진다 ─────────
def route():
    W, H, CYC = 1664, 470, 14
    xs = [166 + i * 333 for i in range(5)]
    st = [("접수", "역 키오스크", "넣으면 자동 촬영, AI가 특징 기록"), ("보관", "본센터", "품목별 칸에 보관, 칸 번호를 DB에"),
          ("찾기", "웹 · 챗봇", "설명하면 후보, 확인 질문 뒤 찾기 번호"), ("반환", "로봇팔", "본인 확인 · 메인 AI 승인 뒤 제출보관함으로"),
          ("인계", "직접 수령", "꺼내고 [물건 받았어요] → 인계 완료")]
    css = ICSS
    css += f".line{{position:absolute;left:{xs[0]}px;top:76px;width:{xs[-1] - xs[0]}px;height:16px;border-radius:8px;background:{ACC}}}"
    css += f".st{{position:absolute;top:58px;width:52px;height:52px;margin-left:-26px;border-radius:50%;background:{CARD};border:10px solid {ACC}}}"
    css += f".c{{position:absolute;top:160px;width:317px;height:300px;border-radius:26px;background:{CARD};border:2px solid {LINE};padding:26px 24px;display:flex;flex-direction:column;gap:10px;box-shadow:0 8px 22px rgba(22,32,46,.08)}}"
    css += f".c i{{font-style:normal;font-size:26px;font-weight:800;color:#B5500A}}.c b{{font-size:38px;color:{INK}}}.c span{{font-size:26px;color:{SUB};line-height:1.45}}"
    seg = 92 / 5
    mv = [(0, f"transform:translate({xs[0]}px,84px) scale(.7);opacity:0;filter:blur(10px)"), (5, f"transform:translate({xs[0]}px,84px) scale(1);opacity:1;filter:blur(0)")]
    for i in range(1, 5):
        a = round(i * seg, 1)
        mv += [(round(a - 6, 1), f"transform:translate({xs[i - 1]}px,84px) scale(1)"), (a, f"transform:translate({xs[i]}px,84px) scale(1)")]
    mv += [(90, f"transform:translate({xs[4]}px,84px) scale(1);opacity:1;filter:blur(0)"), (97, f"transform:translate({xs[4]}px,84px) scale(.7);opacity:0;filter:blur(10px)"),
           (100, f"transform:translate({xs[4]}px,84px) scale(.7);opacity:0;filter:blur(10px)")]
    css += kf("go", mv)
    body = '<div class="line"></div>' + "".join(f'<div class="st" style="left:{x}px"></div>' for x in xs)
    for i, (lab, t, d) in enumerate(st):
        s0 = round(i * seg, 1)
        s1 = round(s0 + seg - 0.5, 1) if i < 4 else 95
        on, off = "border-color:#F06A00;box-shadow:0 0 0 6px rgba(240,106,0,.28),0 8px 22px rgba(22,32,46,.08)", f"border-color:{LINE};box-shadow:0 8px 22px rgba(22,32,46,.08)"
        css += kf(f"h{i}", [(0, off), (max(0, s0 - 0.5), off), (s0 if s0 else 0.5, on), (s1, on), (min(100, s1 + 0.5), off), (100, off)])
        body += f'<div class="c" style="left:{xs[i] - 158}px;animation:h{i} {CYC}s infinite"><i>{lab}</i><div style="flex:1"></div><b>{t}</b><span>{d}</span></div>'
    body += f'<div style="position:absolute;left:0;top:0;animation:go {CYC}s ease-in-out infinite;opacity:0">{item("phone", 0, -2, "width:40px;height:70px;margin:-35px 0 0 -20px")}</div>'
    return wrap(W, H, css, body)


# ───────── 맡기기 5단계 카드 안 그림 ─────────
def found(n):
    W, H, CYC = 260, 150, 5
    css = ICSS + f".box{{position:absolute;left:60px;top:70px;width:140px;height:70px;border:5px solid #9AA6B8;border-top:none;border-radius:0 0 18px 18px;background:#C9CDD3}}"
    body = ""
    if n == 0:  # 넣기
        css += kf("dn", [(0, "transform:translate(130px,40px);opacity:0"), (8, "transform:translate(130px,40px);opacity:1"), (40, "transform:translate(130px,100px)"), (100, "transform:translate(130px,100px);opacity:1")])
        css += kf("hd", [(0, "transform:translate(105px,4px);opacity:0"), (8, "transform:translate(105px,4px);opacity:1"), (40, "transform:translate(105px,50px)"), (52, "transform:translate(105px,50px);opacity:1"), (75, "transform:translate(105px,4px);opacity:0"), (100, "opacity:0")])
        body += '<div class="box"></div>'
        body += f'<div style="position:absolute;left:0;top:0;animation:dn {CYC}s infinite">{item("phone", 0, 0, "transform:rotate(45deg)")}</div>'
        body += f'<div style="position:absolute;left:0;top:0;width:50px;height:46px;border-radius:22px;background:#F2C6A0;border:3px solid #D9A57A;animation:hd {CYC}s infinite"></div>'
    elif n == 1:  # 자동 촬영: 카운트다운 → 찰칵
        css += ".cr{position:absolute;width:30px;height:30px;border-color:" + INK + ";border-style:solid}"
        css += ".nb{position:absolute;left:150px;top:22px;width:80px;text-align:center;margin:0;font-size:48px;font-weight:900;color:" + ACC + ";opacity:0}"
        body += '<div class="cr" style="left:40px;top:12px;border-width:5px 0 0 5px"></div><div class="cr" style="left:150px;top:12px;border-width:5px 5px 0 0"></div>'
        body += '<div class="cr" style="left:40px;top:108px;border-width:0 0 5px 5px"></div><div class="cr" style="left:150px;top:108px;border-width:0 5px 5px 0"></div>'
        body += item("cream", 110, 76, "transform:rotate(45deg)")
        for i, num in enumerate("54321"):
            s = i * 12
            css += kf(f"n{i}", [(0, "opacity:0"), (s, "opacity:0;transform:scale(1.4)"), (s + 2, "opacity:1;transform:scale(1)"), (s + 11, "opacity:1"), (s + 12, "opacity:0"), (100, "opacity:0")])
            body += f'<p class="nb" style="animation:n{i} {CYC}s infinite">{num}</p>'
        css += kf("fl", [(0, "opacity:0"), (60, "opacity:0"), (62, "opacity:.95"), (72, "opacity:0"), (100, "opacity:0")])
        css += kf("sn", [(0, "opacity:0"), (64, "opacity:0;transform:scale(.5)"), (70, "opacity:1;transform:scale(1)"), (95, "opacity:1"), (100, "opacity:0")])
        body += f'<div style="position:absolute;left:0;top:0;width:{W}px;height:{H}px;background:#fff;border-radius:16px;animation:fl {CYC}s infinite;opacity:0"></div>'
        body += f'<div style="position:absolute;left:186px;top:40px;width:62px;height:46px;border-radius:12px;background:{INK};animation:sn {CYC}s infinite;opacity:0"><div style="margin:10px auto;width:24px;height:24px;border-radius:50%;border:4px solid {ACCL}"></div></div>'
    elif n == 2:  # 장소 고르기
        rows = ["대합실", "개찰구 앞", "직접 입력"]
        css += f".r{{position:absolute;left:20px;width:220px;height:38px;border-radius:10px;background:#EEF0F3;font-size:21px;color:{INK};display:flex;align-items:center;padding-left:16px;font-weight:700}}"
        css += kf("hl", [(0, "transform:translateY(8px)"), (25, "transform:translateY(8px)"), (40, "transform:translateY(54px)"), (100, "transform:translateY(54px)")])
        css += kf("tk", [(0, "opacity:0"), (48, "opacity:0;transform:scale(.4)"), (54, "opacity:1;transform:scale(1)"), (95, "opacity:1"), (100, "opacity:0")])
        for i, r in enumerate(rows):
            body += f'<div class="r" style="top:{12 + i * 46}px">{r}</div>'
        body += f'<div style="position:absolute;left:14px;top:0;width:232px;height:46px;border-radius:12px;border:4px solid {ACC};z-index:2;animation:hl {CYC}s infinite"></div>'
        body += f'<div style="position:absolute;left:198px;top:64px;width:34px;height:34px;border-radius:50%;background:#2E9E5B;color:#fff;font-size:22px;font-weight:900;display:flex;align-items:center;justify-content:center;animation:tk {CYC}s infinite;opacity:0">✓</div>'
    elif n == 3:  # 연락처(선택) → 30일 뒤 삭제
        css += f".in{{position:absolute;left:20px;top:20px;width:220px;height:50px;border-radius:12px;background:#fff;border:3px solid #C9CED6;display:flex;align-items:center;gap:8px;padding-left:16px}}"
        css += f".in i{{width:12px;height:12px;border-radius:50%;background:{INK};opacity:0}}"
        body += '<div class="in" style="top:26px">'
        for i in range(7):
            s = 6 + i * 5
            css += kf(f"d{i}", [(0, "opacity:0"), (s, "opacity:0"), (s + 1, "opacity:1"), (62, "opacity:1"), (70, "opacity:0"), (100, "opacity:0")])
            body += f'<i style="animation:d{i} {CYC}s infinite"></i>'
        body += "</div>"
        css += kf("cal", [(0, "opacity:0;transform:translateY(8px)"), (44, "opacity:0;transform:translateY(8px)"), (50, "opacity:1;transform:none"), (95, "opacity:1"), (100, "opacity:0")])
        body += (f'<div style="position:absolute;left:40px;top:86px;display:flex;align-items:center;gap:10px;animation:cal {CYC}s infinite;opacity:0">'
                 f'<div style="width:46px;height:46px;border-radius:10px;background:#fff;border:3px solid {ACC};font-size:20px;font-weight:900;color:{ACC};display:flex;align-items:center;justify-content:center">30</div>'
                 f'<span style="font-size:22px;font-weight:800;color:{INK}">일 뒤 자동 삭제</span></div>')
        body += f'<p style="position:absolute;left:176px;top:2px;margin:0;font-size:18px;font-weight:800;color:#fff;background:{SUB};border-radius:999px;padding:2px 12px">선택</p>'
    else:  # 접수 완료 → 본센터로
        css += kf("dr", [(0, "stroke-dashoffset:120"), (10, "stroke-dashoffset:120"), (35, "stroke-dashoffset:0"), (100, "stroke-dashoffset:0")])
        css += kf("tr", [(0, "transform:translateX(0);opacity:0"), (40, "transform:translateX(0);opacity:0"), (46, "opacity:1"), (88, "transform:translateX(18px);opacity:1"), (96, "transform:translateX(22px);opacity:0"), (100, "opacity:0")])
        body += (f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0"><circle cx="70" cy="70" r="50" fill="#E7F5EC" stroke="#2E9E5B" stroke-width="6"/>'
                 f'<path d="M46 72 L64 90 L96 52" fill="none" stroke="#2E9E5B" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="120" style="animation:dr {CYC}s infinite"/></svg>')
        body += f'<div style="position:absolute;left:126px;top:52px;animation:tr {CYC}s infinite;opacity:0"><span style="font-size:24px;font-weight:900;color:{ACC}">→ 본센터</span></div>'
    return wrap(W, H, css, body)


if __name__ == "__main__":
    for f in (cover, solution, system, route):
        print(f.__name__, len(f().encode()))
    for i in range(3):
        print("prob", i, len(prob(i).encode()))
    for i in range(5):
        print("found", i, len(found(i).encode()))
