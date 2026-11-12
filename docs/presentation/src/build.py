"""발표 덱 디자인 개선판 슬라이드 파일 만들기 (11/12) — 내용은 기존 덱 그대로, 크기·배치·노선 진행 표시·등장 효과만 바꿈"""
import pathlib, sys

OUT = pathlib.Path(sys.argv[1])
INK, BG, BG2, CARD, LINE, SUB, ACC, ACCD, ACCL, SOFT = "#16202E", "#F7F5F1", "#EDE9E2", "#FFFDF9", "#D9D3C7", "#4A5568", "#F06A00", "#B5500A", "#F6A15B", "#FFF1E4"
VBG, VFR = "#0F1724", "#1B2638"
FONT = "font-family:'Noto Sans KR', Arial, sans-serif"
MONO = "font-family:'JetBrains Mono', monospace"
STATIONS = ["한눈에", "맡기기", "찾기", "돌려받기", "관제", "신뢰성", "근거"]
XS = [round(128 + i * 1664 / 6) for i in range(7)]
SHADOW = "box-shadow:0 8px 24px rgba(22,32,46,.07)"


def bi(b):
    return f' data-build-in="{b}"' if b else ""


def box(x, y, w, h, inner, style, b=None, extra=""):
    hh = f"height:{h}px;" if h else ""
    return f'<div{extra} style="position:absolute;left:{x}px;top:{y}px;width:{w}px;{hh}{style}"{bi(b)}>{inner}</div>\n'


def ptext(x, y, w, text, style, b=None):
    return f'<p style="position:absolute;left:{x}px;top:{y}px;width:{w}px;{style}"{bi(b)}>{text}</p>\n'


ST = {
    "light": (f"background:{CARD};border:2px solid {LINE};border-radius:28px;{SHADOW}", ACCD, INK, SUB),
    "dark": (f"background:{INK};border-radius:28px;{SHADOW}", ACCL, "#F7F5F1", "#D5DCE6"),
    "accent": (f"background:{ACC};border-radius:28px;{SHADOW}", INK, INK, INK),
    "soft": (f"background:{SOFT};border:3px solid {ACC};border-radius:28px;{SHADOW}", ACCD, INK, "#2B3545"),
}


def card(x, y, w, h, label, title, body, st="light", b=None, ts=40, bs=28, pad="30px 28px", body_style=""):
    bg, lc, tc, bc = ST[st]
    inner = ""
    if label:
        inner += f'<p style="font-size:26px;font-weight:800;color:{lc};letter-spacing:1px">{label}</p><div style="flex:1"></div>'
    if title:
        inner += f'<h3 style="font-size:{ts}px;font-weight:800;color:{tc};line-height:1.25">{title}</h3>'
    if body:
        inner += f'<p style="font-size:{bs}px;color:{bc};line-height:1.45;{body_style}">{body}</p>'
    return box(x, y, w, h, inner, f"{bg};padding:{pad};display:flex;flex-direction:column;gap:12px", b)


def rail(sec, theme="light"):
    if sec is None:
        return ""
    if theme == "dark":
        line, past, fut, lab, now_lab, dot_bg, dot_bd = "#2E3B50", ACC, "#2E3B50", "#9AA6B8", "#F7F5F1", ACCL, "#F7F5F1"
    elif theme == "accent":
        line, past, fut, lab, now_lab, dot_bg, dot_bd = "#C45700", INK, "#C45700", "#3A2410", INK, BG, INK
    else:
        line, past, fut, lab, now_lab, dot_bg, dot_bd = LINE, ACC, LINE, "#6B7280", INK, ACCL, INK
    s = box(128, 982, 1664, 6, "", f"background:{line};border-radius:3px")
    if sec:
        s += box(128, 982, XS[sec] - 128, 6, "", f"background:{past};border-radius:3px", extra=' id="railfill"')
    for i, x in enumerate(XS):
        c = past if i <= sec else fut
        s += box(x - 10, 975, 20, 20, "", f"background:{BG if theme == 'light' else (VBG if theme == 'dark' else ACC)};border:4px solid {c};border-radius:50%")
    s += box(XS[sec] - 18, 967, 36, 36, "", f"background:{dot_bg};border:6px solid {dot_bd};border-radius:50%", extra=' id="nowdot"')
    for i, x in enumerate(XS):
        w = "800" if i == sec else "500"
        s += ptext(x - 110, 1010, 220, STATIONS[i], f"font-size:24px;font-weight:{w};color:{now_lab if i == sec else lab};text-align:center")
    return s


ORDER = ["cover", "problem", "solution", "system", "flow", "v0", "part2", "found", "vision", "v1", "lost", "chatbot", "v2", "ret", "v3", "v7", "v8",
         "arch", "life", "v4", "agents", "talk", "brain", "v5", "except", "v6", "proof", "scope", "learn", "team", "end"]


def slide(sid, sec, eyebrow, title, body, theme="light", bg=None, note="", top=112):
    bgc = bg or {"light": BG, "dark": VBG, "accent": ACC}[theme]
    if theme == "light":
        bgc = f"radial-gradient(circle at 92% 4%, {'#F5DCC3' if bgc == BG2 else '#FCE4CC'} 0%, {bgc} 30%)"
    num = ORDER.index(sid) + 1 if sid in ORDER else 0
    numc = {"light": "#9AA3AF", "dark": "#6B7A90", "accent": INK}[theme]
    body = f'<p style="position:absolute;left:1592px;top:60px;width:200px;font-size:24px;font-weight:700;color:{numc};text-align:right;{MONO}">{num:02d} / {len(ORDER)}</p>\n' + body
    col = "#F7F5F1" if theme == "dark" else INK
    eb = {"light": ACCD, "dark": ACCL, "accent": INK}[theme]
    head = (f'<p style="font-size:28px;font-weight:800;color:{eb};letter-spacing:1px">{eyebrow}</p>\n'
            f'<h2 style="font-size:72px;font-weight:800;line-height:1.15;color:{col}">{title}</h2>\n') if title else ""
    html = (f'<section id="{sid}" data-transition="magic" style="background:{bgc};color:{col};{FONT};'
            f'padding:{top}px 128px 160px;display:flex;flex-direction:column;gap:12px">\n{head}{body}{rail(sec, theme)}')
    if note:
        html += f"<aside>{note}</aside>\n"
    html += "</section>\n"
    (OUT / f"{sid}.html").write_text(html, encoding="utf-8")


def row_cards(items, y, h, gap=20, x0=128, total=1664, start=1, ts=40, bs=28, b="rise"):
    n = len(items)
    w = (total - gap * (n - 1)) // n
    s = ""
    for i, it in enumerate(items):
        label, title, body, st = it
        s += card(x0 + i * (w + gap), y, w, h, label, title, body, st, b=f"{b} {start + i} auto", ts=ts, bs=bs)
    return s


def pills(y, items, b, size=32, x=128, w=1664, center=False):
    inner = "".join(f'<p style="font-size:{size}px;font-weight:700;{st};border-radius:16px;padding:18px 30px">{t}</p>' for t, st in items)
    jc = "justify-content:center;" if center else ""
    return box(x, y, w, None, inner, f"display:flex;gap:24px;{jc}", b)


P_SOFT = f"background:{SOFT};color:{INK}"
P_DARK = f"background:{INK};color:{ACCL}"


MEDIA = {"v0": ("ea53657cd372172fa47e68b3cff73278", "74d28029848f5a381f53c30502a39888"), "v1": ("1e358750e55db8ce2dca96b2f994bff1", "7b2749479a750bd3960403f21979a629"),
         "v2": ("00c3b8b1fc994dfafe796f153c8bbd89", "0af865e23a582267898eb4d38e4d8f5b"), "v3": ("e662b9ec1beaee8c002f1c1a839bdafe", "b225f4967d515cd2bb99a6b37f781d3c"),
         "v5": ("02dc200414d40fc44da136392535624b", "f1c463adcf9e6b884a9cd7977cddab14"), "v6": ("eb0df1d631de0201bdbd5b22723c4441", "794becba28f2481ba9da12e0fe0c4774"),
         "v7": ("ed6489131dee36b948ce2252aa9835c2", "849a965415353e70589950872092e06d"), "v8": ("5354df29ec391ecbf12d6392fcd7acaa", "b345b20fc3dd7fcc9ba50ada61bddb02")}


def vslide(sid, sec, eyebrow, title, alt, tag, points, fname, note):
    if sid in MEDIA:
        clip, still = MEDIA[sid]
        frame = (f'<img src="/_blob/{still}" data-video="/_blob/{clip}" alt="{alt}" style="position:absolute;left:128px;top:270px;width:1184px;height:666px;'
                 f'object-fit:contain;background:{VFR};border-radius:18px" data-build-in="fade 1 auto">\n')
        lis = "".join(f"<li>{p}</li>" for p in points)
        side = box(1360, 270, 432, None,
                   f'<p style="font-size:26px;font-weight:800;color:{INK};background:{ACCL};border-radius:999px;padding:8px 22px">{tag}</p>'
                   f'<h3 style="font-size:36px;font-weight:800;color:#F7F5F1">보는 포인트</h3>'
                   f'<ul style="font-size:28px;line-height:1.5;color:#D5DCE6">{lis}</ul>',
                   "display:flex;flex-direction:column;gap:20px", "rise 2 auto")
        slide(sid, sec, eyebrow, title, frame + side, theme="dark", note=note, top=96)
        return
    frame = (f'<img alt="{alt}" style="position:absolute;left:128px;top:270px;width:1184px;height:666px;'
             f'background:{VFR};border:3px dashed #4A5A70;border-radius:18px" data-build-in="fade 1 auto">\n')
    play = box(656, 539, 128, 128, f'<x-icon name="Play" style="color:{INK};width:56px;height:56px"></x-icon>',
               f"background:{ACC};border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 0 0 18px rgba(240,106,0,.18)", "pop 2 auto")
    lis = "".join(f"<li>{p}</li>" for p in points)
    side = box(1360, 270, 432, None,
               f'<p style="font-size:24px;color:#9AA6B8">← 영상 자리 · 파일 받으면 넣음</p>'
               f'<p style="font-size:26px;font-weight:800;color:{INK};background:{ACCL};border-radius:999px;padding:8px 22px">{tag}</p>'
               f'<h3 style="font-size:36px;font-weight:800;color:#F7F5F1">자막 포인트</h3>'
               f'<ul style="font-size:28px;line-height:1.5;color:#D5DCE6">{lis}</ul>'
               f'<p style="font-size:24px;color:#9AA6B8;{MONO}">{fname}</p>',
               "display:flex;flex-direction:column;gap:20px", "rise 3 auto")
    slide(sid, sec, eyebrow, title, frame + play + side, theme="dark", note=note, top=96)


# ───────── 표지 ─────────
cover = (box(0, 0, 24, 1080, "", f"background:{ACC}")
         + ptext(128, 128, 1664, "AgentOps 2조 · Agentic AI 프로젝트", f"font-size:32px;font-weight:800;color:{ACCL};letter-spacing:2px", "fade 1 auto")
         + f'<h1 style="position:absolute;left:128px;top:330px;width:1664px;font-size:150px;font-weight:800;line-height:1.05;color:#F7F5F1" data-build-in="rise 2 auto">AI 분실물 관제탑</h1>\n'
         + ptext(128, 530, 1664, "맡기면 AI가 기록하고, 확인되면 로봇이 돌려줍니다", "font-size:48px;color:#BFC8D6", "fade 3 auto")
         + box(128, 724, 1664, 12, "", f"background:{ACC};border-radius:6px", "fade 4 auto")
         + box(272, 706, 48, 48, "", f"background:{VBG};border:8px solid {ACC};border-radius:50%", "pop 5 auto")
         + box(932, 698, 64, 64, "", f"background:{ACCL};border:10px solid #F7F5F1;border-radius:50%", "pop 5 auto")
         + box(1592, 706, 48, 48, "", f"background:{VBG};border:8px solid {ACC};border-radius:50%", "pop 5 auto")
         + ptext(196, 780, 200, "중앙역", "font-size:30px;font-weight:700;color:#BFC8D6;text-align:center", "fade 6 auto")
         + ptext(814, 788, 300, "부산역 본센터", "font-size:32px;font-weight:800;color:#F7F5F1;text-align:center", "fade 6 auto")
         + ptext(1516, 780, 200, "초량역", "font-size:30px;font-weight:700;color:#BFC8D6;text-align:center", "fade 6 auto")
         + box(128, 880, 1664, None,
               f'<p style="font-size:26px;color:{INK};background:{ACCL};padding:10px 26px;border-radius:999px;font-weight:800">역 키오스크 · 본센터 · 로봇팔</p>'
               f'<p style="font-size:26px;color:#F7F5F1;border:2px solid #4A5A70;padding:8px 26px;border-radius:999px">sLLM · VLM · 에이전트</p>'
               f'<p style="font-size:26px;color:#F7F5F1;border:2px solid #4A5A70;padding:8px 26px;border-radius:999px">2026. 11</p>',
               "display:flex;gap:20px", "fade 7 auto"))
