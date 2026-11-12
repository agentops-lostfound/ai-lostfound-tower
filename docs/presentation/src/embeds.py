"""슬라이드 안 움직이는 그림(x-embed) 4개 — 연결 지도 · 에이전트 대화 · 챗봇 흐름 · 한 바퀴 노선 (11/12)
x-embed 는 슬라이드 글꼴이 닿지 않아 시스템 글꼴을 쓴다. CSS @keyframes 만 사용(SMIL 안 씀)."""

FONT = "font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR','Noto Sans CJK KR',sans-serif"
INK, CARD, LINE, SUB, ACC, ACCL, SOFT = "#16202E", "#FFFDF9", "#D9D3C7", "#4A5568", "#F06A00", "#F6A15B", "#FFF1E4"

BASE = (f"html,body{{margin:0;padding:0;overflow:hidden;background:transparent;{FONT}}}*{{box-sizing:border-box;word-break:keep-all}}"
        f".n{{position:absolute;border-radius:24px;background:{CARD};border:2px solid {LINE};padding:16px 22px;box-shadow:0 8px 22px rgba(22,32,46,.08);display:flex;flex-direction:column;justify-content:center;gap:4px}}"
        f".n b{{font-size:30px;color:{INK};font-weight:800}}.n span{{font-size:24px;color:{SUB}}}"
        f".n.dark{{background:{INK};border:none}}.n.dark b{{color:#F7F5F1}}.n.dark span{{color:{ACCL}}}"
        f".n.soft{{background:{SOFT};border:3px solid {ACC}}}"
        f".dot{{position:absolute;left:0;top:0;width:20px;height:20px;border-radius:50%;background:{ACC};box-shadow:0 0 0 6px rgba(240,106,0,.25);offset-rotate:0deg;opacity:0}}"
        "@keyframes dash{to{stroke-dashoffset:-68}}")


def phase_kf(name, start, end, total=100):
    """start~end(%) 동안만 보이는 opacity 키프레임"""
    a, b = max(0, start - 1), min(100, end + 1)
    return (f"@keyframes {name}{{0%{{opacity:0}}{a}%{{opacity:0}}{start}%{{opacity:1}}{end}%{{opacity:1}}{b}%{{opacity:0}}100%{{opacity:0}}}}"
            if start > 0 else f"@keyframes {name}{{0%{{opacity:1}}{end}%{{opacity:1}}{b}%{{opacity:0}}100%{{opacity:0}}}}")


def glow_kf(name, start, end):
    on = "box-shadow:0 0 0 8px rgba(240,106,0,.35),0 8px 22px rgba(22,32,46,.08)"
    off = "box-shadow:0 8px 22px rgba(22,32,46,.08)"
    a, b = max(0, start - 1), min(100, end + 1)
    return f"@keyframes {name}{{0%{{{off}}}{a}%{{{off}}}{start}%{{{on}}}{end}%{{{on}}}{b}%{{{off}}}100%{{{off}}}}}"


def wrap(w, h, css, body):
    return f'<x-embed style="position:absolute;left:{{L}}px;top:{{T}}px;width:{w}px;height:{h}px"><style>{BASE}{css}</style>{body}</x-embed>'


