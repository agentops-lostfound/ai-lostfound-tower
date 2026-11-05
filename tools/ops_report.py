"""관제 분석·보고 에이전트 실행 (LF-5, 11/5) — agents/ops_analyst.py

한줄 설명: 관제탑 기록을 읽어 "왜 실패했는지·로봇은 괜찮은지"를 한국어 보고서로 써 준다(LangManus 구조, LangGraph).

사용법 (저장소 폴더, .venv 켠 상태, 관제탑 켜진 상태)
    python tools/ops_report.py "오늘 반환 실패 원인 알려줘"
    python tools/ops_report.py "로봇팔 문제 요약해줘" --model qwen3-vl:2b-instruct   # 로컬 Ollama 로 문장 다듬기
    python tools/ops_report.py "전체 현황" --tower http://127.0.0.1:8100 --save data/reports/ops.md
    python tools/ops_report.py "전체 현황" --from-json 기록.json        # 관제탑 없이 저장해 둔 기록으로
- 모델 이름은 .env OPS_ANALYST_MODEL 로도 정할 수 있다(비우면 템플릿 보고서)
- 보고서에는 사례 번호·물건 번호 외 개인정보가 들어가지 않는다
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FileReader:
    def __init__(self, path):
        self.path = Path(path)

    def collect(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="관제 분석·보고 에이전트")
    ap.add_argument("question", help='예: "오늘 반환 실패 원인 알려줘"')
    ap.add_argument("--tower", default=os.environ.get("TOWER_URL") or "http://127.0.0.1:8100")
    ap.add_argument("--model", default=os.environ.get("OPS_ANALYST_MODEL") or None)
    ap.add_argument("--from-json", help="관제탑 대신 읽을 기록 파일({returns, live})")
    ap.add_argument("--save", help="보고서를 저장할 .md 경로")
    a = ap.parse_args(argv)
    from agents.ops_analyst import OpsAnalyst, TowerReader
    reader = FileReader(a.from_json) if a.from_json else TowerReader(a.tower)
    out = OpsAnalyst(reader=reader, model=a.model).run(a.question)
    print(out["report"])
    if out["accepted"]:
        print(f"\n[초점: {out['focus']} · LLM 사용: {', '.join(out['used_llm']) or '없음(템플릿)'}]", file=sys.stderr)
    if a.save and out["accepted"]:
        p = Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out["report"] + "\n", encoding="utf-8")
        print(f"[저장: {p}]", file=sys.stderr)
    return 0 if out["accepted"] else 2


if __name__ == "__main__":
    sys.exit(main())
