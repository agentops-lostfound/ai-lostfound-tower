"""11/12 4차 움직이는 그림 — 돌려받기 카드 5장(14쪽) · 물건 일생 아이콘과 상태 기록(19쪽)"""
from embeds import wrap, INK, CARD, LINE, SUB, ACC, ACCL, SOFT
from embeds2 import ICSS, KIOSK, item, kf

OK = "#2E9E5B"
CHK = (f".ok{{position:absolute;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;background:{OK};color:#fff;font-size:24px;font-weight:900;"
       "display:flex;align-items:center;justify-content:center;opacity:0}")


def ret(n):
    """돌려받기 카드 안 그림(260x150). 3번째 카드는 어두운 배경"""
    W, H, CYC = 260, 150, 5
    css = ICSS + KIOSK + CHK
    body = ""
    if n == 0:  # 본인 확인: 찾기 번호 + 숫자 하나 → ✓
        css += f".fd{{position:absolute;left:24px;width:212px;height:44px;border-radius:10px;background:#fff;border:3px solid #C9CED6;font-size:20px;font-weight:800;color:{INK};display:flex;align-items:center;padding-left:14px;overflow:hidden;white-space:nowrap}}"
        css += kf("t1", [(0, "width:0"), (8, "width:0"), (38, "width:120px"), (100, "width:120px")])
        css += kf("t2", [(0, "opacity:0"), (48, "opacity:0"), (52, "opacity:1"), (100, "opacity:1")])
        css += kf("ck", [(0, "opacity:0"), (60, "opacity:0;transform:scale(.4)"), (66, "opacity:1;transform:scale(1)"), (94, "opacity:1"), (100, "opacity:0")])
        body += f'<div class="fd" style="top:14px"><span style="display:inline-block;overflow:hidden;animation:t1 {CYC}s infinite">C-…0021</span></div>'
        body += f'<div class="fd" style="top:74px;width:120px"><span style="color:{SUB};font-size:16px;margin-right:8px">뒤 첫 자리</span><b style="animation:t2 {CYC}s infinite;opacity:0">•</b></div>'
        body += f'<div class="ok" style="left:196px;top:96px;animation:ck {CYC}s infinite">✓</div>'
    elif n == 1:  # 메인 AI 승인: 세 가지 대조가 차례로 ✓
        body += (f'<div style="position:absolute;left:14px;top:30px;width:88px;height:88px;border-radius:50%;background:{INK};color:#F7F5F1;font-size:19px;font-weight:800;'
                 f'display:flex;align-items:center;justify-content:center;text-align:center;line-height:1.15;animation:hb {CYC}s infinite">메인<br>AI</div>')
        css += kf("hb", [(0, "box-shadow:0 0 0 0 rgba(240,106,0,.5)"), (60, "box-shadow:0 0 0 0 rgba(240,106,0,.5)"), (70, "box-shadow:0 0 0 12px rgba(240,106,0,0)"), (100, "box-shadow:none")])
        for i, t in enumerate(["기록 대조", "칸 위치", "본인 확인"]):
            s = 10 + i * 16
            css += kf(f"r{i}", [(0, "opacity:.25"), (s, "opacity:.25"), (s + 4, "opacity:1"), (96, "opacity:1"), (100, "opacity:.25")])
            body += (f'<div style="position:absolute;left:118px;top:{16 + i * 42}px;display:flex;align-items:center;gap:8px;animation:r{i} {CYC}s infinite;opacity:.25">'
                     f'<i style="display:flex;width:26px;height:26px;border-radius:50%;background:{OK};color:#fff;font-size:16px;font-style:normal;font-weight:900;align-items:center;justify-content:center">✓</i>'
                     f'<b style="font-size:20px;color:{INK};white-space:nowrap">{t}</b></div>')
    elif n == 2:  # 로봇팔(어두운 카드): 칸 번호 → 자세 번호 → 집기 → 제출보관함 (옆에서 본 SO-101, 마디 길이 고정)
        import arm
        CYC = 8
        acss, ahtml = arm.side("r", CYC, 60, 112, 138, s=0.78, dark=True, with_badges=False, wc=260)
        css += acss
        body += (f'<div style="position:absolute;left:10px;top:10px;padding:5px 10px;border-radius:10px;background:#24324A;color:{ACCL};font-size:17px;font-weight:800;white-space:nowrap">'
                 f'R4-1 → pose_7</div>')
        body += ahtml
    elif n == 3:  # 제출보관함: 물건이 내려와 도착
        css += kf("dp", [(0, "transform:translate(130px,20px);opacity:0"), (10, "transform:translate(130px,24px);opacity:1"), (45, "transform:translate(130px,96px)"), (92, "transform:translate(130px,96px);opacity:1"), (100, "opacity:0")])
        css += kf("bg", [(0, "box-shadow:none"), (44, "box-shadow:none"), (50, "box-shadow:0 0 0 10px rgba(240,106,0,.3)"), (92, "box-shadow:0 0 0 10px rgba(240,106,0,.3)"), (100, "box-shadow:none")])
        body += f'<div style="position:absolute;left:50px;top:62px;width:160px;height:80px;border-radius:14px;background:#fff;border:4px dashed {ACC};animation:bg {CYC}s infinite"></div>'
        body += f'<div style="position:absolute;left:0;top:0;animation:dp {CYC}s infinite">{item("balm", 0, 0, "transform:rotate(90deg)")}</div>'
    else:  # [물건 받았어요] 누르기 → 인계 완료
        css += kf("pr", [(0, "transform:scale(1)"), (34, "transform:scale(1)"), (38, "transform:scale(.92);filter:brightness(.9)"), (44, "transform:scale(1);filter:none"), (100, "transform:scale(1)")])
        css += kf("dn", [(0, "opacity:0;transform:translateY(8px)"), (46, "opacity:0;transform:translateY(8px)"), (52, "opacity:1;transform:none"), (94, "opacity:1"), (100, "opacity:0")])
        css += kf("fi", [(0, "transform:translate(226px,118px)"), (18, "transform:translate(170px,58px)"), (36, "transform:translate(140px,46px)"), (60, "transform:translate(226px,118px)"), (100, "transform:translate(226px,118px)")])
        body += (f'<div style="position:absolute;left:30px;top:22px;width:200px;height:50px;border-radius:14px;background:{ACC};color:#fff;font-size:21px;font-weight:800;'
                 f'display:flex;align-items:center;justify-content:center;white-space:nowrap;animation:pr {CYC}s infinite">물건 받았어요</div>')
        body += (f'<div style="position:absolute;left:30px;top:94px;width:200px;display:flex;align-items:center;justify-content:center;gap:8px;animation:dn {CYC}s infinite;opacity:0">'
                 f'<i style="display:flex;width:30px;height:30px;border-radius:50%;background:{OK};color:#fff;font-style:normal;font-weight:900;align-items:center;justify-content:center">✓</i>'
                 f'<b style="font-size:21px;color:{INK}">인계 완료</b></div>')
        body += f'<div style="position:absolute;left:0;top:0;width:26px;height:26px;border-radius:50%;background:#F2C6A0;border:3px solid #D9A57A;animation:fi {CYC}s infinite"></div>'
    return wrap(W, H, css, body)