(OUT / "cover.html").write_text(
    f'<section id="cover" data-transition="magic" style="background:{INK};color:#F7F5F1;{FONT};padding:128px;display:flex;flex-direction:column">\n'
    + cover + "<aside>전반부는 한눈에 간략하게, 후반부는 하나씩 자세히 설명합니다. 설명 장 뒤에는 바로 그 장면 영상이 나옵니다.</aside>\n</section>\n", encoding="utf-8")

# ───────── 전반 · 한눈에 ─────────
pb = ""
for i, (who, worry, fix) in enumerate([("주운 사람", "어디에 맡기지?", "→ 역 키오스크에 넣기만"),
                                        ("잃어버린 사람", "어느 역이었지?", "→ 웹·챗봇에서 모든 역을 한 번에"),
                                        ("보관하는 쪽", "진짜 주인일까?", "→ 확인 질문 + 키오스크 본인 확인")]):
    pb += box(128 + i * 565, 300, 533, 560,
              f'<p style="font-size:32px;font-weight:700;color:{SUB}">{who}</p>'
              f'<h3 style="font-size:56px;font-weight:800;line-height:1.2">{worry}</h3><div style="flex:1"></div>'
              f'<p style="font-size:32px;font-weight:700;color:{INK};background:{SOFT};border-radius:16px;padding:20px 24px">{fix}</p>',
              f"{ST['light'][0]};padding:48px 44px;display:flex;flex-direction:column;gap:24px", f"rise {i + 1} auto")
slide("problem", 0, "문제", "분실물, 세 사람 모두에게 번거로운 일", pb,
      note="각자의 고민을 한 단계씩 맡도록 나눴습니다. 주운 사람은 넣기만, 잃어버린 사람은 역을 몰라도 검색, 보관하는 쪽은 확인 질문과 키오스크로 주인을 확인합니다.")

sx = [300, 740, 1180, 1620]
so = box(228, 300, 1464, 150,
         '<p style="font-size:44px;font-weight:800;color:#F7F5F1">AI 관제탑</p><p style="font-size:28px;color:#BFC8D6">모든 단계를 보고 · 기록하고 · 애매하면 멈춘다</p>',
         f"background:{INK};border-radius:28px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;{SHADOW}", "rise 1 auto")
for x in sx:
    so += f'<x-connector x1="{x}" y1="450" x2="{x}" y2="586" head="none" style="color:#8A93A3;border-width:3px;border-style:dashed"></x-connector>\n'
