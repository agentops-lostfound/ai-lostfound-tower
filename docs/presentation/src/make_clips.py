"""발표 덱 영상 자리용 클립 만들기 (11/12) — 장면마다 위쪽 띠에 자막(장면 이름 + 실물/화면 녹화 구분), 20MB 이하 H.264"""
import json, pathlib, subprocess, sys

W = pathlib.Path(__file__).parent
U = pathlib.Path("/mnt/user-data/uploads")
A = pathlib.Path("/mnt/user-data/attachments/70df0ea4-d487-5e20-ada4-3803bad85908")
BK, LB = U / "시나리오 검정폰 중앙", U / "시나리오 빨간 립밤 중앙"
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
OUT = W / "out"; OUT.mkdir(exist_ok=True)
TMP = W / "tmp"; TMP.mkdir(exist_ok=True)
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-an", "-movflags", "+faststart"]


def run(cmd):
    o = pathlib.Path(cmd[-1])
    if o.suffix in (".mp4",) and o.exists() and o.stat().st_size > 0 and "v8_compare" not in o.name:
        return
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-1500:]); sys.exit(1)


def tf(name, text):
    p = TMP / f"{name}.txt"; p.write_text(text, encoding="utf-8"); return str(p)


def seg(name, src, title, tag, speed=1.0, W_=1280, H_=720, still=None, ss=None, to=None, hold=0):
    """한 장면 → W_xH_ 캔버스, 위 64px 띠에 자막"""
    band = 64
    fit = f"scale={W_}:{H_ - band - 12}:force_original_aspect_ratio=decrease"
    vf = (f"{fit},setsar=1,pad={W_}:{H_}:(ow-iw)/2:{band + 6}:color=0x0F1724,setpts=PTS/{speed},"
          f"drawbox=x=0:y=0:w={W_}:h={band}:color=0x16202E:t=fill,drawbox=x=0:y={band - 4}:w={W_}:h=4:color=0xF06A00:t=fill,"
          f"drawtext=fontfile={FONT}:textfile={tf(name + '_t', title)}:fontsize=30:fontcolor=0xF7F5F1:x=28:y=15,"
          f"drawtext=fontfile={FONT}:textfile={tf(name + '_g', tag)}:fontsize=24:fontcolor=0x16202E:box=1:boxcolor=0xF6A15B:boxborderw=8:x=w-tw-36:y=18")
    if hold:
        vf += f",tpad=stop_mode=clone:stop_duration={hold}"
    out = TMP / f"{name}.mp4"
    if still:
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(still), "-i", str(src), "-vf", vf, *ENC, str(out)])
    else:
        cut = (["-ss", str(ss)] if ss else []) + (["-to", str(to)] if to else [])
        run(["ffmpeg", "-y", "-v", "error", *cut, "-i", str(src), "-vf", vf, *ENC, str(out)])
    return out


def seg_pair(name, real, virt, title, tag, speed=1.5, real_to=29.2, vstretch=1.2, hold=1.5, W_=1280, H_=720):
    """실물(왼쪽 크게) + 관제탑 가상 팔(오른쪽) 나란히. 실물은 놓는 순간에서 자르고 잠깐 멈춤"""
    band = 64
    hw = (W_ - 24) // 2
    hh = H_ - band - 60
    fc = (f"[0:v]trim=0:{real_to},setpts=(PTS-STARTPTS)/{speed},crop=1400:1080:380:0,scale={hw}:{hh}:force_original_aspect_ratio=decrease,pad={hw}:{hh}:(ow-iw)/2:(oh-ih)/2:color=0x0F1724,"
          f"tpad=stop_mode=clone:stop_duration={hold},drawtext=fontfile={FONT}:text='실물 로봇':fontsize=24:fontcolor=0x16202E:box=1:boxcolor=0xF6A15B:boxborderw=6:x=12:y=12[a];"
          f"[1:v]trim=0:{real_to},setpts=(PTS-STARTPTS)/{speed},crop=590:690:285:85,scale={hw}:{hh}:force_original_aspect_ratio=decrease,pad={hw}:{hh}:(ow-iw)/2:(oh-ih)/2:color=0xF7F5F1,"
          f"tpad=stop_mode=clone:stop_duration={hold},drawtext=fontfile={FONT}:text='관제탑 가상 팔':fontsize=24:fontcolor=0xF7F5F1:box=1:boxcolor=0x16202E:boxborderw=6:x=12:y=12[b];"
          f"[a][b]hstack=inputs=2:shortest=1,pad={W_}:{H_}:(ow-iw)/2:{band + 30}:color=0x0F1724,"
          f"drawbox=x=0:y=0:w={W_}:h={band}:color=0x16202E:t=fill,drawbox=x=0:y={band - 4}:w={W_}:h=4:color=0xF06A00:t=fill,"
          f"drawtext=fontfile={FONT}:textfile={tf(name + '_t', title)}:fontsize=30:fontcolor=0xF7F5F1:x=28:y=15,"
          f"drawtext=fontfile={FONT}:textfile={tf(name + '_g', tag)}:fontsize=24:fontcolor=0x16202E:box=1:boxcolor=0xF6A15B:boxborderw=8:x=w-tw-36:y=18,fps=30")
    out = TMP / f"{name}.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(real), "-i", str(virt), "-filter_complex", fc, *ENC, str(out)])
    return out


