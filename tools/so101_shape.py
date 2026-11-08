"""SO-101 실제 형상 자료 만들기 (LF-29, 11/4) — /live 화면이 그리는 로봇팔 모양의 출처.

한줄 설명: SO-ARM100 공식 저장소의 MuJoCo 모델(so101_new_calib_camera.xml)과 부품 STL 을 읽어,
부품을 조각으로 나눈 뒤 조각마다 '겉모양 점'(볼록 껍질 꼭짓점 근사)만 뽑아 web/live/so101_shape.js 로 저장한다(11/8 조각 나눔).
화면은 이 점들을 관절 각도로 돌려(정방향 기구학) 위·옆에서 본 실루엣을 그린다.

- 원본: https://github.com/TheRobotStudio/SO-ARM100 (Apache-2.0) · Simulation/SO101
- 다시 만들 때만 쓴다(numpy 필요). 평소 시연에는 필요 없음
    git clone --depth 1 https://github.com/TheRobotStudio/SO-ARM100 C:\\git\\SO-ARM100
    python tools/so101_shape.py C:\\git\\SO-ARM100\\Simulation\\SO101
- --check: sim_world.so101_joints(평면 계산)로 구한 관절 각도를 이 모델의 3차원 정방향 계산에 넣어
  집게 끝이 목표 위치에 오는지 확인한다(가상 시연 각도와 화면 그림이 같은 모델인지 검사)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
import xml.etree.ElementTree as ET

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "live", "so101_shape.js")
XML_NAME = "so101_new_calib_camera.xml"      # 팔로워 + 손목 카메라
N_DIRS = 220                                  # 겉모양 점을 뽑을 방향 수(많을수록 정확, 파일 커짐)


def read_stl(path: str) -> np.ndarray:
    b = open(path, "rb").read()
    if b[:5] == b"solid" and b"facet" in b[:300]:
        return np.array([list(map(float, ln.split()[1:4])) for ln in b.decode(errors="ignore").splitlines()
                         if ln.strip().startswith("vertex")])
    n = struct.unpack("<I", b[80:84])[0]
    a = np.frombuffer(b[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    return a["v"].reshape(-1, 3).astype(float)


def quat_mat(q) -> np.ndarray:
    w, x, y, z = np.asarray(q, float) / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _vec(s, d):
    return np.array([float(t) for t in s.split()]) if s else np.array(d, float)


def load_model(model_dir: str) -> dict:
    root = ET.parse(os.path.join(model_dir, XML_NAME)).getroot()
    comp = root.find("compiler")
    meshdir = os.path.join(model_dir, comp.get("meshdir", "") if comp is not None else "")
    files = {(m.get("name") or os.path.splitext(m.get("file"))[0]): (m.get("file"), _vec(m.get("scale"), [1, 1, 1]))
             for m in root.iter("mesh")}                  # 카메라 거치대 STL 은 mm 단위라 scale=0.001 이 붙어 있다
    bodies = []

    def walk(el, parent):
        for b in el.findall("body"):
            j = b.find("joint")
            bodies.append({"name": b.get("name"), "parent": parent, "pos": _vec(b.get("pos"), [0, 0, 0]),
                           "quat": _vec(b.get("quat"), [1, 0, 0, 0]),
                           "joint": j.get("name") if j is not None else None,
                           "range": _vec(j.get("range"), [0, 0]) if j is not None and j.get("range") else None,
                           "geoms": [(g.get("mesh"), _vec(g.get("pos"), [0, 0, 0]), _vec(g.get("quat"), [1, 0, 0, 0]))
                                     for g in b.findall("geom") if g.get("class") == "visual"],
                           "sites": {s.get("name"): _vec(s.get("pos"), [0, 0, 0]) for s in b.findall("site")}})
            walk(b, len(bodies) - 1)

    walk(root.find("worldbody"), -1)
    return {"bodies": bodies, "files": files, "meshdir": meshdir}


def forward(model: dict, q: dict) -> list:
    """관절 각도(라디안) → 몸체마다 (회전행렬, 위치 m)"""
    out = []
    for b in model["bodies"]:
        r0, p0 = (np.eye(3), np.zeros(3)) if b["parent"] < 0 else out[b["parent"]]
        r = r0 @ quat_mat(b["quat"])
        p = p0 + r0 @ b["pos"]
        if b["joint"]:
            r = r @ rot_z(q.get(b["joint"], 0.0))
        out.append((r, p))
    return out


def tip_mm(model: dict, q: dict) -> np.ndarray:
    tf = forward(model, q)
    for b, (r, p) in zip(model["bodies"], tf):
        if "gripperframe" in b["sites"]:
            return (p + r @ b["sites"]["gripperframe"]) * 1000
    raise KeyError("gripperframe")


def outline_points(v: np.ndarray, n: int = N_DIRS) -> np.ndarray:
    """여러 방향으로 가장 바깥 점만 남긴다 → 어느 쪽에서 투영해도 실루엣(볼록 껍질)이 거의 같다"""
    k = np.arange(n) + 0.5
    phi, th = np.arccos(1 - 2 * k / n), math.pi * (1 + 5 ** 0.5) * k
    dirs = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)
    idx = np.unique(np.argmax(v @ dirs.T, axis=0))
    return v[idx]


# 11/8 옆모습 검증(사용자 요청 "정말 저 집게가 저런지"): 부품 하나를 볼록 껍질 하나로 그리면 고정 집게·손목이 한 덩어리
# 삼각형으로, 위팔도 실제보다 뚱뚱하게 보였다(실제 STL 삼각형 투영과 비교) → 부품을 조각(k-평균)으로 나눠 조각마다 껍질.
# 조각 경계 점은 이웃 조각에도 넣어(겹침) 틈이 생기지 않게 한다. 모터(상자 모양)는 1조각
PIECES = {"jaw": 12, "wrist_roll_follower": 14, "camera": 3, "sts3215": 1}
PIECES_DEFAULT = 10                            # 11/9 옆모습 재검증: 7→10, 겹침 1.35→1.6, 조각 방향 90→120 (STL 대비 IoU 0.95→0.965, 빠진 면적 3.1%→1.2%)
OVERLAP = 1.6                                 # 두 번째로 가까운 중심까지 거리가 가장 가까운 거리의 이 배 안이면 그 조각에도 넣음


def pieces_of(mesh: str) -> int:
    return next((k for key, k in PIECES.items() if key in mesh), PIECES_DEFAULT)


def split_pieces(v: np.ndarray, k: int, seed: int = 0, iters: int = 30) -> list:
    """k-평균으로 점을 k 조각으로 나누고, 경계 점은 이웃 조각에도 넣는다(겹침)"""
    v = np.unique(np.round(v, 6), axis=0)
    if k <= 1 or len(v) < k * 8:
        return [v]
    rng = np.random.default_rng(seed)
    c = v[rng.choice(len(v), k, replace=False)]
    for _ in range(iters):
        d = ((v[:, None, :] - c[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            if (lab == j).any():
                c[j] = v[lab == j].mean(0)
    d = np.sqrt(((v[:, None, :] - c[None]) ** 2).sum(-1))
    near = d.min(1, keepdims=True)
    member = d <= near * OVERLAP + 1e-9
    return [v[member[:, j]] for j in range(k) if member[:, j].sum() >= 4]


def kind_of(mesh: str) -> str:
    if mesh.startswith("sts3215"):
        return "motor"                      # STS3215 서보(검정)
    if "camera" in mesh and "mount" not in mesh:
        return "camera"
    return "part"                           # 3D 프린트 부품(팔로워는 흰색)


def build(model_dir: str) -> dict:
    m = load_model(model_dir)
    cache = {}
    bodies, geoms = [], []
    for i, b in enumerate(m["bodies"]):
        bodies.append({"name": b["name"], "parent": b["parent"], "pos": [round(float(t) * 1000, 2) for t in b["pos"]],
                       "quat": [round(float(t), 6) for t in b["quat"]], "joint": b["joint"],
                       "range": [round(math.degrees(t), 1) for t in b["range"]] if b["range"] is not None else None})
        for mesh, gp, gq in b["geoms"]:
            if mesh not in cache:
                f, sc = m["files"][mesh]
                cache[mesh] = read_stl(os.path.join(m["meshdir"], f)) * sc
            v = cache[mesh] @ quat_mat(gq).T + gp          # 몸체 좌표(m)
            grp = len({(g["body"], g["mesh"]) for g in geoms})   # 같은 부품 조각끼리 묶는 번호(화면이 윤곽을 한 번에 그림)
            for part in split_pieces(v, pieces_of(mesh)):
                pts = outline_points(part, 120 if pieces_of(mesh) > 1 else N_DIRS) * 1000
                geoms.append({"body": i, "mesh": mesh, "kind": kind_of(mesh), "grp": grp,
                              "pts": [[round(float(c), 1) for c in p] for p in pts]})
        if "gripperframe" in b["sites"]:
            tip = {"body": i, "pos": [round(float(t) * 1000, 2) for t in b["sites"]["gripperframe"]]}
    return {"source": "TheRobotStudio/SO-ARM100 Simulation/SO101/" + XML_NAME + " (Apache-2.0)",
            "units": "mm", "bodies": bodies, "geoms": geoms, "tip": tip}


def check(model_dir: str) -> int:
    """평면 계산(sim_world.so101_joints) ↔ 3차원 모델 정방향 계산 비교"""
    sys.path.insert(0, ROOT)
    from agents import sim_world as sw
    m = load_model(model_dir)
    s = sw.ARM_SCALE
    worst = 0.0
    pts = [(*sw.HOME_MM, sw.HOME_Z), (*sw.BASKET_MM, sw.HOVER_Z), (*sw.BASKET_MM, sw.DROP_Z)]
    pts += [(x, y, z) for x, y in sw.SLOTS_MM for z in (sw.PICK_Z, sw.HOVER_Z)]
    for x, y, z in pts:
        j = sw.so101_joints(x, y, z, 50)
        q = {k: math.radians(v) for k, v in j.items() if k != "gripper"}
        t = tip_mm(m, q) * s                                  # 화면 배율을 곱한 집게 끝(모델 좌표)
        bx, by = sw.ROBOT_BASE_MM
        pan_x = sw.SO101_PAN_X * s
        want = np.array([by - y + pan_x, bx - x, z])           # 작업대 → 모델 좌표(앞 = +X, 왼쪽 = +Y)
        err = float(np.linalg.norm(t - want))
        worst = max(worst, err)
        lim = [(k, v) for k, v in j.items() if k in sw.SO101_LIMITS and not sw.SO101_LIMITS[k][0] <= v <= sw.SO101_LIMITS[k][1]]
        flag = "" if err < 2 and not lim else "  <-- 확인"
        print(f"({x:5.0f},{y:5.0f},{z:4.0f}) 오차 {err:6.2f}mm  {j}{flag}")
    print(f"최대 오차 {worst:.2f}mm (2mm 미만이면 통과)")
    return 0 if worst < 2 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SO-101 실제 형상 자료(web/live/so101_shape.js) 만들기")
    ap.add_argument("model_dir", help="SO-ARM100 저장소의 Simulation/SO101 폴더")
    ap.add_argument("--check", action="store_true", help="가상 시연 관절 계산이 이 모델과 맞는지만 확인")
    a = ap.parse_args(argv)
    if a.check:
        return check(a.model_dir)
    data = build(a.model_dir)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("// 자동 생성: python tools/so101_shape.py <SO-ARM100>/Simulation/SO101 — 직접 고치지 말 것\n")
        f.write("// 출처: " + data["source"] + "\n")
        f.write("window.SO101_SHAPE = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    n = sum(len(g["pts"]) for g in data["geoms"])
    print(f"{OUT} 저장: 몸체 {len(data['bodies'])}개 · 부품 {len(data['geoms'])}개 · 점 {n}개 · {os.path.getsize(OUT)//1024}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
