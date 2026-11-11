"""키오스크 사진 크기 확인·맞추기 (LF-18 · 11/11 변재원)

한줄 설명: 키오스크 사진의 물건 길이·폭(720 화면 픽셀)과 크기로 본 품목을 찍어 보고, 카메라 해상도·높이를 바꾼 뒤에는
'이 사진들은 ○○다'라고 알려 주면 .env TOWER_SIZE_SCALE 추천값을 계산한다. 사진을 바꾸거나 보내지 않는다.

사용법 (저장소 폴더, .venv)
    python tools/size_check.py data/photos/KIOSK-A/20261111-13*.jpg
    python tools/size_check.py data/photos/KIOSK-A/새사진*.jpg --expect 핸드크림    # 추천 TOWER_SIZE_SCALE
- 회색 펠트 위 사진만 잰다. 키오스크가 잘라 키운 사진은 옆의 같은 이름 .json(자르기 정보)이 있어야 잰다(11/11 이후 접수)
"""
from __future__ import annotations

import argparse
import glob
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REF = {"립밤": (215, 68), "핸드크림": (382, 127), "모형폰": (455, 218), "보조배터리": (420, 210)}   # 11/11 펠트 사진 기준


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="키오스크 사진 크기 확인·TOWER_SIZE_SCALE 추천")
    ap.add_argument("photos", nargs="+")
    ap.add_argument("--expect", choices=sorted(REF), help="모두 이 품목 사진이면 → 추천 TOWER_SIZE_SCALE")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    from agents.size_measure import measure, scale_from_env
    files = [f for p in args.photos for f in (glob.glob(p) or [p])]
    lengths = []
    for f in files:
        m = measure(f)
        name = Path(f).name
        if not m.get("found"):
            print(f"{name}: 못 잼 — {m.get('reason')}")
            continue
        lengths.append(m["length"])
        print(f"{name}: 길이 {m['length']} · 폭 {m['width']} → {m.get('size_group') or '맞는 품목 없음'}")
    if args.expect and lengths:
        cur = scale_from_env()
        med = statistics.median(lengths)
        rec = round(cur * REF[args.expect][0] / med, 3)
        print(f"\n{args.expect} 기준 길이 {REF[args.expect][0]} / 잰 길이(가운데값) {med:.0f} → 추천 .env TOWER_SIZE_SCALE={rec}"
              f" (지금 {cur})")
    return 0 if lengths else 1


if __name__ == "__main__":
    raise SystemExit(main())