# ───────── E1 연결 지도: 습득 → 찾기 → 반환 3단계가 15초마다 돈다 ─────────
def connect():
    W, H, CYC = 1664, 640, 15
    nodes = [("kiosk", 0, 30, 320, 120, "역 키오스크", "습득 등록", "", "g1"), ("chat", 0, 230, 320, 120, "챗봇 · 분실인 웹", "검색 · 분실 접수", "", "g2"),
             ("staff", 0, 430, 320, 120, "직원 화면", "예외 처리만", "", ""), ("tower", 560, 170, 420, 230, "관제탑", "쓰기는 모두 여기서", "dark", "pulse"),
             ("db", 1180, 0, 260, 120, "팀 DB", "PostgreSQL 16", "soft", ""), ("lf", 1180, 150, 260, 120, "Langfuse", "AI 판단 기록", "", "g2"),
             ("dc", 1180, 300, 260, 120, "디스코드", "운영 알림", "", "g3"), ("rb", 1180, 450, 260, 120, "로봇 PC", "SO-101 실행", "", "g3"),
             ("dbv", 1500, 0, 164, 120, "DBeaver", "읽기만", "", "")]
    paths = [("k", "M320 90 C440 90 440 250 560 250", "p1"), ("c", "M320 290 L560 290", "p2"), ("s", "M320 490 C440 490 440 330 560 330", None),
             ("tdb", "M980 230 C1080 230 1080 60 1180 60", "all"), ("tlf", "M980 270 C1080 270 1080 210 1180 210", "p2"),
             ("tdc", "M980 310 C1080 310 1080 360 1180 360", "p3"), ("trb", "M980 350 C1080 350 1080 510 1180 510", "p3"),
             ("dbv", "M1440 60 L1500 60", "all")]
    css = phase_kf("p1", 0, 31) + phase_kf("p2", 34, 64) + phase_kf("p3", 67, 97)
    css += glow_kf("g1", 0, 31) + glow_kf("g2", 34, 64) + glow_kf("g3", 67, 97)
    css += "@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(240,106,0,.0)}50%{box-shadow:0 0 0 14px rgba(240,106,0,.25)}}"
    css += "@keyframes mv{from{offset-distance:0%}to{offset-distance:100%}}"
    css += f".cap{{position:absolute;left:0;top:590px;width:{W}px;text-align:center;font-size:30px;font-weight:800;color:{INK}}}.cap i{{font-style:normal;color:#fff;background:{ACC};border-radius:999px;padding:4px 18px;margin-right:14px;font-size:26px}}"
    body = ""
    svg = f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0">'
    for pid, d, ph in paths:
        svg += f'<path d="{d}" fill="none" stroke="#C9C1B3" stroke-width="3"/>'
        if ph:
            anim = "dash 1.4s linear infinite" + (f",{ph} {CYC}s infinite" if ph != "all" else "")
            col = "#5B7BB5" if pid == "dbv" else ACC
            svg += f'<path d="{d}" fill="none" stroke="{col}" stroke-width="6" stroke-linecap="butt" stroke-dasharray="22 12" style="animation:{anim}"/>'
    svg += "</svg>"
    body += svg
    for nid, x, y, w, h, t, s, cls, an in nodes:
        a = f"animation:{an} {CYC if an != 'pulse' else 2.4}s infinite;" if an else ""
        fs = "font-size:44px;" if nid == "tower" else ("font-size:23px;" if nid == "dbv" else "")
        body += f'<div class="n {cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;{a}"><b style="{fs}">{t}</b><span>{s}</span></div>'
    for pid, d, ph in []:
        if not ph:
            continue
        for k in (0, 1):
            phase = "" if ph == "all" else f",{ph} {CYC}s infinite"
            vis = "opacity:1;" if ph == "all" else ""
            col = "background:#5B7BB5;box-shadow:0 0 0 6px rgba(91,123,181,.25);" if pid == "dbv" else ""
            body += f'<div class="dot" style="offset-path:path(\'{d}\');{vis}{col}animation:mv 1.6s linear infinite{phase};animation-delay:{-0.8 * k}s,0s"></div>'
    caps = [("p1", "① 습득", "역 키오스크 → 관제탑 → 팀 DB에 물건 1행"), ("p2", "② 찾기", "챗봇 → 관제탑 → DB 검색 · 판단 과정은 Langfuse에"),
            ("p3", "③ 반환", "관제탑 → 로봇 PC 실행 · 디스코드 알림 · DB 기록")]
    for i, (ph, tag, t) in enumerate(caps):
        body += f'<div class="cap" style="animation:{ph} {CYC}s infinite;{"" if i == 0 else "opacity:0"}"><i>{tag}</i>{t}</div>'
    return wrap(W, H, css, body)


