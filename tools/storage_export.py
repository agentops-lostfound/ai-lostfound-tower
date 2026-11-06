"""보관함 정답지 → 비전 storage JSON 내보내기 (LF-8 · 11/6 변재원)

한줄 설명: 팀 DB 의 보관함 표(007 마이그레이션)를 읽어 김건태 run_storage_check.py 의 --storage 파일을 만든다.
관리자 로그인 없이 저장소 폴더에서 바로 쓸 수 있게 DATABASE_URL(.env)로 DB 를 직접 읽는다(읽기만 함).

사용법 (교육원 PC, 저장소 폴더, .venv, 팀 DB 켠 상태)
    python tools/storage_export.py                         # 화면에 출력
    python tools/storage_export.py --out data/storage.json # 파일로 저장 → run_storage_check.py --storage data/storage.json
    python tools/storage_export.py --demo                  # DB 없이 시연용 배치(물건 없음)로 형식만 확인

- 저장 자세가 비어 있는 칸에 물건이 있으면 경고를 출력하고 끝 코드 2 를 돌려준다(로봇 티칭 먼저)
- DATABASE_URL(비밀번호 포함)은 출력하지 않는다
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None, store=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description="보관함 정답지 → 비전 storage JSON")
    p.add_argument("--out", type=Path, default=None, help="저장할 파일 경로")
    p.add_argument("--demo", action="store_true", help="DB 없이 시연용 배치로")
    a = p.parse_args(argv)
    if store is None:
        if a.demo:
            from agents.storage import MemoryStorageStore
            store = MemoryStorageStore()
        else:
            try:
                from tools.envfile import load_env
                load_env()
            except Exception:
                pass
            dsn = os.environ.get("DATABASE_URL", "")
            if not dsn:
                print("[storage_export] DATABASE_URL 이 비어 있음(.env 확인) — 형식만 보려면 --demo", file=sys.stderr)
                return 1
            from agents.storage import PostgresStorageStore
            store = PostgresStorageStore(dsn)
    try:
        data = store.export()
    except Exception as e:
        print(f"[storage_export] 실패({type(e).__name__}) → python tools/db_migrate.py --apply 로 007 적용 여부 확인",
              file=sys.stderr)
        return 1
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
        print(f"[storage_export] 저장: {a.out} (보관 중 물건 {len(data['inventory'])}개)")
    else:
        print(text)
    for w in data["warnings"]:
        print(f"[storage_export] 경고: {w}", file=sys.stderr)
    return 2 if data["warnings"] else 0


if __name__ == "__main__":
    sys.exit(main())