STEPS = [("kiosk", "—", "등록기계 보관", "kiosk"), ("staff", "등록기계 보관", "회수 중", "staff"), ("shelf", "회수 중", "본센터 보관", "staff"),
         ("ai", "본센터 보관", "승인·수령 예약", "tower"), ("robot", "승인·수령 예약", "반환 중", "tower"), ("box", "반환 중", "인계 대기", "tower"),
         ("done", "인계 대기", "인계 완료", "kiosk")]


def life_icons():
    """일곱 카드 가운데 빈칸의 아이콘 + 지금 단계 표시(1664x110). 카드 폭 225, 간격 14"""
    W, H, CYC = 1664, 110, 14
    w7, gap = 225, 14
    seg = 100 / 7
    css = ICSS + KIOSK
    css += ".ic{position:absolute;top:8px;width:96px;height:96px;margin-left:-48px;border-radius:24px;background:#F3EFE8;display:flex;align-items:center;justify-content:center}"
    body = ""
    for i, (k, *_r) in enumerate(STEPS):
        x = i * (w7 + gap) + w7 // 2
        s0, s1 = round(i * seg, 2), round((i + 1) * seg - 0.4, 2)
        on, off = f"background:{SOFT};box-shadow:0 0 0 5px {ACC}", "background:#F3EFE8;box-shadow:none"
        css += kf(f"g{i}", [(0, off), (max(0, s0 - 0.3), off), (s0 if s0 else 0.3, on), (s1, on), (min(100, s1 + 0.3), off), (100, off)])
        if k == "kiosk":
            inner = '<div class="kio" style="position:relative;transform:scale(.62)"></div>'
        elif k == "staff":
            inner = (f'<div style="position:relative;width:56px;height:70px"><i style="position:absolute;left:16px;top:0;width:24px;height:24px;border-radius:50%;background:{SUB}"></i>'
                     f'<i style="position:absolute;left:6px;top:28px;width:44px;height:40px;border-radius:20px 20px 8px 8px;background:{SUB}"></i>'
                     f'<i style="position:absolute;left:34px;top:38px;width:22px;height:18px;border-radius:4px;background:{ACCL};border:2px solid #fff"></i></div>')
        elif k == "shelf":
            inner = ('<div style="display:grid;grid-template-columns:repeat(4,15px);gap:4px">' + "".join(
                f'<i style="width:15px;height:22px;border-radius:4px;background:{ACC if j == 7 else "#D6C9B5"}"></i>' for j in range(8)) + "</div>")
        elif k == "ai":
            inner = f'<div style="width:62px;height:62px;border-radius:50%;background:{INK};color:{ACCL};font-size:16px;font-weight:800;display:flex;align-items:center;justify-content:center">AI ✓</div>'
        elif k == "robot":
            inner = (f'<div style="position:relative;width:64px;height:64px"><i style="position:absolute;left:4px;top:40px;width:24px;height:24px;border-radius:50%;background:#9AA6B8"></i>'
                     f'<i style="position:absolute;left:12px;top:6px;width:12px;height:46px;border-radius:6px;background:#7D8899;transform:rotate(35deg);transform-origin:50% 100%"></i>'
                     f'<i style="position:absolute;left:40px;top:6px;width:8px;height:18px;border-radius:3px;background:{INK}"></i></div>')
        elif k == "box":
            inner = f'<div style="width:66px;height:46px;border-radius:10px;background:#fff;border:4px dashed {ACC}"></div>'
        else:
            inner = f'<div style="width:58px;height:58px;border-radius:50%;background:#E7F5EC;border:5px solid #2E9E5B;color:#2E9E5B;font-size:30px;font-weight:900;display:flex;align-items:center;justify-content:center">✓</div>'
        body += f'<div class="ic" style="left:{x}px;animation:g{i} {CYC}s infinite">{inner}</div>'
    return wrap(W, H, css, body)


