"""입력칸만 모자이크 + 칸 이름 표시 (11/12 2차)"""
import subprocess, sys, pathlib
F = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
W = pathlib.Path(__file__).parent
U = pathlib.Path("/mnt/user-data/uploads")
JOBS = {
 "lost_blur.mp4": (W / "검정폰_분실신고C_새로찍음.mp4", 10.2, 18.3, [(137, 301, 273, 56, "이름"), (137, 365, 273, 55, "신분 번호 뒤 첫 자리"), (137, 424, 268, 26, "")]),
 "lb_lost_blur.mp4": (U / "시나리오 빨간 립밤 중앙/분실신고C.mp4", 9.6, 20.3, [(129, 252, 300, 46, "이름"), (129, 302, 300, 49, "신분 번호 뒤 첫 자리"), (129, 354, 245, 22, "")]),
 "bk_L_blur.mp4": (U / "시나리오 검정폰 중앙/분실신고 L.mp4", 9.6, 19.7, [(117, 254, 298, 47, "이름"), (117, 305, 298, 48, "신분 번호 뒤 첫 자리"), (117, 359, 230, 22, "")]),
}
for out, (src, a, b, rects) in JOBS.items():
    n = len(rects)
    fc = f"[0:v]split={n + 1}[base]" + "".join(f"[s{i}]" for i in range(n)) + ";"
    cur = "base"
    for i, (x, y, w, h, lab) in enumerate(rects):
        fc += f"[s{i}]crop={w}:{h}:{x}:{y},scale={max(2, w // 14)}:{max(2, h // 10)},scale={w}:{h}:flags=neighbor"
        if lab:
            fc += f",drawbox=x=0:y=0:w={w}:h={h}:color=0x16202E@0.35:t=fill,drawtext=fontfile={F}:text='{lab} (가림)':fontsize={min(20, h // 2)}:fontcolor=white:x=(w-tw)/2:y=(h-th)/2"
        fc += f"[m{i}];[{cur}][m{i}]overlay={x}:{y}:enable='between(t,{a},{b})'[o{i}];"
        cur = f"o{i}"
    fc = fc.rstrip(";")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", fc, "-map", f"[{cur}]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(W / out)], capture_output=True, text=True)
    print(out, r.returncode, r.stderr[-400:])