so += box(300, 604, 1320, 20, "", f"background:{ACC};border-radius:10px", "fade 2 auto")
for i, x in enumerate(sx):
    last = i == 3
    sz = 80 if last else 68
    so += box(x - sz // 2, 614 - sz // 2, sz, sz, "", f"background:{ACCL if last else CARD};border:{12 if last else 12}px solid {INK if last else ACC};border-radius:50%", f"pop {3 + i} auto")
for i, (t, d) in enumerate([("① 맡기기", "역 키오스크 · 자동 촬영"), ("② 보관", "본센터 · 품목별 칸"), ("③ 찾기", "웹 · 챗봇 · 확인 질문"), ("④ 돌려받기", "본센터 키오스크 · 로봇팔")]):
    so += box(sx[i] - 190, 676, 380, None, f'<h3 style="font-size:44px;font-weight:800;text-align:center">{t}</h3><p style="font-size:28px;color:{SUB};text-align:center">{d}</p>',
              "display:flex;flex-direction:column;align-items:center;gap:6px", f"rise {3 + i} auto")
so += pills(824, [("정상 흐름은 사람 없이", P_SOFT), ("애매하면 멈추고 사람에게", P_DARK)], "rise 7 auto", center=True)
slide("solution", 0, "해결", "네 단계를 잇는 AI 관제탑 하나", so,
      note="노선도의 역 하나가 단계 하나입니다. 관제탑은 모든 단계를 지켜보며 기록하고, 확인되지 않은 단계가 있으면 로봇을 멈추고 직원에게 넘깁니다.")


def ulcard(x, y, w, h, label, title, items, st, b, fs=28):
    bg, lc, tc, bc = ST[st]
    lis = "".join(f"<li>{t}</li>" for t in items)
    return box(x, y, w, h, f'<p style="font-size:26px;font-weight:800;color:{lc}">{label}</p><h3 style="font-size:38px;font-weight:800;color:{tc}">{title}</h3>'
               f'<ul style="font-size:{fs}px;line-height:1.45;color:{bc}">{lis}</ul>', f"{bg};padding:32px 30px;display:flex;flex-direction:column;gap:14px", b)


sy = ""
ws = [370, 482, 370, 370]
xs = [128]
for w in ws[:-1]:
    xs.append(xs[-1] + w + 24)
sy += ulcard(xs[0], 300, ws[0], 520, "역 (중앙역 · 초량역)", "습득물 등록기계", ["키오스크 화면", "포토박스 + 웹캠: 두면 자동 촬영", "운영 품목 4종: 목업폰 · 보조배터리 · 핸드크림 · 립밤"], "light", "rise 1 auto")
sy += ulcard(xs[1], 300, ws[1], 520, "부산역 본센터", "보관과 반환", ["공용 보관함 4열 × 2줄 = 8칸", "탑뷰 카메라", "SO-101 로봇팔 (로봇 PC, 원격 연결)", "제출보관함", "본센터 키오스크: 본인 확인 · [물건 받았어요]"], "soft", "rise 2 auto")
sy += ulcard(xs[2], 300, ws[2], 520, "관제탑 PC", "AI 관제탑", ["관제탑 서버 (포트 8100)", "팀 DB: PostgreSQL 16", "sLLM Mi:dm 2.0 mini", "VLM Qwen3-VL"], "dark", "rise 3 auto")
sy += ulcard(xs[3], 300, ws[3], 520, "분실인 · 운영", "밖에서 보는 곳", ["휴대폰 웹 + AI 안내 챗봇", "디스코드 운영 알림", "Langfuse 판단 기록"], "light", "rise 4 auto")
sy += pills(850, [("R1 휴대폰", P_SOFT), ("R2 보조배터리", P_SOFT), ("R3 핸드크림", P_SOFT), ("R4 립밤", P_SOFT)], "rise 5 auto", size=28)
slide("system", 0, "전체 구성", "역 · 본센터 · 관제탑 PC가 하나로 움직인다", sy,
      note="모든 장치는 관제탑 PC를 거쳐 연결됩니다. 로봇팔은 로봇 PC에서 미리 가르친 자세(티칭)로 움직이고, 관제탑은 DB의 칸 번호를 그 자세 번호로 바꿔 보냅니다. 아래 줄은 보관함 열 배치입니다.")

fl = row_cards([("접수", "역 키오스크", "넣으면 자동 촬영, AI가 특징 기록", "light"),
                ("보관", "본센터", "품목별 칸에 보관, 칸 번호를 DB에", "light"),
                ("찾기", "웹 · 챗봇", "설명하면 후보, 확인 질문 뒤 찾기 번호", "light"),
                ("반환", "로봇팔", "본인 확인 · 메인 AI 승인 뒤 제출보관함으로", "dark"),
                ("인계", "직접 수령", "꺼내고 [물건 받았어요] → 인계 완료", "accent")], 300, 400)
fl += pills(760, [("모든 단계를 AI 관제탑이 잇고 기록", P_SOFT), ("정상은 직원 없이, 확인되지 않으면 직원에게", P_DARK)], "rise 6 auto")
slide("flow", 0, "한 바퀴 요약", "물건 하나가 주인에게 돌아가기까지", fl,
      note="전반부는 여기까지 간략하게 보고, 바로 전체 흐름 영상을 보여 줍니다. 각 단계는 후반부에서 하나씩 자세히 설명합니다.")

vslide("v0", 0, "전체 흐름 영상 · 한눈에", "빨간 립밤 한 바퀴", "빨간 립밤 습득 → 분실 신고(C-…0021) → 같은 번호로 회수 → 로봇 전달", "화면 녹화 + 실물",
       ["습득 → 분실 신고 → 회수", "찾기 번호 C-…0021로 이어짐", "로봇: 실물과 관제탑 가상 팔을 나란히", "본인 정보 입력칸은 모자이크"], "v0_overview.mp4",
       "빨간 립밤 한 건을 습득부터 본센터 회수까지 이었습니다. 분실 신고와 회수는 같은 찾기 번호(C-…0021)입니다. 마지막 로봇 동작은 같은 칸(R4-1)을 미리 찍어 둔 영상이라 화면에 '사전 녹화'로 표시했고, 왼쪽 실물과 오른쪽 관제탑 가상 팔을 나란히 놓고, 가상 영상을 구간마다 빠르거나 느리게 맞춰 칸 위로 · 내려감 · 집기 · 들어 올림 · 놓기가 같은 순간에 나오게 했습니다. 립밤을 놓는 순간에서 끊었습니다. 분실인이 꺼내고 [물건 받았어요]를 누르는 장면은 아직 없습니다.")

# ───────── 후반 구분 ─────────
p2 = (box(0, 0, 24, 1080, "", f"background:{ACC}")
      + ptext(128, 300, 1664, "후반", f"font-size:36px;font-weight:800;color:{ACCL};letter-spacing:2px", "fade 1 auto")
      + f'<h2 style="position:absolute;left:128px;top:360px;width:1664px;font-size:140px;font-weight:800;line-height:1.1;color:#F7F5F1" data-build-in="rise 2 auto">하나씩 자세히</h2>\n'
      + box(128, 580, 1664, None, "".join(
          f'<p style="font-size:32px;font-weight:800;color:{INK if i == 0 else "#F7F5F1"};{"background:" + ACCL if i == 0 else "border:2px solid #4A5A70"};border-radius:999px;padding:12px 30px">{t}</p>'
          for i, t in enumerate(["① 맡기기", "③ 찾기", "④ 돌려받기", "관제: DB · 에이전트", "신뢰성"])), "display:flex;gap:20px;flex-wrap:wrap", "rise 3 auto")
      + ptext(128, 720, 1664, "설명 한 장 → 바로 그 장면 영상", "font-size:32px;color:#BFC8D6", "fade 4 auto"))
(OUT / "part2.html").write_text(
    f'<section id="part2" data-transition="magic" style="background:{INK};color:#F7F5F1;{FONT};padding:128px;display:flex;flex-direction:column">\n'
    + p2 + "<aside>후반부는 각 부분을 설명한 뒤 바로 해당 장면 영상(영상 1~6)을 보여 줍니다.</aside>\n</section>\n", encoding="utf-8")

# ───────── ① 맡기기 ─────────
fd = row_cards([("01", "넣기", "포토박스 안에 물건 두기", "light"),
                ("02", "자동 촬영", "손을 빼고 5초 멈추면 찰칵, 버튼 없음", "light"),
                ("03", "장소 고르기", "그 역의 장소 목록, 없으면 직접 입력", "light"),
                ("04", "연락처 (선택)", "안 남겨도 접수, 감사 연락에만 쓰고 30일 뒤 삭제", "light"),
                ("05", "접수 완료", "다음 과정을 안내, 본센터로 회수", "light")], 300, 420)
fd += box(128, 780, 1664, None, f'<p style="font-size:30px;font-weight:800;color:#2B3545;padding:16px 0">본센터 보관 칸</p>' + "".join(
    f'<p style="font-size:30px;font-weight:800;background:{SOFT};border:3px solid {ACC};border-radius:14px;padding:14px 26px">{t}</p>'
    for t in ["R1 휴대폰", "R2 보조배터리", "R3 핸드크림", "R4 립밤"]), "display:flex;gap:18px;align-items:center", "rise 6 auto")
slide("found", 1, "① 맡기기 · 역 키오스크", "상자에 넣고 장소만 고르면 끝", fd,
      note="주운 사람이 할 일은 넣고 장소를 고르는 것뿐입니다. 촬영 버튼은 없고, 물건이 들어오고 손이 빠진 뒤 5초 동안 움직임이 없으면 자동으로 찍습니다.")

vw = [330, 440, 440, 330]
vx = [128]
for w in vw[:-1]:
    vx.append(vx[-1] + w + 42)
vs = card(vx[0], 300, vw[0], 420, "사진", "키오스크 웹캠", "회색 펠트 바닥 위에서 한 장", "light", "rise 1 auto")
vs += card(vx[1], 300, vw[1], 420, "VLM Qwen3-VL", "읽기", "품목 · 색 · 모양 → 공개 특징<br>글자 · 스티커 → 비공개 특징(확인 질문용)", "dark", "rise 3 auto")
vs += card(vx[2], 300, vw[2], 420, "숫자로 다시 재기", "확인", "색 측정: 펠트 기준 색값<br>크기 측정: 길이·폭으로 크림 ↔ 립밤<br>확실할 때만 수정", "light", "rise 5 auto")
vs += card(vx[3], 300, vw[3], 420, "저장", "팀 DB", "features<br>private_features", "soft", "rise 7 auto", body_style=MONO + ";font-size:23px")
for i in range(3):
    ax = vx[i] + vw[i] + 3
    vs += f'<x-shape kind="arrow-right" style="position:absolute;left:{ax}px;top:494px;width:36px;height:30px;background:{ACC}" data-build-in="fade {2 + 2 * i} auto"></x-shape>\n'
vs += ptext(128, 780, 1664, f'통합 화면의 사진 분석 카드: <span style="color:{ACCD}">읽은 값 → 저장한 값</span>을 나란히 표시', "font-size:32px;font-weight:700;color:#2B3545", "rise 8 auto")
slide("vision", 1, "① 맡기기 · AI 사진 분석", "사진 한 장 → 특징 → DB", vs,
      note="VLM은 사진과 글을 함께 읽는 언어 모델입니다. Qwen이 읽은 색과 품목을 사진의 실제 색값과 크기로 한 번 더 재서, 확실하게 다를 때만 고칩니다. 확인 질문의 정답이 되는 비공개 특징은 공개 특징과 다른 칸에 저장합니다.")

vslide("v1", 1, "영상 1 · ① 맡기기", "습득 등록 한 번", "영상 자리: 습득 등록(키오스크 촬영 → Qwen 분석 → DB 기록)", "실물 + 화면 녹화",
       ["두고 손을 빼면 카운트다운 뒤 자동 촬영", "역 장소 고르기, 연락처는 선택", "접수 완료 → 다음 과정 안내", "끝 화면: 다른 접수의 Qwen 결과 예시"], "v1_found.mp4",
       "통합 화면의 DB·에이전트 함께 보기로 녹화하면 촬영, Qwen 분석 카드, DB 기록이 한 화면에 잡힙니다.")

# ───────── ③ 찾기 ─────────
ls = ""
for i, (t, st) in enumerate([("물건 설명: 종류 · 색 · 역", "light"), ("가린 본인 정보", "light"), ("확인 질문(비공개 특징)", "light"), ("찾기 번호 C-… 받기", "light")]):
    bg, lc, tc, bc = ST[st]
    ls += box(128, 300 + i * 120, 820, 104, f'<p style="font-size:34px;font-weight:800;color:{lc if st != "accent" else INK};width:40px">{i + 1}</p><p style="font-size:34px;font-weight:800;color:{tc}">{t}</p>',
              f"{bg};padding:0 32px;display:flex;align-items:center;gap:20px", f"rise {i + 1} auto")
ls += ptext(128, 790, 820, "AI 안내 챗봇에 말로 해도 같은 접수", f"font-size:30px;color:{SUB}", "fade 5 auto")
for i, (q, a) in enumerate([("역을 모르면", "장소는 빼고 색으로 확인"), ("방문 전이면", "찾기 요청 취소, 물건은 계속 보관"), ("같은 물건에 진행 중인 요청이 있으면", "새 요청을 막아 중복 반환 방지")]):
    ls += box(1010, 300 + i * 176, 782, 150, f'<p style="font-size:28px;color:{SUB};font-weight:700">{q}</p><p style="font-size:36px;font-weight:800;line-height:1.3">{a}</p>',
              f"border-left:8px solid {ACC};padding:12px 0 12px 30px;display:flex;flex-direction:column;gap:8px", f"rise {6 + i} auto")
slide("lost", 2, "③ 찾기 · 웹과 챗봇", "센터에 가기 전에, 내 물건인지 먼저", ls,
      note="본인 정보는 가린 값만 저장합니다. 확인 질문은 사진에서 읽은 비공개 특징으로 만들고, 통과 여부만 남깁니다. 확인에 실패하고 방문하지 않은 요청은 정리한 뒤 다시 신청할 수 있습니다(11/12 개선).")

cb = card(128, 300, 420, 128, "", "", "", "light")  # placeholder 제거용
cb = ""
for i, (name, desc, y, h, st) in enumerate([("coordinator", "어떤 말인지 분류", 300, 124, "light"), ("planner", "부를 일꾼 순서", 464, 124, "light"),
                                             ("supervisor", "결과를 보고 판단: 되묻기 · 확인 · 다시 계획 · 멈춤", 628, 220, "soft")]):
    bg, lc, tc, bc = ST[st]
    cb += box(128, y, 420, h, f'<p style="font-size:30px;{MONO};font-weight:600;color:{tc}">{name}</p><p style="font-size:28px;color:{bc};line-height:1.4">{desc}</p>',
              f"{bg};padding:22px 28px;display:flex;flex-direction:column;gap:6px", f"rise {i + 1} auto")
cb += f'<x-connector x1="338" y1="424" x2="338" y2="464" head="end" style="color:#8A93A3;border-width:3px"></x-connector>\n'
cb += f'<x-connector x1="338" y1="588" x2="338" y2="628" head="end" style="color:#8A93A3;border-width:3px"></x-connector>\n'
cb += f'<x-connector x1="548" y1="738" x2="620" y2="738" head="both" style="color:{ACC};border-width:4px"></x-connector>\n'
chips = "".join(f'<div style="background:{CARD};border-radius:14px;padding:10px 20px"><p style="font-size:28px;{MONO};font-weight:600">{n}</p><p style="font-size:26px;color:{SUB}">{d}</p></div>'
                for n, d in [("researcher", "안내 답 + 근거 검사"), ("item_search", "물건 후보 검색(읽기만)"), ("intake", "대화 접수(확인 뒤에만)"), ("reporter", "결과 합치기 · 버튼")])
cb += box(620, 300, 440, 548, chips, f"background:#E0DACF;border-radius:22px;padding:22px;display:flex;flex-direction:column;gap:14px", "rise 4 auto")
cb += box(1120, 300, 672, None,
          f'<h3 style="font-size:36px;font-weight:800">500문항 채점표 (사용자 말투)</h3>'
          f'<table style="width:672px;font-size:28px;color:{INK};{FONT}"><tr style="background:#E0DACF"><th style="width:26%;padding:10px 16px">단계</th><th style="width:52%">모델</th><th style="width:22%">점수</th></tr>'
          f'<tr><td>11/9 01</td><td>규칙만</td><td>355</td></tr><tr><td>11/9 03</td><td>Mi:dm 2.0 Mini</td><td>403</td></tr>'
          f'<tr style="background:{SOFT}"><td>11/9 06</td><td>Mi:dm + 프롬프트 13개</td><td>459</td></tr><tr><td>11/9 07~</td><td>규칙만(보강)</td><td>500*</td></tr></table>'
          f'<p style="font-size:26px;color:{SUB};line-height:1.5">* 채점표에 맞춘 면이 있어 Mi:dm 점수와 함께 봄<br>에이전트 1개 = Langfuse 프롬프트 1개 — 배포 없이 고침</p>',
          "display:flex;flex-direction:column;gap:18px", "rise 5 auto")
slide("chatbot", 2, "③ 찾기 · 챗봇 (DeerFlow 구조)", "질문 하나가 감독을 거쳐 일꾼에게", cb, bg=BG2,
      note="말을 이해하고 판단하는 칸은 모델과 프롬프트, 검색·접수·숫자처럼 기록을 남기는 일은 코드로 나눈 혼합 구조입니다. 모델은 규칙이 허용한 목록 안에서만 고를 수 있습니다. 직원용 관제 분석(ops_analyst) 일꾼은 관리자 화면에서만 쓰여 그림에서 뺐습니다.")

vslide("v2", 2, "영상 2 · ③ 찾기", "휴대폰 웹으로 찾고 신청하기", "휴대폰 웹 분실 신고: 물건 설명 → 본인 확인 → 찾기 번호", "화면 녹화",
       ["종류 · 색 · 역으로 물건 설명", "역을 모르면 '잘 모르겠어요'", "이름 · 신분 번호 입력칸은 모자이크", "확인 뒤 찾기 번호 C-… 발급"], "v2_lost.mp4",
       "예시 질문: 휴대폰 습득된 거 있어요? → 색을 되묻는지 → 찾기 신청할게요. 정정(초량 말고 중앙)도 넣으면 좋습니다.")

# ───────── ④ 돌려받기 ─────────
rt = row_cards([("01", "본인 확인", "본센터 키오스크에 찾기 번호 + 신분 번호 뒤 첫 자리", "light"),
                ("02", "메인 AI 승인", "기록과 대조, 칸 위치 확인", "light"),
                ("03", "로봇팔", "DB 칸 번호 → 미리 가르친 자세로 집기", "dark"),
                ("04", "제출보관함", "물건 도착, 로봇은 원점으로", "light"),
                ("05", "물건 받았어요", "분실인이 꺼내고 누름 → 인계 완료", "light")], 300, 420, ts=38)
rt += box(128, 780, 1664, None,
          f'<p style="flex:2;font-size:36px;font-weight:800;background:{INK};color:#F7F5F1;border-radius:18px;padding:26px 34px">정상 흐름은 직원 없이. 직원은 예외만</p>'
          f'<p style="flex:1;font-size:30px;color:#2B3545;background:{CARD};border:2px solid {LINE};border-radius:18px;padding:28px 30px">실물 로봇 한 바퀴 약 44초(11단계)</p>',
          "display:flex;gap:24px;align-items:stretch", "rise 6 auto")
slide("ret", 3, "④ 돌려받기 · 부산역 본센터", "키오스크가 확인하고, 로봇이 꺼내는 반환", rt,
      note="직원이 나서는 경우는 확인 질문 미통과(대면 확인), 직원 보관 선반의 물건, 정지, 원점 복귀 같은 예외뿐입니다. 로봇은 원점에서 칸 위로 가 집고, 제출보관함에 놓은 뒤 원점으로 돌아오기까지 11단계(단계당 약 3.9초)로 움직입니다.")

vslide("v3", 3, "영상 3 · ④ 돌려받기", "본센터 회수와 로봇 반환", "본센터 키오스크 본인 확인(C-…0021) → 로봇이 R4-1 칸 립밤을 제출보관함으로", "화면 녹화 + 실물",
       ["찾기 번호 + 숫자 하나로 본인 확인", "회수 요청 → 로봇 실행 안내", "실물 로봇과 관제탑 가상 팔이 같은 칸을", "R4-1 → 제출보관함 (사전 녹화)"], "v3_return.mp4",
       "앞은 본센터 키오스크 화면, 뒤는 같은 칸(R4-1 빨간 립밤)의 실물 로봇 동작입니다. 로봇 영상은 미리 찍어 둔 것으로, 이 회수 요청과 동시에 찍은 것은 아닙니다. 정지 수단을 확인한 사람이 옆에 있을 때만 실물을 움직였습니다.")

vslide("v7", 3, "영상 · ④ 돌려받기", "8칸 모두, 미리 가르친 자세로", "실물 로봇 8칸(R1-1~R4-2) 동시 재생", "실물 · 사전 녹화 · 2배",
       ["R1 휴대폰 · R2 보조배터리", "R3 핸드크림 · R4 립밤", "DB 칸 번호 = 티칭 자세 번호", "칸마다 같은 11단계 · 사전 녹화"], "v7_cells.mp4",
       "실물 로봇이 8칸을 각각 꺼내는 장면을 한 화면에 모았습니다(2배속). 관제탑은 DB에 적힌 칸 번호를 미리 가르친 자세 번호로 바꿔 로봇 PC에 보냅니다.")
vslide("v8", 3, "영상 · ④ 돌려받기", "같은 칸, 가상과 실물", "같은 칸(R1-1 검정폰)의 가상 시연과 실물 로봇 나란히", "가상 + 실물 · 1.5배",
       ["가상 시연이 실물과 같은 순서로", "단계 시간은 실물 실측(약 3.9초)", "가상으로 먼저 확인 → 실물로", "R1-1 검정 휴대폰"], "v8_compare.mp4",
       "왼쪽은 관제탑 가상 작업대, 오른쪽은 실물 로봇입니다(둘 다 미리 찍은 영상). 시작 시간이 아니라 집기·운반·내려놓기 단계를 기준으로 보시면 됩니다. 가상 시연의 단계와 시간을 실물에서 잰 값에 맞췄습니다.")

# ───────── 관제 ─────────
ar = ""
for i, (t, d) in enumerate([("역 키오스크", "습득 등록 · 본센터 회수"), ("챗봇 · 분실인 웹", "물건 검색 · 분실 접수"), ("직원 화면", "예외 처리만")]):
    ar += card(128, 300 + i * 166, 440, 146, "", t, d, "light", "rise 1 auto", ts=36, pad="24px 28px")
ar += box(660, 380, 560, 340, f'<h3 style="font-size:56px;font-weight:800;color:#F7F5F1">관제탑</h3><p style="font-size:28px;color:#BFC8D6">파이썬 서버 · 포트 8100</p>'
          f'<p style="font-size:32px;color:{ACCL};font-weight:800;line-height:1.4">화면은 DB에 직접 쓰지 않는다<br>쓰기는 모두 여기서</p>',
          f"background:{INK};border-radius:24px;padding:40px;display:flex;flex-direction:column;gap:16px;{SHADOW}", "pop 2 auto")
ar += card(1300, 300, 492, 250, "", "팀 DB", "PostgreSQL 16 · Docker<br><b>일의 결과: 물건·요청·예약·반환</b>", "soft", "rise 3 auto", ts=40, pad="30px 32px")
ar += card(1300, 590, 492, 220, "", "Langfuse", "인터넷 서비스 · DB 아님<br><b>AI가 판단한 과정</b>", "light", "rise 4 auto", ts=40, pad="30px 32px")
for y1, y2 in [(373, 470), (539, 550), (705, 630)]:
    ar += f'<x-connector x1="568" y1="{y1}" x2="660" y2="{y2}" head="end" style="color:#8A93A3;border-width:3px"></x-connector>\n'
ar += f'<x-connector x1="1220" y1="470" x2="1300" y2="425" head="end" style="color:{ACC};border-width:5px"></x-connector>\n'
ar += f'<x-connector x1="1220" y1="630" x2="1300" y2="700" head="end" style="color:#8A93A3;border-width:3px;border-style:dashed"></x-connector>\n'
ar += ptext(128, 846, 1664, f'가상 시연도 같은 내용을 팀 DB에 함께 쓴다(가상 물건 표시 <span style="color:{ACCD}">object_id = \'SIM\'</span>). 팀 DB가 꺼져도 시연은 계속된다.', f"font-size:28px;color:{SUB};line-height:1.5", "fade 5 auto")
slide("arch", 4, "관제 · 전체 구조", "모든 기록은 관제탑 한 곳을 거쳐 저장", ar,
      note="왼쪽 화면들은 요청만 보내고, 기록을 남기는 것은 관제탑뿐입니다. 결과는 팀 DB에, 챗봇과 메인 AI가 판단한 과정은 Langfuse에 남습니다. 둘은 역할이 다릅니다.")

lf = ""
steps = [("01", "키오스크 등록", "등록기계 보관", "kiosk"), ("02", "직원이 꺼냄", "회수 중", "staff"), ("03", "보관 칸에 넣음", "본센터 보관", "staff"),
         ("04", "방문 · 메인 AI 승인", "승인·수령 예약", "tower"), ("05", "로봇이 꺼내는 중", "반환 중", "tower"), ("06", "제출보관함 도착", "인계 대기", "tower"),
         ("07", "[물건 받았어요]", "인계 완료", "kiosk")]
w7 = (1664 - 6 * 14) // 7
for i, (n, trig, stt, who) in enumerate(steps):
    last = i == 6
    c1, c2 = (ACCD, SUB)
    lf += box(128 + i * (w7 + 14), 300, w7, 330,
              f'<p style="font-size:26px;font-weight:800;color:{c1}">{n}</p><p style="font-size:24px;color:{c2};line-height:1.35">{trig}</p>'
              f'<div style="flex:1"></div><p style="font-size:32px;font-weight:800;line-height:1.25;color:{INK}">{stt}</p><p style="font-size:24px;{MONO};color:{c2}">{who}</p>',
              f"{ST['light'][0]};padding:24px 18px;display:flex;flex-direction:column;gap:10px", f"rise {i + 1} auto")
lf += box(128, 670, 800, None, f'<ul style="font-size:28px;line-height:1.5;color:#2B3545"><li>바뀔 때마다 <b>item.status</b> 수정 + <b>item_status_log</b>에 1줄 추가(무엇에서 무엇으로 · 누가 · 언제)</li><li>누가 = kiosk(키오스크) · staff(직원) · tower(관제탑)</li><li>정상 인계는 직원 없이 — 마지막 기록자도 kiosk</li></ul>', "", "rise 8 auto")
lf += box(980, 670, 812, 240, f'<p style="font-size:26px;color:{ACCL};font-weight:800">물건이 지나온 길 (DBeaver)</p><p style="font-size:26px;{MONO};color:#E7EBF1;line-height:1.5">SELECT from_status, to_status,<br>       changed_by, at<br>FROM item_status_log<br>WHERE item_id = \'A-…\' ORDER BY id;</p>',
          f"background:{INK};border-radius:20px;padding:28px 34px;display:flex;flex-direction:column;gap:8px", "rise 9 auto")
slide("life", 4, "관제 · DB 상태 흐름", "물건 하나의 일생 = item 1행 + 상태 기록 7줄", lf,
      note="물건 한 개는 item 표의 한 줄입니다. 상태가 바뀔 때마다 그 줄의 status를 고치고, item_status_log에 기록이 한 줄씩 쌓입니다. 정상 흐름이면 한 바퀴에 7줄입니다. 예외 흐름(확인 질문 미통과, 직원 교차 검증 불일치)은 반환 보류 쪽으로 빠지며 이 그림에는 없습니다.")

vslide("v4", 4, "영상 4 · 관제", "동작마다 바뀌는 DB", "영상 자리: 통합 화면 DB·에이전트 함께 보기 — DB 실시간 기록과 팀 DB 조회", "화면 녹화",
       ["DB·에이전트 함께 보기 한 화면", "동작마다 표 · 칸 · 값이 바로", "개인정보는 값 대신 '저장됨'", "[팀 DB 조회]로 실제 저장 확인"], "v4_db.mp4",
       "영상 1·2·3을 녹화할 때 DB·에이전트 함께 보기 화면이었다면 그 영상의 오른쪽 기록 부분을 잘라 써도 됩니다.")

rows = [("메인 AI", "나누고 · 확인하고 · 결정, 결정마다 쉬운 설명 한 줄", "sLLM Mi:dm 2.0 mini", True), ("비전", "사진에서 품목·색·특징을 읽음", "VLM Qwen3-VL", True),
        ("키오스크 AI", "접수 내용을 메인 AI에 알림", "코드", False), ("DB", "물건 기록 · 칸 범위를 찾아 답함", "코드(DB 조회)", False),
        ("보관 칸", "품목 열에서 빈 칸을 고름", "규칙(보관함 정답지)", False), ("매칭", "탑뷰 물건 중 찾는 물건 후보와 점수", "코드", False),
        ("로봇팔", "칸 범위 확인 뒤 집기 · 전달", "티칭 경로", False)]
tb = f'<table style="width:1664px;font-size:30px;color:{INK};{FONT}"><tr style="background:#E0DACF"><th style="width:20%;padding:12px 20px">에이전트</th><th style="width:50%">하는 일</th><th style="width:30%">쓰는 것</th></tr>'
tb += "".join(f'<tr{" style=\"background:" + SOFT + "\"" if m else ""}><td>{a}</td><td>{b}</td><td>{c}</td></tr>' for a, b, c, m in rows) + "</table>"
ag = box(128, 300, 1664, None, tb, "", "fade 1 auto")
ag += ptext(128, 840, 1664, "말을 이해하고 설명하는 일은 모델, 정확해야 하는 일은 코드. 두 모델은 관제탑 PC에서 돈다.", "font-size:32px;font-weight:800;color:#2B3545", "rise 2 auto")
slide("agents", 4, "관제 · 에이전트 지도", "말은 모델이, 정확한 일은 코드가", ag, bg=BG2,
      note="sLLM은 작은 언어 모델, VLM은 사진을 함께 읽는 언어 모델입니다. 11/12에 채점 에이전트는 없앴고, 다른 기록과 맞춰 보는 검사는 메인 AI가 직접 합니다. 챗봇 쪽 에이전트(coordinator 등)는 찾기 부분에서 다뤘습니다.")

talk = [("요청", "#D9DEE7", "키오스크 AI → 메인 AI", "중앙역 접수, 사진은 핸드크림·초록", False), ("요청", "#D9DEE7", "메인 AI → DB", "기록 알려 줘 — 역·품목·색·상태", False),
        ("답", "#E6EFE3", "DB → 메인 AI", "A-… · 중앙역 · 핸드크림 · 초록", False), ("확인", "#FBE3C9", "메인 AI", "정답지·역 표와 맞춰 봤어요 — 일치", False),
        ("요청", "#D9DEE7", "메인 AI → 보관 칸", "핸드크림 들어갈 빈 칸은?", False), ("답", "#E6EFE3", "보관 칸 → 메인 AI", "R3-1 (핸드크림 열, 먼 줄)", False),
        ("결정", ACCL, "메인 AI", "회수해서 R3-1 칸에", True), ("설명", "#ECE4F6", "sLLM Mi:dm", "(예) 앞칸이 비어 그 칸으로 정했어요", False)]
tk = ""
for i, (k, kc, path, txt, dark) in enumerate(talk):
    bg = INK if dark else CARD
    bd = "" if dark else (f"border:2px dashed #C9C1B3;" if k == "설명" else "")
    tk += box(128, 300 + i * 74, 1180, 64,
              f'<p style="font-size:26px;font-weight:800;color:{INK};background:{kc};border-radius:999px;text-align:center;width:110px">{k}</p>'
              f'<p style="font-size:26px;color:{"#BFC8D6" if dark else SUB};width:330px">{path}</p><p style="font-size:30px;color:{"#F7F5F1" if dark else INK};font-weight:{700 if dark else 500}">{txt}</p>',
              f"background:{bg};{bd}border-radius:14px;padding:0 22px;display:flex;align-items:center;gap:20px;{SHADOW}", f"left {i + 1} auto")
tk += box(1360, 300, 432, None, f'<h3 style="font-size:36px;font-weight:800">보는 법</h3><ul style="font-size:28px;line-height:1.5;color:#2B3545">'
          f'<li>말은 정해진 틀에 실제 값(물건 번호·칸)을 넣은 것</li><li>통합 화면은 말 하나당 1.6초씩</li><li>어긋나면 "확인할 점이 있어요" + 직원 확인 경보</li><li>설명 한 줄만 sLLM이 쓰고, 없는 숫자·칸을 만들면 버림</li></ul>',
          "display:flex;flex-direction:column;gap:18px", "fade 9 auto")
slide("talk", 4, "관제 · 습득 등록 대화", "습득 한 건에 오가는 말", tk, bg=BG2,
      note="모든 말은 메인 AI를 거칩니다. 마지막 설명 줄은 형식 예시이고, 실제 문장은 그때그때 sLLM이 만듭니다. Qwen 분석이 그래픽카드를 쓰는 중이면 설명은 건너뜁니다.")

br = card(128, 420, 320, 170, "", "매칭 확신 낮음", "또는 닮은 물건 있음", "light", "rise 1 auto", ts=34, pad="26px 26px")
br += box(520, 370, 460, 270, f'<h3 style="font-size:52px;font-weight:800;color:#F7F5F1">메인 AI</h3><p style="font-size:28px;color:{ACCL};font-weight:800">sLLM Mi:dm</p><p style="font-size:28px;color:#BFC8D6;line-height:1.4">다음에 부를 에이전트를 고름 · 최대 4번</p>',
          f"background:{INK};border-radius:24px;padding:36px;display:flex;flex-direction:column;gap:12px;{SHADOW}", "pop 2 auto")
for i, (t, d) in enumerate([("매칭 에이전트", "왜 확신이 낮은지 — 후보·점수·차이"), ("보관 칸 에이전트", "기록된 칸 안에 있는 후보"), ("비전 에이전트", "탑뷰를 다시 찍고 다시 매칭(1번)")]):
    br += card(1060, 300 + i * 160, 732, 140, "", t, d, "light", f"left {3 + i} auto", ts=34, pad="22px 30px")
br += card(520, 690, 460, 190, "", "결론은 코드가", "'확실' + 닮은 물건 없음일 때만 반환 계속", "soft", "rise 6 auto", ts=36, pad="26px 30px")
br += box(1060, 790, 732, 110, f'<p style="font-size:30px;color:#F7F5F1;font-weight:800">반환 계속 → 집기 · 전달</p><p style="font-size:28px;color:{ACCL}">그 밖 → 직원 확인 + 메인 AI 추천</p>',
          f"background:{INK};border-radius:18px;padding:14px 30px;display:flex;flex-direction:column;justify-content:center;gap:2px", "rise 7 auto")
for (x1, y1, x2, y2, hd, c, wdt) in [(448, 505, 520, 505, "end", "#8A93A3", 3), (980, 420, 1060, 370, "both", "#8A93A3", 3), (980, 505, 1060, 530, "both", "#8A93A3", 3),
                                    (980, 590, 1060, 690, "both", "#8A93A3", 3), (750, 640, 750, 690, "end", ACC, 5), (980, 845, 1060, 845, "end", ACC, 5)]:
    br += f'<x-connector x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" head="{hd}" style="color:{c};border-width:{wdt}px"></x-connector>\n'
br += ptext(128, 640, 340, "11/8 실측: 판단 2.3초, 시연 한 바퀴 18~24초<br><br>끄면(TOWER_BRAIN=0) 같은 상황이 곧바로 직원 확인", f"font-size:26px;color:{SUB};line-height:1.5", "fade 8 auto")
slide("brain", 4, "관제 · 관제탑 메인 AI (LangGraph)", "확신이 낮으면 근거를 더 수집", br, bg=BG2,
      note="11/8 집 PC 실측에서 Mi:dm은 정해진 순서(매칭 → 보관 칸 → 비전)와 달리 보관 칸 → 비전을 스스로 골랐고, 다시 찍어 확실해져 반환까지 갔습니다. 메인 AI가 정하는 것은 어느 에이전트를 부를지와 직원에게 줄 추천, 두 가지뿐입니다. 판단 과정은 Langfuse의 tower-main-ai trace에 남습니다. 가상 시연은 분실 메시지 끝에 #흐린촬영을 붙입니다.")

vslide("v5", 4, "영상 5 · 관제", "에이전트 협업", "영상 자리: 에이전트 대화 패널 — 습득 한 건, #흐린촬영으로 메인 AI가 근거를 모으는 장면", "가상 시연",
       ["습득 한 건(초량역 예시)에 에이전트가 차례로", "키오스크 AI → 비전(Qwen) → 메인 AI", "주고받은 말이 아래에 쌓임", "보관 칸 결정과 쉬운 설명까지"], "v5_agents.mp4",
       "메인 AI를 끈 결과(곧바로 직원 확인)와 켠 결과(근거를 모아 반환 계속)를 나란히 보여 주면 역할이 잘 드러납니다.")

# ───────── 신뢰성 ─────────
ex = ""
for i, (q, a) in enumerate([("확인 질문이 안 맞으면", "[직원 확인 후 진행] — 직원이 대면 확인"), ("매칭 확신이 낮으면", "메인 AI가 근거를 더 모으고, 그래도 낮으면 직원 확인 + 추천"),
                            ("방문 전에 취소하면", "예약만 취소, 물건은 같은 칸에 계속 보관"), ("정지를 누르면", "로봇 멈춤 · 중단 이유 표시 · 원점 복귀 뒤 다음 명령")]):
    ex += box(128 + (i % 2) * 848, 300 + (i // 2) * 262, 816, 238,
              f'<p style="font-size:28px;font-weight:800;color:{ACCD}">{q}</p><h3 style="font-size:40px;font-weight:800;line-height:1.3">{a}</h3>',
              f"{ST['light'][0]};padding:34px 40px;display:flex;flex-direction:column;gap:14px", f"rise {i + 1} auto")
ex += ptext(128, 840, 1664, "같은 요청을 반복해도 중복 접수·중복 회수 없음 · DB에 닿지 않으면 실행하지 않음", "font-size:32px;font-weight:800;color:#2B3545", "rise 5 auto")
slide("except", 5, "신뢰성 · 막혔을 때", "잘 안 될 때는 확정 보류", ex,
      note="정지 후 자동으로 이어서 하는 기능은 아직 설계 단계입니다. 지금은 원점으로 돌아간 뒤 다시 실행하는 방식입니다.")

vslide("v6", 5, "영상 6 · 신뢰성", "확인 답이 다르면 직원에게", "휴대폰 분실 신고 → 확인 답 불일치 → 본센터 직원 확인 안내(C-…0019)", "화면 녹화",
       ["물건 설명 · 본인 확인 · 신고", "확인 답이 맞지 않음", "자동 반환하지 않고 직원 확인", "다른 예외는 추가 촬영"], "v6_except.mp4",
       "확인 질문의 답이 맞지 않으면 찾기 번호는 주지만 자동 반환은 하지 않고, 본센터 직원이 대면으로 확인한다고 안내합니다. [직원 확인 후 진행] 이후, 정지·원점 복귀, 찾기 취소 장면은 아직 없습니다.")

sf = ""
for i, t in enumerate(["메인 AI가 정하는 것은 '누구를 부를지'와 '직원에게 줄 추천'뿐", "반환 계속 조건은 그대로: 매칭 '확실' + 닮은 물건 검사, 코드가 한 번 더 확인",
                       "탑뷰 물건 중심이 DB 칸 범위 밖이면 멈추고 직원 확인", "DB에 닿지 않아 중복 확인을 못 하면 실행하지 않음", "sLLM 설명이 결정에 없는 숫자·칸 번호를 만들면 버림"]):
    sf += box(128, 420 + i * 92, 1664, 76, f'<p style="font-size:30px;font-weight:800;color:{ACC};background:{INK};border-radius:50%;width:56px;height:56px;text-align:center;line-height:1.9">{i + 1}</p><p style="font-size:36px;font-weight:700;color:{INK}">{t}</p>',
              "display:flex;align-items:center;gap:26px", f"left {i + 2} auto")
safety_head = (f'<p style="font-size:28px;font-weight:800;color:{INK};letter-spacing:1px">안전 원칙</p>\n'
               f'<h2 style="font-size:100px;font-weight:800;line-height:1.1;color:{INK}" data-build-in="fade 1 auto">로봇을 움직일지는 코드가 결정</h2>\n')
(OUT / "safety.html").write_text(
    f'<section id="safety" data-transition="magic" style="background:{ACC};color:{INK};{FONT};padding:128px 128px 160px;display:flex;flex-direction:column;gap:16px">\n'
    + safety_head + sf + rail(5, "accent") + "<aside>AI는 더 조심하게 만들 수만 있고, 더 과감하게 만들 수는 없습니다. 에이전트 대화가 할 수 있는 일은 멈추고 직원을 부르는 것뿐입니다.</aside>\n</section>\n", encoding="utf-8")

# ───────── 근거 · 범위 · 마무리 ─────────
pr = ""
for i, (num, t, d, st) in enumerate([("1,934", "자동 시험", "11/12 전체 실행 · PR마다 GitHub에서 자동", "light"), ("500", "챗봇 채점 문항", "사용자 말투, 문항마다 0/1 · Mi:dm 459점(11/9)", "light"),
                                     ("0", "안전 위반", "시험 사례 10개(11/12)", "soft"), ("13", "버전 관리 프롬프트", "에이전트 1개 = Langfuse 프롬프트 1개", "light")]):
    bg = ST[st][0]
    pr += box(128 + i * 422, 300, 398, 440, f'<p style="font-size:110px;font-weight:800;line-height:1;color:{INK}">{num}</p><div style="flex:1"></div><p style="font-size:32px;font-weight:800">{t}</p><p style="font-size:26px;color:{SUB};line-height:1.45">{d}</p>',
              f"{bg};padding:40px 34px;display:flex;flex-direction:column;gap:12px", f"pop {i + 1} auto")
pr += ptext(128, 790, 1664, "실패 발견 → 고침 → 같은 시험으로 다시 확인 · 기록은 GitHub PR과 Jira에", "font-size:32px;font-weight:800;color:#2B3545", "rise 5 auto")
slide("proof", 6, "근거", "고칠 때마다 다시 측정", pr,
      note="채점표 500문항은 규칙만으로 500점이지만 채점표에 맞춘 면이 있어 실제 모델(Mi:dm) 점수와 함께 봅니다. Mi:dm 다시 측정은 TBD입니다. 시험 수는 11/12 저장소 기준이며, 오류 9개는 tkinter가 없는 환경 문제로 기존과 같습니다.")

sc_rows = [("역 키오스크 자동 촬영 + 사진 분석", "실물 확인", "교육원 웹캠 · Qwen3-VL", 0), ("본센터 본인 확인 → 로봇 반환", "실물 확인", "원격 티칭 로봇 · 검정폰·립밤 촬영", 0),
           ("직원 없는 인계 [물건 받았어요]", "구현 · 실물 촬영 예정", "영상 3에서 확인", 0), ("챗봇 대화 검색·접수", "구현 · 시험 확인", "500문항 채점표", 0),
           ("메인 AI(매칭 확신이 낮을 때)", "가상 확인", "#흐린촬영 시연", 0), ("팀 DB 기록", "시험용 DB 확인", "같은 표 정의 PostgreSQL 16", 0),
           ("회수·통계 관리자 화면", "구현 · 기본 꺼짐", "DB 담당 확인 뒤 켬", 0), ("정지 후 자동 재개", "설계 단계", "지금은 원점 복귀 후 다시", 1), ("음성 입력", "미구현", "—", 1)]
st_ = f'<table style="width:1664px;font-size:28px;color:{INK};{FONT}"><tr style="background:#E0DACF"><th style="width:38%;padding:10px 20px">기능</th><th style="width:26%">상태</th><th style="width:36%">근거 · 비고</th></tr>'
st_ += "".join(f'<tr{" style=\"background:" + BG2 + "\"" if g else ""}><td>{a}</td><td>{b}</td><td>{c}</td></tr>' for a, b, c, g in sc_rows) + "</table>"
slide("scope", 6, "범위", "실물로 확인한 것과 남은 것", box(128, 290, 1664, None, st_, "", "fade 1 auto"),
      note="실물로 확인한 것, 가상으로 확인한 것, 아직 아닌 것을 나눠 말합니다. 발표 전에 상태 칸을 팀원과 한 번 더 맞춰 주세요(특히 로봇 8칸 전체와 실제 수령 장면).")

ed = box(0, 0, 24, 1080, "", f"background:{ACC}")
for i, (a, b_, c) in enumerate([("맡기기는 ", "넣기만", ""), ("찾기는 ", "웹·챗봇", "에서"), ("돌려주기는 ", "확인된 만큼만", "")]):
    ed += f'<h2 style="position:absolute;left:128px;top:{260 + i * 120}px;width:1664px;font-size:88px;font-weight:800;line-height:1.2;color:#F7F5F1" data-build-in="rise {i + 1} auto">{a}<span style="color:{ACCL}">{b_}</span>{c}</h2>\n'
ed += ptext(128, 700, 420, "감사합니다", f"font-size:52px;font-weight:800;color:{INK};background:{ACCL};border-radius:18px;padding:16px 40px;text-align:center", "pop 4 auto")
(OUT / "end.html").write_text(
    f'<section id="end" data-transition="magic" style="background:{INK};color:#F7F5F1;{FONT};padding:128px;display:flex;flex-direction:column">\n'
    + ed + "<aside>질문을 받습니다. 한계는 범위 장에서 이미 나눠 말했습니다.</aside>\n</section>\n", encoding="utf-8")


# ═════════ 11/12 2차: 움직이는 그림 · 새 장 · 마무리 문구 ═════════
import embeds


def em(fn, left, top):
    return fn().replace("{L}", str(left)).replace("{T}", str(top)) + "\n"


slide("flow", 0, "한 바퀴 요약", "물건 하나가 주인에게 돌아가기까지", em(embeds.route, 128, 290)
      + pills(792, [("모든 단계를 AI 관제탑이 잇고 기록", P_SOFT), ("정상은 직원 없이, 확인되지 않으면 직원에게", P_DARK)], "rise 1 auto"),
      note="물건(검은 네모)이 노선을 따라 접수 → 보관 → 찾기 → 반환 → 인계로 이동하고, 지금 단계의 카드가 빛납니다. 전반부는 여기까지 간략하게 보고 바로 전체 흐름 영상을 보여 줍니다.")

slide("arch", 4, "관제 · 연결 지도", "모든 기록은 관제탑 한 곳을 거쳐 저장", em(embeds.connect, 128, 290),
      note="습득 → 찾기 → 반환 세 장면이 5초씩 돌며, 그때 움직이는 연결선이 주황으로 흐릅니다. 관제탑 → 팀 DB 는 늘 흐르고, DBeaver 는 팀 DB 를 읽기만 합니다(파란 점). AI 가 판단한 과정은 Langfuse, 운영 알림은 디스코드, 로봇 실행은 로봇 PC 로 갑니다. 화면들은 DB 에 직접 쓰지 않고, 가상 시연도 같은 내용을 팀 DB 에 함께 씁니다(object_id = 'SIM').")

cb2 = em(embeds.chatflow, 128, 300)
cb2 += box(1120, 300, 672, None,
           f'<h3 style="font-size:36px;font-weight:800">500문항 채점표 (사용자 말투)</h3>'
           f'<table style="width:672px;font-size:28px;color:{INK};{FONT}"><tr style="background:#E0DACF"><th style="width:26%;padding:10px 16px">단계</th><th style="width:52%">모델</th><th style="width:22%">점수</th></tr>'
           f'<tr><td>11/9 01</td><td>규칙만</td><td>355</td></tr><tr><td>11/9 03</td><td>Mi:dm 2.0 Mini</td><td>403</td></tr>'
           f'<tr style="background:{SOFT}"><td>11/9 06</td><td>Mi:dm + 프롬프트 13개</td><td>459</td></tr><tr><td>11/9 07~</td><td>규칙만(보강)</td><td>500*</td></tr></table>'
           f'<p style="font-size:26px;color:{SUB};line-height:1.5">* 채점표에 맞춘 면이 있어 Mi:dm 점수와 함께 봄<br>에이전트 1개 = Langfuse 프롬프트 1개 — 배포 없이 고침</p>',
           "display:flex;flex-direction:column;gap:18px", "rise 1 auto")
slide("chatbot", 2, "③ 찾기 · 챗봇 (DeerFlow 구조)", "질문 하나가 감독을 거쳐 일꾼에게", cb2, bg=BG2,
      note="질문이 coordinator → planner → supervisor 를 거쳐 item_search 로 갔다가 돌아오고, reporter 가 답을 정리하는 길을 점이 따라갑니다. 말을 이해하고 판단하는 칸은 모델과 프롬프트, 검색·접수처럼 기록을 남기는 일은 코드로 나눈 혼합 구조입니다. 모델은 규칙이 허용한 목록 안에서만 고릅니다. 직원용 관제 분석(ops_analyst)은 관리자 화면에서만 쓰여 그림에서 뺐습니다.")

slide("talk", 4, "관제 · 에이전트 대화", "습득 한 건에 에이전트들이 주고받는 말", em(embeds.agents, 128, 290), bg=BG2,
      note="메인 AI 를 가운데 두고, 말 하나가 오갈 때마다 점이 그 에이전트와 메인 AI 사이를 오가며 오른쪽 기록에 한 줄씩 쌓입니다(실제 통합 화면은 말 하나당 1.6초). 말은 정해진 틀에 실제 값(물건 번호·칸)을 넣은 것이고, 마지막 설명 한 줄만 sLLM 이 씁니다(형식 예시). 어긋나면 '확인할 점이 있어요'와 함께 직원 확인 경보가 갑니다.")

ln = ""
for i, (t, d) in enumerate([("정확해야 하는 일은<br>코드에", "모델은 말을 이해하고 설명하는 일만. 실행 조건 · 기록 · 숫자는 코드가 정해 결과가 늘 같음"),
                            ("실물은 가상과 다름", "로봇 단계 시간 · 카메라 노출을 실제로 재서 가상 시연을 실물에 맞춤"),
                            ("약속(계약)으로 나누면<br>다섯이 동시에", "입·출력 약속을 먼저 정해 비전 · 로봇 · 챗봇 · 관제탑을 따로 만들고 한 번에 연결")]):
    ln += box(128 + i * 565, 300, 533, 520,
              f'<p style="font-size:120px;font-weight:800;line-height:1;color:{ACC}">{i + 1}</p><div style="flex:1"></div>'
              f'<h3 style="font-size:44px;font-weight:800;line-height:1.25">{t}</h3><p style="font-size:30px;color:{SUB};line-height:1.5">{d}</p>',
              f"{ST['light'][0]};padding:44px 40px;display:flex;flex-direction:column;gap:18px", f"rise {i + 1} auto")
slide("learn", 6, "배운 점", "만들면서 배운 세 가지", ln, note="발표 마무리 전에 팀이 얻은 교훈을 짧게 말합니다.")

tm = ""
for i, (nm, rl) in enumerate([("김건태", "비전 · 매칭<br>8칸 티칭 · 로봇 원격 실행"), ("변재원", "관제탑 · DB · 화면 통합<br>메인 AI · 에이전트"),
                              ("김재민", "웹 · 키오스크 화면<br>관리자 · 회수 화면"), ("이순필", "SO-ARM 구축 · 사진 분석 실험<br>작업대 · 실물 시연"),
                              ("정연우", "챗봇 후속 · 대화 평가<br>회수 · 통계 · 정합성")]):
    w = (1664 - 4 * 24) // 5
    tm += box(128 + i * (w + 24), 330, w, 450,
              f'<div style="width:96px;height:96px;border-radius:50%;background:{INK if i % 2 else ACC};display:flex;align-items:center;justify-content:center">'
              f'<p style="font-size:40px;font-weight:800;color:{ACCL if i % 2 else INK}">{nm[0]}</p></div><div style="flex:1"></div>'
              f'<h3 style="font-size:44px;font-weight:800">{nm}</h3><p style="font-size:28px;color:{SUB};line-height:1.5">{rl}</p>',
              f"{ST['light'][0]};padding:40px 30px;display:flex;flex-direction:column;gap:14px", f"rise {i + 1} auto")
slide("team", 6, "팀", "AgentOps 2조, 다섯 명의 역할 분담", tm, note="Q&A 때 질문을 맡을 사람을 바로 찾을 수 있게 역할을 한 줄씩 적었습니다.")

ed = box(0, 0, 24, 1080, "", f"background:{ACC}")
for i, (a, b_, c) in enumerate([("맡기기는 ", "넣기만", ""), ("찾기는 ", "말 한마디로", ""), ("돌려받기는 ", "직원 없이", "")]):
    ed += f'<h2 style="position:absolute;left:128px;top:{220 + i * 120}px;width:1664px;font-size:88px;font-weight:800;line-height:1.2;color:#F7F5F1" data-build-in="rise {i + 1} auto">{a}<span style="color:{ACCL}">{b_}</span>{c}</h2>\n'
ed += ptext(128, 620, 1664, "잃어버린 물건이 주인에게 돌아가는 길, AI 관제탑이 잇습니다", "font-size:40px;color:#BFC8D6", "fade 4 auto")
ed += ptext(128, 760, 420, "감사합니다", f"font-size:52px;font-weight:800;color:{INK};background:{ACCL};border-radius:18px;padding:16px 40px;text-align:center", "pop 5 auto")
(OUT / "end.html").write_text(
    f'<section id="end" data-transition="magic" style="background:{INK};color:#F7F5F1;{FONT};padding:128px;display:flex;flex-direction:column">\n'
    + ed + "<aside>세 줄로 정리하고 질문을 받습니다.</aside>\n</section>\n", encoding="utf-8")


# ═════════ 11/12 3차: 앞 장 움직이는 그림 · 강조 정리 · 글 줄이기 ═════════
import embeds2

# 표지: 양 옆 역 → 본센터로 물건이 들어온다
cv = (box(0, 0, 24, 1080, "", f"background:{ACC}")
      + ptext(128, 128, 1664, "AgentOps 2조 · Agentic AI 프로젝트", f"font-size:32px;font-weight:800;color:{ACCL};letter-spacing:2px", "fade 1 auto")
      + f'<h1 style="position:absolute;left:128px;top:330px;width:1664px;font-size:150px;font-weight:800;line-height:1.05;color:#F7F5F1" data-build-in="rise 2 auto">AI 분실물 관제탑</h1>\n'
      + ptext(128, 530, 1664, "맡기면 AI가 기록하고, 확인되면 로봇이 돌려줍니다", "font-size:48px;color:#BFC8D6", "fade 3 auto")
      + em(embeds2.cover, 128, 620)
      + ptext(196, 780, 200, "중앙역", "font-size:30px;font-weight:700;color:#BFC8D6;text-align:center", "fade 4 auto")
      + ptext(814, 792, 300, "부산역 본센터", "font-size:32px;font-weight:800;color:#F7F5F1;text-align:center", "fade 4 auto")
      + ptext(1516, 780, 200, "초량역", "font-size:30px;font-weight:700;color:#BFC8D6;text-align:center", "fade 4 auto")
      + box(128, 880, 1664, None,
            f'<p style="font-size:26px;color:{INK};background:{ACCL};padding:10px 26px;border-radius:999px;font-weight:800">역 키오스크 · 본센터 · 로봇팔</p>'
            f'<p style="font-size:26px;color:#F7F5F1;border:2px solid #4A5A70;padding:8px 26px;border-radius:999px">sLLM · VLM · 에이전트</p>'
            f'<p style="font-size:26px;color:#F7F5F1;border:2px solid #4A5A70;padding:8px 26px;border-radius:999px">2026. 11</p>',
            "display:flex;gap:20px", "fade 5 auto"))
(OUT / "cover.html").write_text(
    f'<section id="cover" data-transition="magic" style="background:{INK};color:#F7F5F1;{FONT};padding:128px;display:flex;flex-direction:column">\n'
    + cv + "<aside>양 옆 중앙역·초량역에서 맡긴 물건이 부산역 본센터로 모이는 모습입니다. 전반부는 한눈에 간략하게, 후반부는 하나씩 자세히 설명하고, 설명 장 뒤에는 바로 그 장면 영상이 나옵니다.</aside>\n</section>\n", encoding="utf-8")

# 문제: 카드마다 움직이는 그림
pb = ""
for i, (who, worry, fix) in enumerate([("주운 사람", "어디에 맡기지?", "→ 역 키오스크에 넣기만"),
                                        ("잃어버린 사람", "어느 역이었지?", "→ 웹·챗봇에서 모든 역을 한 번에"),
                                        ("보관하는 쪽", "진짜 주인일까?", "→ 확인 질문 + 키오스크 본인 확인")]):
    x = 128 + i * 565
    pb += box(x, 290, 533, 620,
              f'<p style="font-size:32px;font-weight:700;color:{SUB}">{who}</p>'
              f'<h3 style="font-size:52px;font-weight:800;line-height:1.2">{worry}</h3><div style="flex:1"></div>'
              f'<p style="font-size:32px;font-weight:700;color:{INK};background:{SOFT};border-radius:16px;padding:20px 24px">{fix}</p>',
              f"{ST['light'][0]};padding:44px 44px;display:flex;flex-direction:column;gap:20px", f"rise {i + 1} auto")
    pb += em(lambda i=i: embeds2.prob(i), x + 44, 540)
slide("problem", 0, "문제", "분실물, 세 사람 모두에게 번거로운 일", pb,
      note="각 카드의 그림: 주운 사람은 어디에 맡길지 몰라 물음표가 뜨다가 역 키오스크에 넣고, 잃어버린 사람은 역을 하나씩 찾아다니다가 모든 역을 한 번에 검색하고, 보관하는 쪽은 똑같은 두 휴대폰 중 확인 질문으로 주인을 가립니다.")

# 해결: ①~④ 진행 + 관제탑과 주고받기
so = em(embeds2.solution, 128, 290)
so += pills(836, [("정상 흐름은 사람 없이", P_SOFT), ("확인되지 않으면 직원에게", P_DARK)], "rise 1 auto", center=True)
slide("solution", 0, "해결", "네 단계를 잇는 AI 관제탑 하나", so,
      note="물건이 ① → ④ 정거장을 지날 때마다 그 단계가 관제탑에 보고하고(주황 점), 관제탑이 기록·확인해서 돌려줍니다(초록 점). 관제탑 상자 안에 그때 남긴 기록이 한 줄씩 바뀝니다. 확인되지 않은 단계가 있으면 로봇을 멈추고 직원에게 넘깁니다.")

# 전체 구성: 그림 지도 + 보관함 R 설명
slide("system", 0, "전체 구성", "역 · 관제탑 · 본센터를 하나로 연결", em(lambda: embeds2.system()[0], 128, 290) + em(lambda: embeds2.system()[1], 928, 290) + ''.join(em(lambda h=h: h, 1496, 722) for h in __import__('tower_arm2').side4()) + ''.join(em(lambda h=h: h, 928, 290) for h in __import__('tower_arm2').top_embed()),
      note="왼쪽은 물건을 맡기는 역 키오스크와 분실인 휴대폰, 가운데는 모든 연결이 지나가는 관제탑 PC, 오른쪽은 부산역 본센터입니다. 보관함은 4줄 × 2칸이고, R은 보관함 줄(Row) 번호입니다. 줄마다 품목 하나(R1 휴대폰 · R2 보조배터리 · R3 핸드크림 · R4 립밤), -1은 먼 칸, -2는 로봇 쪽 칸입니다. 그래서 R4-1은 '립밤 줄의 먼 칸'입니다. 로봇팔은 칸 번호에 맞춰 미리 가르친 자세로 집어 제출보관함에 놓습니다.")

# 한 바퀴: 검은 휴대폰이 나타나 지나가고 사라진다
slide("flow", 0, "한 바퀴 요약", "물건 하나가 주인에게 돌아가기까지", em(embeds2.route, 128, 290)
      + pills(792, [("모든 단계를 AI 관제탑이 잇고 기록", P_SOFT), ("정상은 직원 없이, 확인되지 않으면 직원에게", P_DARK)], "rise 1 auto"),
      note="검은 휴대폰이 접수 정거장에서 서서히 나타나 보관 → 찾기 → 반환 → 인계를 지나고, 마지막에 서서히 사라집니다. 지금 단계의 카드에 주황 테두리가 생깁니다.")

# 맡기기: 카드 5장 빈칸에 그림
fd = row_cards([("01", "넣기", "포토박스 안에 물건 두기", "light"),
                ("02", "자동 촬영", "손을 빼고 5초 멈추면 찰칵, 버튼 없음", "light"),
                ("03", "장소 고르기", "그 역의 장소 목록, 없으면 직접 입력", "light"),
                ("04", "연락처 (선택)", "안 남겨도 접수, 30일 뒤 자동 삭제", "light"),
                ("05", "접수 완료", "다음 과정을 안내, 본센터로 회수", "light")], 300, 420)
for i in range(5):
    fd += em(lambda i=i: embeds2.found(i), 128 + i * 336 + 28, 376)
fd += box(128, 780, 1664, None, f'<p style="font-size:30px;font-weight:800;color:#2B3545;padding:16px 0">본센터 보관 줄(R)</p>' + "".join(
    f'<p style="font-size:30px;font-weight:800;background:{CARD};border:2px solid {LINE};border-radius:14px;padding:14px 26px"><span style="color:{ACCD}">{t.split()[0]}</span> {t.split()[1]}</p>'
    for t in ["R1 휴대폰", "R2 보조배터리", "R3 핸드크림", "R4 립밤"]), "display:flex;gap:18px;align-items:center", "rise 6 auto")
slide("found", 1, "① 맡기기 · 역 키오스크", "상자에 넣고 장소만 고르면 끝", fd,
      note="주운 사람이 할 일은 넣고 장소를 고르는 것뿐입니다. 촬영 버튼은 없고, 물건이 들어오고 손이 빠진 뒤 5초 동안 움직임이 없으면 자동으로 찍습니다. 접수된 물건은 본센터에서 품목별 줄(R1~R4)에 보관합니다.")

# 에이전트 지도: 표 → 모델이 맡는 일 / 코드가 맡는 일
ag = box(128, 300, 700, 560, f'<p style="font-size:28px;font-weight:800;color:{ACCL}">모델이 맡는 일</p><h3 style="font-size:40px;font-weight:800;color:#F7F5F1">말을 이해하고 설명</h3>'
         + "".join(f'<div style="background:#24324A;border-radius:18px;padding:22px 26px;display:flex;flex-direction:column;gap:6px"><p style="font-size:36px;font-weight:800;color:#F7F5F1">{a}</p><p style="font-size:26px;color:{ACCL};font-weight:700">{m}</p><p style="font-size:26px;color:#D5DCE6">{d}</p></div>'
                   for a, m, d in [("메인 AI", "sLLM Mi:dm 2.0 mini", "누구를 부를지 고르고, 결정마다 쉬운 설명"), ("비전", "VLM Qwen3-VL", "사진에서 품목 · 색 · 특징을 읽음")]),
         f"background:{INK};border-radius:28px;padding:36px;display:flex;flex-direction:column;gap:18px;{SHADOW}", "rise 1 auto")
ag += box(870, 300, 922, 560, f'<p style="font-size:28px;font-weight:800;color:{ACCD}">코드가 맡는 일</p><h3 style="font-size:40px;font-weight:800">정확해야 하는 일</h3>'
          f'<div style="display:flex;flex-wrap:wrap;gap:16px">' + "".join(
              f'<div style="width:404px;background:{CARD};border:2px solid {LINE};border-radius:18px;padding:18px 22px"><p style="font-size:32px;font-weight:800">{a}</p><p style="font-size:24px;color:{SUB}">{d}</p></div>'
              for a, d in [("키오스크 AI", "접수 내용을 메인 AI에 알림"), ("DB", "물건 기록 · 칸 범위 조회"), ("보관 칸", "품목 줄에서 빈 칸 고르기"), ("매칭", "탑뷰 후보와 점수"), ("로봇팔", "칸 범위 확인 뒤 티칭 경로로 집기")]) + "</div>",
          f"background:{BG2};border-radius:28px;padding:36px;display:flex;flex-direction:column;gap:18px", "rise 2 auto")
slide("agents", 4, "관제 · 에이전트 지도", "말은 모델이, 정확한 일은 코드가", ag,
      note="sLLM은 작은 언어 모델, VLM은 사진을 함께 읽는 언어 모델로, 둘 다 관제탑 PC에서 돕니다. 11/12에 채점 에이전트는 없앴고, 다른 기록과 맞춰 보는 검사는 메인 AI가 직접 합니다. 챗봇 쪽 에이전트(coordinator 등)는 찾기 부분에서 다뤘습니다.")

# 범위: 표 → 세 칸
cols = [("실물로 확인", "#2E9E5B", "#E7F5EC", ["역 키오스크 자동 촬영 + 사진 분석", "본센터 본인 확인 → 로봇 반환", "로봇 8칸 티칭 동작"]),
        ("가상 · 시험으로 확인", ACC, SOFT, ["챗봇 대화 검색 · 접수 (500문항)", "메인 AI 근거 모으기 (#흐린촬영)", "팀 DB 기록 (PostgreSQL 16)", "직원 없는 인계 (실물 촬영 예정)"]),
        ("남은 것", "#6B7280", BG2, ["정지 후 자동 재개 (설계 단계)", "음성 입력 (미구현)", "회수·통계 관리자 화면 (기본 꺼짐)"])]
sc = ""
for i, (h, c, bgc, items) in enumerate(cols):
    sc += box(128 + i * 565, 300, 533, 600,
              f'<p style="font-size:34px;font-weight:800;color:{c}">{h}</p>' + "".join(
                  f'<div style="background:{CARD};border-left:8px solid {c};border-radius:14px;padding:18px 22px"><p style="font-size:29px;font-weight:700;line-height:1.35">{t}</p></div>' for t in items),
              f"background:{bgc};border-radius:28px;padding:36px 32px;display:flex;flex-direction:column;gap:16px", f"rise {i + 1} auto")
slide("scope", 6, "범위", "실물로 확인한 것과 남은 것", sc,
      note="실물로 확인한 것, 가상·시험으로 확인한 것, 아직 아닌 것을 나눠 말합니다. 발표 전에 팀원과 한 번 더 맞춰 주세요(특히 실제 수령 장면).")

# 안전 원칙: 주황 전면 배경 → 밝은 배경
sf = ""
for i, t in enumerate(["메인 AI가 정하는 것은 '누구를 부를지'와 '직원에게 줄 추천'뿐", "반환 계속 조건은 그대로: 매칭 '확실' + 닮은 물건 검사, 코드가 한 번 더 확인",
                       "탑뷰 물건 중심이 DB 칸 범위 밖이면 멈추고 직원 확인", "DB에 닿지 않아 중복 확인을 못 하면 실행하지 않음", "sLLM 설명이 결정에 없는 숫자·칸 번호를 만들면 버림"]):
    sf += box(128, 300 + i * 112, 1664, 92, f'<p style="font-size:32px;font-weight:800;color:{ACCL};background:{INK};border-radius:50%;width:60px;height:60px;text-align:center;line-height:1.85;flex:none">{i + 1}</p><p style="font-size:34px;font-weight:700;color:{INK}">{t}</p>',
              f"{ST['light'][0]};border-radius:20px;padding:0 30px;display:flex;align-items:center;gap:26px", f"rise {i + 1} auto")
slide("safety", 5, "안전 원칙", "로봇을 움직일지는 코드가 결정", sf,
      note="AI는 더 조심하게 만들 수만 있고, 더 과감하게 만들 수는 없습니다. 에이전트 대화가 할 수 있는 일은 멈추고 직원을 부르는 것뿐입니다.")


# ═════════ 11/12 4차: 빈 공간 채우기 · 안전 원칙 합치기 · 근거/범위/배운 점 다시 구성 ═════════
import embeds3

# 9쪽 사진 분석: 2x2 단계 카드 + 실제 사진 분석 카드 화면
vs = ""
for i, (lab, t, d, st) in enumerate([("① 사진", "키오스크 웹캠", "회색 펠트 바닥 위에서 한 장", "light"),
                                      ("② VLM Qwen3-VL 읽기", "품목 · 색 · 특징", "보이는 특징은 공개 칸, 글자·스티커는 비공개 칸(확인 질문용)", "dark"),
                                      ("③ 숫자로 다시 재기", "색 · 크기 측정", "펠트 기준 색값 · 길이·폭으로 크림 ↔ 립밤 확인, 확실할 때만 수정", "light"),
                                      ("④ 저장", "팀 DB", "features · private_features 두 칸에 나눠 저장", "soft")]):
    vs += card(128 + (i % 2) * 580, 290 + (i // 2) * 320, 560, 300, lab, t, d, st, f"rise {i + 1} auto", ts=40, bs=27)
vs += (f'<img src="/_blob/580b5d1c186c74bcf2f7484eb9708345" alt="통합 화면 사진 분석 카드: Qwen이 읽은 값과 DB에 저장한 값" '
       f'style="position:absolute;left:1316px;top:290px;width:476px;height:557px;object-fit:contain;background:#FFFFFF;border-radius:22px;border:2px solid {LINE};{SHADOW}" data-build-in="fade 5 auto">\n')
vs += ptext(1316, 862, 476, f'실제 화면 · <span style="color:{ACCD}">읽은 값 → 저장한 값</span>', "font-size:24px;font-weight:700;color:#2B3545;text-align:center", "fade 6 auto")
slide("vision", 1, "① 맡기기 · AI 사진 분석", "사진 한 장 → 특징 → DB", vs,
      note="VLM은 사진과 글을 함께 읽는 언어 모델입니다. 오른쪽은 통합 화면의 실제 사진 분석 카드로, 빨간 립밤을 Qwen이 '분홍'으로 읽었지만 색 측정으로 '빨강'으로 고쳐 저장한 예입니다. 글자·스티커 같은 비공개 특징은 값을 가리고 저장됐다고만 보여 줍니다.")

# 14쪽 돌려받기: 카드 빈칸에 그림
rt = row_cards([("01", "본인 확인", "찾기 번호 + 신분 번호 뒤 첫 자리", "light"),
                ("02", "메인 AI 승인", "기록과 대조, 칸 위치 확인", "light"),
                ("03", "로봇팔", "칸 번호 → 미리 가르친 자세로 집기", "dark"),
                ("04", "제출보관함", "물건 도착, 로봇은 원점으로", "light"),
                ("05", "물건 받았어요", "꺼내고 누르면 인계 완료", "light")], 300, 440, ts=38)
for i in range(5):
    if i == 2:
        rt += ''.join(em(lambda h=h: h, 128 + i * 336 + 28, 376) for h in __import__('tower_arm2').side14())
    else:
        rt += em(lambda i=i: embeds3.ret(i), 128 + i * 336 + 28, 376)
rt += box(128, 790, 1664, None,
          f'<p style="flex:2;font-size:36px;font-weight:800;background:{INK};color:#F7F5F1;border-radius:18px;padding:26px 34px">정상 흐름은 직원 없이 · 직원은 예외만</p>'
          f'<p style="flex:1;font-size:30px;color:#2B3545;background:{CARD};border:2px solid {LINE};border-radius:18px;padding:28px 30px">실물 로봇 한 바퀴 약 44초(11단계)</p>',
          "display:flex;gap:24px;align-items:stretch", "rise 6 auto")
slide("ret", 3, "④ 돌려받기 · 부산역 본센터", "키오스크가 확인하고, 로봇이 꺼내는 반환", rt,
      note="카드 그림 순서: 찾기 번호와 숫자 하나 입력 → 메인 AI가 기록·칸·본인을 차례로 확인 → 로봇이 R4-1(=pose_7) 자세로 집기 → 제출보관함 도착 → 분실인이 [물건 받았어요]를 눌러 인계 완료. 직원은 확인 질문 미통과, 직원 보관 선반, 정지, 원점 복귀 같은 예외에만 나섭니다.")

# 19쪽 DB 상태 흐름: 카드 가운데 아이콘 + 상태 기록이 한 줄씩
lf = ""
w7 = (1664 - 6 * 14) // 7
for i, (n, trig, stt, who) in enumerate(steps):
    lf += box(128 + i * (w7 + 14), 290, w7, 370,
              f'<p style="font-size:26px;font-weight:800;color:{ACCD}">{n}</p><p style="font-size:23px;color:{SUB};line-height:1.35">{trig}</p>'
              f'<div style="flex:1"></div><p style="font-size:26px;font-weight:800;line-height:1.25;color:{INK};white-space:nowrap">{stt}</p><p style="font-size:23px;{MONO};color:{SUB}">{who}</p>',
              f"{ST['light'][0]};padding:22px 18px;display:flex;flex-direction:column;gap:8px", f"rise {i + 1} auto")
lf += em(embeds3.life_icons, 128, 428)
lf += em(embeds3.life_log, 128, 690)
lf += box(980, 690, 812, 250, f'<p style="font-size:26px;color:{ACCL};font-weight:800">물건이 지나온 길 (DBeaver)</p><p style="font-size:25px;{MONO};color:#E7EBF1;line-height:1.5">SELECT from_status, to_status,<br>       changed_by, at<br>FROM item_status_log<br>WHERE item_id = \'A-…\' ORDER BY id;</p>',
          f"background:{INK};border-radius:20px;padding:28px 34px;display:flex;flex-direction:column;gap:8px", "rise 9 auto")
slide("life", 4, "관제 · DB 상태 흐름", "물건 하나의 일생 = item 1행 + 상태 기록 7줄", lf,
      note="지금 단계의 아이콘에 주황 테두리가 생기고, 아래 item_status_log 표에 그 단계의 기록이 한 줄씩 쌓입니다(무엇에서 무엇으로 · 누가). 누가 = kiosk(키오스크) · staff(직원) · tower(관제탑). 정상 인계는 직원 없이 끝나므로 마지막 기록자도 kiosk입니다. 예외 흐름은 반환 보류 쪽으로 빠지며 이 그림에는 없습니다.")

# 25쪽 막혔을 때 + 안전 원칙(27쪽에서 합침)
ex = ""
for i, (q, a) in enumerate([("확인 질문이 안 맞으면", "[직원 확인 후 진행] — 직원이 대면 확인"), ("매칭 확신이 낮으면", "메인 AI가 근거를 더 모으고, 그래도 낮으면 직원 확인 + 추천"),
                            ("방문 전에 취소하면", "예약만 취소, 물건은 같은 칸에 계속 보관"), ("정지를 누르면", "로봇 멈춤 · 중단 이유 표시 · 원점 복귀 뒤 다음 명령")]):
    ex += box(128 + (i % 2) * 848, 290 + (i // 2) * 250, 816, 228,
              f'<p style="font-size:28px;font-weight:800;color:{ACCD}">{q}</p><h3 style="font-size:38px;font-weight:800;line-height:1.3">{a}</h3>',
              f"{ST['light'][0]};padding:32px 40px;display:flex;flex-direction:column;gap:12px", f"rise {i + 1} auto")
ex += box(128, 800, 1664, 140,
          f'<p style="font-size:26px;font-weight:800;color:{ACCL};flex:none;width:150px;line-height:1.3">안전<br>원칙</p>' + "".join(
              f'<p style="flex:1;font-size:25px;font-weight:700;color:#F7F5F1;background:#24324A;border-radius:14px;padding:16px 18px;line-height:1.35">{t}</p>'
              for t in ["로봇을 움직일지는 코드가 결정", "칸 범위 밖 · DB 미확인이면 실행 안 함", "같은 요청 반복해도 중복 실행 없음", "sLLM 설명에 없는 숫자가 있으면 버림"]),
          f"background:{INK};border-radius:22px;padding:20px 24px;display:flex;align-items:center;gap:14px", "rise 5 auto")
slide("except", 5, "신뢰성 · 막혔을 때", "잘 안 될 때는 확정 보류", ex,
      note="위 네 칸은 막혔을 때의 동작, 아래 띠는 안전 원칙입니다. AI는 더 조심하게 만들 수만 있고 더 과감하게 만들 수는 없습니다. 메인 AI가 정하는 것은 누구를 부를지와 직원에게 줄 추천뿐이고, 로봇을 움직일지는 코드가 마지막으로 확인합니다. 정지 후 자동으로 이어서 하는 기능은 아직 설계 단계입니다.")

# 28쪽 근거: 숫자마다 '무엇을 확인했나'
pr = ""
for i, (q, num, t, d, st) in enumerate([("코드를 고쳐도 기존 기능이 그대로인가?", "1,954", "자동 시험", "고칠 때마다 전부 다시 실행, PR마다 GitHub가 자동 실행", "light"),
                                        ("챗봇이 사용자 말을 알아듣나?", "459/500", "챗봇 채점", "사용자 말투 500문항 · 문항마다 맞음/틀림 · Mi:dm(11/9)", "light"),
                                        ("로봇이 확인 없이 움직이나?", "0건", "안전 위반", "시험 사례 10개에서 확인 없이 움직인 경우", "soft"),
                                        ("AI 지시문을 관리하나?", "13개", "버전 관리 프롬프트", "Langfuse에서 고치고 되돌림 · 코드 배포 없이", "light")]):
    pr += box(128 + i * 422, 290, 398, 500,
              f'<p style="font-size:26px;font-weight:700;color:{ACCD};line-height:1.35">{q}</p><div style="flex:1"></div>'
              f'<p style="font-size:84px;font-weight:800;line-height:1;color:{INK}">{num}</p><p style="font-size:32px;font-weight:800">{t}</p><p style="font-size:24px;color:{SUB};line-height:1.45">{d}</p>',
              f"{ST[st][0]};padding:36px 32px;display:flex;flex-direction:column;gap:12px", f"pop {i + 1} auto")
pr += box(128, 830, 1664, None, "".join(
    f'<p style="font-size:28px;font-weight:800;color:{INK if j % 2 == 0 else ACC}">{t}</p>' for j, t in enumerate(["실패 발견", "→", "고침", "→", "같은 시험으로 다시 확인", "→", "기록은 GitHub PR · Jira"])),
    "display:flex;gap:18px;align-items:center", "rise 5 auto")
slide("proof", 6, "근거", "고칠 때마다 다시 측정", pr,
      note="카드 위의 질문이 '무엇을 확인했나'이고, 큰 숫자가 그 결과입니다. 챗봇은 실제 모델(Mi:dm) 점수 459점을 기준으로 말합니다(규칙만 보강한 버전은 500점이지만 채점표에 맞춘 면이 있음). 자동 시험 수는 11/12 저장소 기준이며, 오류 9개는 tkinter가 없는 환경 문제로 기존과 같습니다.")

# 29쪽 범위: 두 묶음으로
two = [("확인 완료", "#2E9E5B", "#E7F5EC", [("역 키오스크 자동 촬영 + 사진 분석", "실물"), ("본인 확인 → 로봇 반환, 8칸", "실물 · 사전 녹화"),
                                           ("챗봇 대화로 검색 · 접수", "500문항 시험"), ("메인 AI가 근거 더 모으기", "가상 시연"), ("팀 DB 기록", "PostgreSQL 16")]),
       ("다음 단계", ACC, SOFT, [("직원 없는 인계 [물건 받았어요]", "실물 촬영 예정", "분실인이 꺼내고 누르는 장면까지 실물로"), ("카메라로 위치 계산해 집기", "실험 단계", "칸 자리가 어긋나도 탑뷰로 찾아 집기(Field Vision)"), ("정지 후 자동 재개", "설계 단계", "지금은 원점 복귀 뒤 다시 실행")])]
sc = ""
for i, (h, c, bgc, items) in enumerate(two):
    sc += box(128 + i * 848, 290, 816, 640,
              f'<p style="font-size:40px;font-weight:800;color:{c}">{h}</p>' + "".join(
                  f'<div style="background:{CARD};border-left:8px solid {c};border-radius:14px;padding:18px 22px;display:flex;flex-direction:column;gap:6px">'
                  f'<div style="display:flex;align-items:center;justify-content:space-between;gap:16px"><p style="font-size:31px;font-weight:700">{it[0]}</p><p style="font-size:23px;font-weight:700;color:{c};white-space:nowrap">{it[1]}</p></div>'
                  + (f'<p style="font-size:24px;color:{SUB}">{it[2]}</p>' if len(it) > 2 else "") + '</div>' for it in items),
              f"background:{bgc};border-radius:28px;padding:36px 34px;display:flex;flex-direction:column;gap:16px", f"rise {i + 1} auto")
slide("scope", 6, "범위", "확인한 것과 다음 단계", sc,
      note="왼쪽은 실물·시험·가상으로 확인한 것, 오른쪽은 아직 남은 것입니다. 오른쪽 '카메라로 위치 계산해 집기'는 순필 님이 만든 Field Vision으로, 실험 단계입니다.")

# 30쪽 배운 점: 상황 → 배운 점
ln = ""
for i, (t, sit, les) in enumerate([("AI는 말, 결정은 코드", "같은 질문에도 모델 답이 조금씩 달라짐", "실행 조건 · 기록 · 숫자는 코드가, 모델은 이해 · 설명만"),
                                   ("가상과 실물은 다름", "가상 시연은 매끄러웠지만 실물은 속도 · 카메라 노출이 다름", "실물에서 재서 가상을 맞춤(단계 3.9초 · 노출 고정)"),
                                   ("약속을 먼저 정하면 동시에 개발", "다섯 명이 비전 · 로봇 · 챗봇 · 관제탑을 나눠 맡음", "입 · 출력 약속을 먼저 정해 따로 만들고 한 번에 연결"),
                                   ("기록이 있어야 고칠 수 있음", "실패 원인을 추측만으로 찾기 어려움", "DB 상태 기록 · Langfuse 판단 기록으로 원인을 찾아 수정")]):
    ln += box(128 + (i % 2) * 848, 290 + (i // 2) * 330, 816, 306,
              f'<div style="display:flex;align-items:center;gap:18px"><p style="font-size:30px;font-weight:800;color:{INK};background:{ACCL};border-radius:50%;width:54px;height:54px;text-align:center;line-height:1.8;flex:none">{i + 1}</p>'
              f'<h3 style="font-size:40px;font-weight:800">{t}</h3></div>'
              f'<div style="display:flex;gap:16px;align-items:baseline"><p style="font-size:22px;font-weight:800;color:{SUB};background:{BG2};border-radius:999px;padding:4px 14px;flex:none">상황</p><p style="font-size:28px;color:{SUB};line-height:1.4">{sit}</p></div>'
              f'<div style="display:flex;gap:16px;align-items:baseline"><p style="font-size:22px;font-weight:800;color:#FFFFFF;background:{ACC};border-radius:999px;padding:4px 14px;flex:none">배운 점</p><p style="font-size:29px;font-weight:700;line-height:1.4">{les}</p></div>',
              f"{ST['light'][0]};padding:30px 36px;display:flex;flex-direction:column;gap:18px", f"rise {i + 1} auto")
slide("learn", 6, "배운 점", "만들면서 배운 네 가지", ln, note="네 가지 모두 '어떤 상황이었고 → 그래서 무엇을 바꿨나' 순서로 말합니다.")
print("ok")