# ───────── E2 에이전트 대화: 메인 AI 허브 + 대화 기록이 한 줄씩 ─────────
def agents():
    W, H, CYC = 1664, 640, 18
    C = (370, 320)
    nodes = {"kiosk": ("키오스크 AI", 370, 85), "db": ("DB", 640, 190), "slot": ("보관 칸", 640, 450), "robot": ("로봇팔", 370, 555),
             "match": ("매칭", 100, 450), "vision": ("비전", 100, 190)}
    seq = [("요청", "#D9DEE7", "kiosk", "main", "키오스크 AI → 메인 AI", "중앙역 접수, 핸드크림·초록"), ("요청", "#D9DEE7", "main", "db", "메인 AI → DB", "기록 알려 줘 — 역·품목·색·상태"),
           ("답", "#E6EFE3", "db", "main", "DB → 메인 AI", "A-… · 중앙역 · 핸드크림 · 초록"), ("확인", "#FBE3C9", None, None, "메인 AI", "정답지·역 표와 맞춰 봤어요 — 일치"),
           ("요청", "#D9DEE7", "main", "slot", "메인 AI → 보관 칸", "핸드크림 들어갈 빈 칸은?"), ("답", "#E6EFE3", "slot", "main", "보관 칸 → 메인 AI", "R3-1 (핸드크림 열, 먼 줄)"),
           ("결정", ACCL, "main", "robot", "메인 AI → 로봇팔", "회수해서 R3-1 칸에"), ("설명", "#ECE4F6", None, None, "sLLM Mi:dm", "(예) 앞칸이 비어 그 칸으로 정했어요")]
    n = len(seq)
    slot = 100 / (n + 1)
    css = "@keyframes mv{from{offset-distance:0%}to{offset-distance:100%}}"
    css += f".hub{{position:absolute;left:{C[0]-120}px;top:{C[1]-120}px;width:240px;height:240px;border-radius:50%;background:{INK};display:flex;flex-direction:column;align-items:center;justify-content:center;box-shadow:0 10px 30px rgba(22,32,46,.18)}}"
    css += f".hub b{{font-size:40px;color:#F7F5F1}}.hub span{{font-size:24px;color:{ACCL}}}"
    css += f".ag{{position:absolute;width:150px;height:150px;border-radius:50%;background:{CARD};border:3px solid {LINE};display:flex;align-items:center;justify-content:center;text-align:center;font-size:26px;font-weight:800;color:{INK};box-shadow:0 8px 22px rgba(22,32,46,.08)}}"
    css += f".row{{position:absolute;left:800px;width:856px;height:66px;border-radius:16px;background:{CARD};display:flex;align-items:center;gap:16px;padding:0 18px;box-shadow:0 4px 14px rgba(22,32,46,.06)}}"
    css += f".row i{{font-style:normal;font-size:24px;font-weight:800;color:{INK};border-radius:999px;width:84px;text-align:center;flex:none}}.row em{{font-style:normal;font-size:21px;color:{SUB};width:236px;flex:none}}.row b{{font-size:23px;white-space:nowrap;color:{INK};font-weight:600}}"
    body = f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0">'
    for k, (_, x, y) in nodes.items():
        body += f'<line x1="{C[0]}" y1="{C[1]}" x2="{x}" y2="{y}" stroke="#C9C1B3" stroke-width="3" stroke-dasharray="6 8"/>'
    body += "</svg>"
    for k, (t, x, y) in nodes.items():
        body += f'<div class="ag" id="a_{k}" style="left:{x-75}px;top:{y-75}px">{t}</div>'
    body += f'<div class="hub" style="animation:hp {CYC}s infinite"><b>메인 AI</b><span>sLLM Mi:dm</span></div>'
    hub_on = []
    for i, (kind, kc, frm, to, path, txt) in enumerate(seq):
        s0 = round(slot * (i + 0.5), 1)
        s1 = round(s0 + slot * 0.6, 1)
        # 기록 줄: 차례가 오면 나타나 끝까지 남음
        css += f"@keyframes r{i}{{0%{{opacity:0;transform:translateX(30px)}}{s0}%{{opacity:0;transform:translateX(30px)}}{round(s0 + 2, 1)}%{{opacity:1;transform:none}}96%{{opacity:1;transform:none}}100%{{opacity:0}}}}"
        dark = kind == "결정"
        bg = f"background:{INK};" if dark else ("border:2px dashed #C9C1B3;" if kind == "설명" else "")
        body += (f'<div class="row" style="top:{8 + i * 78}px;{bg}animation:r{i} {CYC}s infinite"><i style="background:{kc}">{kind}</i>'
                 f'<em style="{"color:#BFC8D6" if dark else ""}">{path}</em><b style="{"color:#F7F5F1" if dark else ""}">{txt}</b></div>')
        if frm:
            a = C if frm == "main" else nodes[frm][1:]
            b = C if to == "main" else nodes[to][1:]
            css += (f"@keyframes m{i}{{0%{{opacity:0;offset-distance:0%}}{max(0, s0 - 0.5)}%{{opacity:0;offset-distance:0%}}{s0}%{{opacity:1;offset-distance:0%}}"
                    f"{s1}%{{opacity:1;offset-distance:100%}}{round(s1 + 1, 1)}%{{opacity:0;offset-distance:100%}}100%{{opacity:0;offset-distance:100%}}}}")
            body += f'<div class="dot" style="offset-path:path(\'M{a[0]} {a[1]} L{b[0]} {b[1]}\');animation:m{i} {CYC}s infinite;width:26px;height:26px"></div>'
            ag = frm if frm != "main" else to
            css += glow_kf(f"gl{i}", s0, s1 + 1).replace("box-shadow:0 8px 22px", "box-shadow:0 8px 22px")
            css += f"#a_{ag}{{}}"
            body = body.replace(f'id="a_{ag}" style="', f'id="a_{ag}" style="animation:gl{i} {CYC}s infinite;', 1) if f'id="a_{ag}" style="animation' not in body else body
        else:
            hub_on.append((s0, s1 + 1))
    # 허브: 확인·설명 때 빛남
    kf = "0%{box-shadow:0 10px 30px rgba(22,32,46,.18)}"
    for s0, s1 in hub_on:
        kf += f"{max(0, s0 - 1)}%{{box-shadow:0 10px 30px rgba(22,32,46,.18)}}{s0}%{{box-shadow:0 0 0 18px rgba(240,106,0,.35)}}{s1}%{{box-shadow:0 0 0 18px rgba(240,106,0,.35)}}{s1 + 1}%{{box-shadow:0 10px 30px rgba(22,32,46,.18)}}"
    css += f"@keyframes hp{{{kf}100%{{box-shadow:0 10px 30px rgba(22,32,46,.18)}}}}"
    return wrap(W, H, css, body)


