"""챗봇 답 진행 단계 알림 (LF-13 · 11/8 변재원)

한줄 설명: 챗봇이 답을 만드는 동안 "안내 자료 찾기 → 답 쓰기 → 근거 검사" 같은 단계에 도착할 때마다
듣는 쪽(채팅 위젯 스트림)에 단계 이름을 알려 주는 작은 알림판이다. 듣는 쪽이 없으면 아무 일도 하지 않는다.

- 알림은 contextvar(요청마다 따로 있는 값)로 전달한다. 여러 사람이 동시에 물어도 단계가 섞이지 않는다
- 알림 콜백이 실패해도 챗봇 동작에는 영향이 없다(예외를 삼킨다). 동작 로직은 바꾸지 않고 "지금 어디쯤"만 알린다
- 퍼센트는 단계별 대표값이다(실제 걸린 시간 비율이 아님). 화면은 단계 사이를 시간으로 부드럽게 채운다
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager

# 단계 → 대표 퍼센트(늘어나는 순서). 화면 글: web/chat-widget/widget.js STAGE_TEXT
STAGES = {
    "received": 5,     # 질문 받음
    "route": 12,       # 질문 종류 판단(모델 coordinator·planner, 모델이 있을 때만)
    "retrieve": 22,    # 안내 자료 찾기
    "intake": 25,      # 대화 접수(빈칸 확인·접수 창구) — 11/9
    "search": 28,      # 물건 찾기(가상 물건 목록) — 11/8 실제 단계로
    "analyze": 30,     # 관제 기록 분석(직원 화면) — 11/8
    "write": 35,       # 답 쓰기(모델)
    "check": 80,       # 근거 검사
    "rewrite": 84,     # 다시 쓰기(질문-답 맞물림 검사에 걸렸을 때 한 번)
    "recheck": 92,     # 다시 쓴 답 근거 검사
}

_listener: contextvars.ContextVar = contextvars.ContextVar("lf_chat_progress", default=None)


def notify(stage: str) -> None:
    """지금 단계를 알린다. 듣는 쪽이 없거나 알림이 실패해도 조용히 지나간다."""
    fn = _listener.get()
    if fn is None:
        return
    try:
        fn(stage)
    except Exception:      # 알림 실패가 답을 막으면 안 된다
        pass


@contextmanager
def listening(fn):
    """with listening(콜백): 안에서 부른 챗봇의 단계 알림을 콜백으로 받는다."""
    token = _listener.set(fn)
    try:
        yield
    finally:
        _listener.reset(token)


__all__ = ["STAGES", "listening", "notify"]
