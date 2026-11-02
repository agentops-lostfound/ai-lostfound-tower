"""메인 AI 반환 흐름의 LangGraph판 — LF-14.

한줄 설명: supervisor.py 의 단계 함수(web_gate → visit_gate → locate → approach → grasp → deliver)를
LangGraph 노드로 이어, 어느 단계에서 멈췄는지 그래프로 보이게 한다.

- 단계 함수는 supervisor.py 와 같은 것을 쓴다(규칙이 두 군데로 갈라지지 않게).
- 각 노드가 '끝(True)'을 돌려주면 END 로, 아니면 다음 노드로 간다.
- 설치: .venv 에서 `pip install langgraph` (설치가 안 되면 supervisor.run_return 으로 똑같이 동작)

실행 예
    python agents/graph.py            # 가짜 부품으로 정상 반환 1건 실행
"""
from __future__ import annotations

import os
import sys
from typing import TypedDict

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.supervisor import STAGES, Ctx, Outcome, ReturnRequest, new_ctx  # noqa: E402


class FlowState(TypedDict):
    ctx: Ctx
    done: bool
    last: str


def _node(name, fn):
    def run(state: FlowState) -> dict:
        return {"done": bool(fn(state["ctx"])), "last": name}
    run.__name__ = name
    return run


def build_graph():
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as e:
        raise SystemExit("langgraph 패키지가 없습니다. .venv 에서 `pip install langgraph` 후 다시 실행하세요") from e
    g = StateGraph(FlowState)
    names = [n for n, _ in STAGES]
    for name, fn in STAGES:
        g.add_node(name, _node(name, fn))
    g.add_edge(START, names[0])
    for i, name in enumerate(names):
        nxt = names[i + 1] if i + 1 < len(names) else None
        if nxt is None:
            g.add_edge(name, END)
        else:
            g.add_conditional_edges(name, lambda s: "end" if s["done"] else "next", {"end": END, "next": nxt})
    return g.compile()


def run_return_graph(req: ReturnRequest, backend, reporter, reviewer=None, app=None) -> Outcome:
    app = app or build_graph()
    c = new_ctx(req, backend, reporter, reviewer)
    app.invoke({"ctx": c, "done": False, "last": ""})
    return c.out


if __name__ == "__main__":
    from agents.tools import MockBackend
    from discord_ops.reporter import Reporter
    feats = {"color": "검정", "shape": "반지갑", "mark": "별 모양 스티커", "visible_text": "ABC", "material": "가죽"}
    be = MockBackend(bin_items=[{"object_id": "W01", "features": feats, "center": [200, 240]}],
                     db={"A-1": {"status": "본센터 보관", "features": feats}})
    rep = Reporter()
    out = run_return_graph(ReturnRequest("DEMO", "A-1"), be, rep)
    print(f"결정: {out.decision} ({out.reason})")
    for s in out.steps:
        print("  →", s)
