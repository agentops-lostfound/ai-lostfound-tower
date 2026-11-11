"""시연 데이터 SQL 만들기 — evaluation/test_cases.json 의 물건 W01~W07 을 접수 번호 A-W01~A-W07 로 넣는다.

한줄 설명: 진짜 접수 데이터가 없을 때 관제탑·웹이 같은 물건으로 시험할 수 있게 DB 시연 데이터를 만든다.
    python center/make_demo_seed.py > center/seed_demo.sql
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from agents.contracts import PRIVATE_FIELDS  # noqa: E402


def q(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def build() -> str:
    with open(os.path.join(ROOT, "evaluation", "test_cases.json"), encoding="utf-8") as f:
        spec = json.load(f)
    lines = ["-- 시연 데이터(자동 생성: python center/make_demo_seed.py). 진짜 접수가 생기면 쓰지 않는다",
             "INSERT INTO machine VALUES ('KIOSK-A', 'kiosk', '1호선', '중앙', FALSE),",
             "                           ('KIOSK-C', 'kiosk', '1호선', '초량', TRUE),",
             "                           ('CENTER', 'center', '1호선', '부산', FALSE)",
             "ON CONFLICT (machine_id) DO NOTHING;"]
    for oid, feats in spec["objects"].items():
        pub = {k: v for k, v in feats.items() if k not in PRIVATE_FIELDS}
        prv = {k: v for k, v in feats.items() if k in PRIVATE_FIELDS}
        lines.append(
            "INSERT INTO item (item_id, machine_id, place_text, status, category, features, private_features, object_id) VALUES ("
            f"{q('A-' + oid)}, 'KIOSK-A', '시연 장소', '본센터 보관', '지갑', "
            f"{q(json.dumps(pub, ensure_ascii=False))}::jsonb, {q(json.dumps(prv, ensure_ascii=False))}::jsonb, {q(oid)}) "
            "ON CONFLICT (item_id) DO NOTHING;")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(build())