def life_log():
    """item_status_log 에 한 줄씩 쌓이는 표(800x250), life_icons 와 같은 주기"""
    W, H, CYC = 800, 250, 14
    seg = 100 / 7
    css = (f".hd,.rw{{position:absolute;left:0;width:{W}px;display:flex;align-items:center;font-size:21px}}.hd{{top:0;height:34px;background:#E0DACF;border-radius:10px;font-weight:800;color:{INK}}}"
           f".rw{{height:29px;color:{INK};opacity:0;border-bottom:1px solid #E6E0D6}}.c1{{width:40px;text-align:center;color:{SUB}}}.c2{{width:230px}}.c3{{width:30px;color:{ACC};font-weight:900}}.c4{{width:240px;font-weight:800}}"
           f".c5{{width:120px;font-family:Consolas,'JetBrains Mono',monospace;color:{SUB}}}")
    body = '<div class="hd"><span class="c1">#</span><span class="c2">from_status</span><span class="c3"></span><span class="c4">to_status</span><span class="c5">changed_by</span></div>'
    for i, (_k, fr, to, by) in enumerate(STEPS):
        s0 = round(i * seg + 2, 2)
        css += kf(f"l{i}", [(0, "opacity:0;transform:translateX(16px)"), (s0, "opacity:0;transform:translateX(16px)"), (s0 + 2, "opacity:1;transform:none;background:#FFF1E4"),
                            (s0 + 10, "opacity:1;background:transparent"), (96, "opacity:1"), (100, "opacity:0")])
        body += (f'<div class="rw" style="top:{38 + i * 30}px;animation:l{i} {CYC}s infinite"><span class="c1">{i + 1}</span><span class="c2">{fr}</span><span class="c3">→</span>'
                 f'<span class="c4">{to}</span><span class="c5">{by}</span></div>')
    return wrap(W, H, css, body)


if __name__ == "__main__":
    for i in range(5):
        print("ret", i, len(ret(i).encode()))
    print("icons", len(life_icons().encode()), "log", len(life_log().encode()))