def warp(name, src, anchors):
    """가상 영상을 구간별 배속으로 실물 시각에 맞춤. anchors = [(실물초, 가상초), ...]"""
    out = TMP / f"{name}.mp4"
    n = len(anchors) - 1
    fc = f"[0:v]split={n}" + "".join(f"[s{i}]" for i in range(n)) + ";"
    for i in range(n):
        (r0, v0), (r1, v1) = anchors[i], anchors[i + 1]
        k = (r1 - r0) / (v1 - v0)
        fc += f"[s{i}]trim=start={v0}:end={v1},setpts=(PTS-STARTPTS)*{k:.4f}[w{i}];"
    fc += "".join(f"[w{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,fps=30[o]"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", fc, "-map", "[o]", *ENC, str(out)])
    return out


LB_SYNC = [(0, 0), (3, 2), (5.5, 6), (9, 10), (16.5, 14), (20.5, 18), (22, 22), (26, 26), (28.9, 30), (29.6, 30.7)]
BK_SYNC = [(0, 0), (5, 3), (8, 7), (11, 10.5), (15, 14.5), (18, 18), (24, 23), (31, 27), (35, 31), (38, 34), (42, 39), (45, 42)]


def concat(name, parts):
    lst = TMP / f"{name}.list"
    lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    out = OUT / f"{name}.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)])
    return out


NEW_LOST = W / "lost_blur.mp4"          # 검정폰 휴대폰 웹 신고(C-…0025, 새로 찍음) · 이름 가림
LB_LOST = W / "lb_lost_blur.mp4"        # V25 립밤 신고(C-…0021) · 이름 가림
BK_L = W / "bk_L_blur.mp4"              # V18 흰 휴대폰 신고(C-…0019) 확인 답 불일치 · 이름 가림
PRE = "사전 녹화"
clips = {}
clips["v0_overview"] = concat("v0_overview", [
    seg("v0a", LB / "빨간립밤 습득.mp4", "① 습득 · 중앙역 키오스크에 빨간 립밤", "화면 녹화 · 1.5배", 1.5, to=20),
    seg("v0b", LB_LOST, "② 분실 신고 · 찾기 번호 C-…0021", "화면 녹화 · 1.5배", 1.5),
    seg("v0c", LB / "회수,본센터 키오스크.mp4", "③ 회수 · 본센터 키오스크에 같은 번호 C-…0021", "화면 녹화 · 1.5배", 1.5),
    seg_pair("v0d", LB / "R4-1.mp4", warp("lbw", LB / "가상R4-1.mp4", LB_SYNC), "④ 로봇이 R4-1 칸 립밤을 제출보관함으로", f"{PRE} · 1.5배")])
clips["v1_found"] = concat("v1_found", [
    seg("v1a", LB / "빨간립밤 습득.mp4", "습득 등록 · 두면 자동 촬영 → 장소 → 접수", "화면 녹화", to=20),
    seg("v1b", LB / "Qwen 분석결과.png", "Qwen 사진 분석 결과 · 품목 · 색 · 특징", "화면 캡처 · 다른 접수 예시", still=5)])
clips["v2_lost"] = concat("v2_lost", [seg("v2a", NEW_LOST, "휴대폰 웹 분실 신고 · 물건 설명 → 본인 확인 → 찾기 번호", "화면 녹화")])
clips["v3_return"] = concat("v3_return", [
    seg("v3a", LB / "회수,본센터 키오스크.mp4", "본센터 키오스크 · 찾기 번호 + 신분 번호 뒤 첫 자리", "화면 녹화"),
    seg_pair("v3b", LB / "R4-1.mp4", warp("lbw", LB / "가상R4-1.mp4", LB_SYNC), "로봇 · R4-1 칸에서 집기 → 제출보관함", f"{PRE} · 1.5배")])
clips["v5_agents"] = concat("v5_agents", [seg("v5a", LB / "사진 분석과정.mp4", "에이전트 흐름 · 통합 화면 (습득 한 건 예시)", "화면 녹화", ss=6)])
clips["v6_except"] = concat("v6_except", [seg("v6a", BK_L, "확인 답이 다르면 · 자동 반환하지 않고 직원 확인", "화면 녹화", hold=3)])

# 8칸 동시 재생(실물) — 4열 x 2줄, 2배속
cells = ["R1-1", "R1-2", "R2-1", "R2-2", "R3-1", "R3-2", "R4-1", "R4-2"]
ins, fl = [], []
for i, c in enumerate(cells):
    ins += ["-i", str(U / f"{c}.mp4")]
    fl.append(f"[{i}:v]setpts=PTS/2,scale=480:270,setsar=1,drawtext=fontfile={FONT}:text='{c}':fontsize=30:fontcolor=0x16202E:box=1:boxcolor=0xF6A15B:boxborderw=6:x=12:y=10[c{i}]")
grid = "".join(f"[c{i}]" for i in range(8)) + "xstack=inputs=8:layout=0_0|480_0|960_0|1440_0|0_270|480_270|960_270|1440_270:shortest=1,pad=1920:1080:0:(1080-540)/2:color=0x0F1724[g]"
cap = (f"[g]drawbox=x=0:y=0:w=1920:h=96:color=0x16202E:t=fill,drawbox=x=0:y=92:w=1920:h=4:color=0xF06A00:t=fill,"
       f"drawtext=fontfile={FONT}:textfile={tf('v7t', '8칸 동작 모음 · DB 칸 번호 → 미리 가르친 자세로 집기')}:fontsize=44:fontcolor=0xF7F5F1:x=40:y=22,"
       f"drawtext=fontfile={FONT}:textfile={tf('v7g', '실물 · 사전 녹화 · 2배')}:fontsize=34:fontcolor=0x16202E:box=1:boxcolor=0xF6A15B:boxborderw=10:x=w-tw-50:y=26,"
       "fps=30[o]")
run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", ";".join(fl) + ";" + grid + ";" + cap, "-map", "[o]",
     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(OUT / "v7_cells.mp4")])