# ───────── E3 챗봇 흐름: 질문 하나가 칸을 따라 흐른다 ─────────
def chatflow():
    W, H, CYC = 930, 560, 12
    nodes = [("q", 0, 0, 420, 96, "질문", "“휴대폰 습득된 거 있어요?”", "dark"), ("co", 0, 136, 420, 100, "coordinator", "어떤 말인지 분류", ""),
             ("pl", 0, 276, 420, 100, "planner", "부를 일꾼 순서", ""), ("sv", 0, 416, 420, 144, "supervisor", "결과 보고 판단 · 되묻기 · 멈춤", "soft"),
             ("re", 500, 0, 430, 110, "researcher", "안내 답 + 근거 검사", ""), ("is", 500, 150, 430, 110, "item_search", "물건 후보 검색(읽기만)", ""),
             ("in", 500, 300, 430, 110, "intake", "대화 접수(확인 뒤에만)", ""), ("rp", 500, 450, 430, 110, "reporter", "결과 합치기 · 버튼", "")]
    pos = {n[0]: n[1:5] for n in nodes}
    order = [("q", "co"), ("co", "pl"), ("pl", "sv"), ("sv", "is"), ("is", "sv"), ("sv", "rp"), ("rp", "sv")]
    css = "@keyframes mv{from{offset-distance:0%}to{offset-distance:100%}}.n b{font-family:Consolas,'JetBrains Mono',monospace}"
    body = f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0">'
    for a, b in [("q", "co"), ("co", "pl"), ("pl", "sv")]:
        body += f'<line x1="210" y1="{pos[a][1] + pos[a][3]}" x2="210" y2="{pos[b][1]}" stroke="#C9C1B3" stroke-width="3"/>'
    for w in ("re", "is", "in", "rp"):
        body += f'<path d="M420 488 C460 488 460 {pos[w][1] + 55} 500 {pos[w][1] + 55}" fill="none" stroke="#C9C1B3" stroke-width="3" stroke-dasharray="6 8"/>'
    body += "</svg>"
    seg = 100 / (len(order) + 1)
    lit = {}
    for i, (a, b) in enumerate(order):
        s0, s1 = round(seg * (i + 0.4), 1), round(seg * (i + 1), 1)
        ax, ay, aw, ah = pos[a]
        bx, by, bw, bh = pos[b]
        if ax == bx:
            d = f"M210 {ay + ah} L210 {by}"
        elif a == "sv":
            d = f"M420 488 C460 488 460 {by + 55} 500 {by + 55}"
        else:
            d = f"M500 {ay + 55} C460 {ay + 55} 460 488 420 488"
        css += (f"@keyframes c{i}{{0%{{opacity:0;offset-distance:0%}}{max(0, s0 - 0.5)}%{{opacity:0;offset-distance:0%}}{s0}%{{opacity:1;offset-distance:0%}}"
                f"{s1}%{{opacity:1;offset-distance:100%}}{round(s1 + 1, 1)}%{{opacity:0;offset-distance:100%}}100%{{opacity:0;offset-distance:100%}}}}")
        body += f'<div class="dot" style="offset-path:path(\'{d}\');animation:c{i} {CYC}s infinite;width:24px;height:24px"></div>'
        lit.setdefault(b, []).append((s1, round(s1 + seg * 0.8, 1)))
    lit.setdefault("q", []).append((0, round(seg * 0.6, 1)))
    for k, spans in lit.items():
        off, on = "box-shadow:0 8px 22px rgba(22,32,46,.08)", "box-shadow:0 0 0 8px rgba(240,106,0,.35)"
        kf = f"0%{{{off}}}" if spans[0][0] > 0 else ""
        for s0, s1 in spans:
            kf += f"{max(0, s0 - 0.5)}%{{{off}}}{s0}%{{{on}}}{s1}%{{{on}}}{min(100, s1 + 0.5)}%{{{off}}}" if s0 > 0 else f"0%{{{on}}}{s1}%{{{on}}}{s1 + 0.5}%{{{off}}}"
        css += f"@keyframes l_{k}{{{kf}100%{{{off}}}}}"
    for nid, x, y, w, h, t, s, cls in nodes:
        a = f"animation:l_{nid} {CYC}s infinite;" if nid in lit else ""
        tf = "font-family:inherit;" if nid == "q" else ""
        body += f'<div class="n {cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;{a}"><b style="{tf}">{t}</b><span>{s}</span></div>'
    return wrap(W, H, css, body)