clips["v7_cells"] = OUT / "v7_cells.mp4"

# 같은 칸 가상 · 실물 나란히 (립밤 R4-1), 1.5배속
fl2 = (f"[0:v]setpts=PTS/1.5,crop=590:690:285:85,scale=944:624:force_original_aspect_ratio=decrease,pad=952:640:(ow-iw)/2:(oh-ih)/2:color=0x0F1724,"
       f"drawtext=fontfile={FONT}:text='가상 시연':fontsize=34:fontcolor=0x16202E:box=1:boxcolor=0xF6A15B:boxborderw=8:x=20:y=16[a];"
       f"[1:v]setpts=PTS/1.5,crop=1400:1080:380:0,scale=944:624:force_original_aspect_ratio=decrease,pad=952:640:(ow-iw)/2:(oh-ih)/2:color=0x0F1724,"
       f"drawtext=fontfile={FONT}:text='실물 로봇':fontsize=34:fontcolor=0x16202E:box=1:boxcolor=0xF6A15B:boxborderw=8:x=20:y=16[b];"
       f"[a][b]hstack=inputs=2:shortest=1,pad=1920:1080:(1920-1904)/2:(1080-640)/2+40:color=0x0F1724,"
       f"drawbox=x=0:y=0:w=1920:h=96:color=0x16202E:t=fill,drawbox=x=0:y=92:w=1920:h=4:color=0xF06A00:t=fill,"
       f"drawtext=fontfile={FONT}:textfile={tf('v8t', '같은 칸(R1-1 검정폰) · 가상과 실물이 같은 동작을 같은 순간에')}:fontsize=44:fontcolor=0xF7F5F1:x=40:y=22,"
       f"drawtext=fontfile={FONT}:textfile={tf('v8g', '사전 녹화 · 1.5배')}:fontsize=34:fontcolor=0x16202E:box=1:boxcolor=0xF6A15B:boxborderw=10:x=w-tw-50:y=26,fps=30[o]")
run(["ffmpeg", "-y", "-v", "error", "-i", str(warp("bkw", BK / "회수로봇영상 가상.mp4", BK_SYNC)), "-i", str(BK / "회수로봇영상 실제.mp4"), "-filter_complex", fl2, "-map", "[o]",
     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(OUT / "v8_compare.mp4")])
clips["v8_compare"] = OUT / "v8_compare.mp4"

info = {}
for k, p in clips.items():
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)
    still = OUT / f"{k}.jpg"
    run(["ffmpeg", "-y", "-v", "error", "-ss", str(round(d * 0.35, 1)), "-i", str(p), "-frames:v", "1", "-q:v", "3", str(still)])
    info[k] = {"sec": round(d, 1), "MB": round(p.stat().st_size / 1e6, 1)}
print(json.dumps(info, ensure_ascii=False, indent=1))