# ───────── E4 한 바퀴 노선: 물건이 정거장을 따라 이동 ─────────
def route():
    W, H, CYC = 1664, 470, 12.5
    xs = [166 + i * 333 for i in range(5)]
    st = [("접수", "역 키오스크", "넣으면 자동 촬영, AI가 특징 기록"), ("보관", "본센터", "품목별 칸에 보관, 칸 번호를 DB에"),
          ("찾기", "웹 · 챗봇", "설명하면 후보, 확인 질문 뒤 찾기 번호"), ("반환", "로봇팔", "본인 확인 · 메인 AI 승인 뒤 제출보관함으로"),
          ("인계", "직접 수령", "꺼내고 [물건 받았어요] → 인계 완료")]
    css = f".line{{position:absolute;left:{xs[0]}px;top:76px;width:{xs[-1] - xs[0]}px;height:16px;border-radius:8px;background:{ACC}}}"
    css += f".st{{position:absolute;top:58px;width:52px;height:52px;margin-left:-26px;border-radius:50%;background:{CARD};border:10px solid {ACC}}}"
    css += f".item{{position:absolute;top:0;left:0;width:44px;height:64px;margin-left:-22px;border-radius:12px;background:{INK};border:5px solid {ACCL};box-shadow:0 8px 18px rgba(22,32,46,.25)}}"
    css += f".c{{position:absolute;top:160px;width:317px;height:300px;border-radius:26px;background:{CARD};border:2px solid {LINE};padding:26px 24px;display:flex;flex-direction:column;gap:10px;box-shadow:0 8px 22px rgba(22,32,46,.08)}}"
    css += f".c i{{font-style:normal;font-size:26px;font-weight:800;color:#B5500A}}.c b{{font-size:38px;color:{INK}}}.c span{{font-size:26px;color:{SUB};line-height:1.45}}"
    kf = ""
    seg = 100 / 5
    for i, x in enumerate(xs):
        a, b = round(i * seg, 1), round(i * seg + seg * 0.62, 1)
        kf += f"{a}%{{transform:translate({x}px,22px)}}{b}%{{transform:translate({x}px,22px)}}"
    kf += f"100%{{transform:translate({xs[0]}px,22px)}}"
    css += f"@keyframes go{{{kf}}}"
    body = '<div class="line"></div>' + "".join(f'<div class="st" style="left:{x}px"></div>' for x in xs)
    body += f'<div class="item" style="animation:go {CYC}s ease-in-out infinite;transform:translate({xs[0]}px,22px)"></div>'
    for i, (lab, t, d) in enumerate(st):
        s0, s1 = round(i * seg, 1), round(i * seg + seg * 0.9, 1)
        css += glow_kf(f"h{i}", s0 if s0 else 0.1, s1)
        last = i == 4
        sty = f"background:{ACC};border-color:{ACC};" if last else ""
        body += (f'<div class="c" style="left:{xs[i] - 158}px;{sty}animation:h{i} {CYC}s infinite"><i style="{"color:" + INK if last else ""}">{lab}</i>'
                 f'<div style="flex:1"></div><b>{t}</b><span style="{"color:" + INK if last else ""}">{d}</span></div>')
    return wrap(W, H, css, body)


if __name__ == "__main__":
    for f in (connect, agents, chatflow, route):
        s = f()
        print(f.__name__, len(s.encode("utf-8")), "bytes")
