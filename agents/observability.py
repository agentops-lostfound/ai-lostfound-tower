"""Langfuse 실행 기록(trace) 연결 (LF-5 · 11/7 변재원, 이건영 교수님 지시)

한줄 설명: 챗봇이 질문 하나를 처리하는 동안 어떤 에이전트가 어떤 순서로 무엇을 했는지(입력·출력·시간·모델)를
Langfuse 화면(us.cloud.langfuse.com)에 남긴다. 문제가 난 에이전트를 찾아 프롬프트를 고치는 데 쓴다.

- .env: LANGFUSE_PUBLIC_KEY · LANGFUSE_SECRET_KEY · LANGFUSE_BASE_URL(미국 서버 https://us.cloud.langfuse.com)
  셋 중 하나라도 비었거나 langfuse 패키지가 없으면 아무것도 보내지 않고 챗봇은 그대로 동작한다(LF_LANGFUSE=0 으로 끔)
- 보내기 전에 전화번호·주민번호·이메일 모양은 가린다(시연 번호라도 실제 번호가 들어올 수 있어서)
- 기록 실패는 절대 챗봇 답을 막지 않는다(모든 호출을 감싸 실패하면 조용히 넘김)
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import re
import threading

_LOCK = threading.Lock()
_CLIENT = None
_TRIED = False
_CALLBACK_ON = contextvars.ContextVar("lf_callback_on", default=False)

PRIVATE = [
    (re.compile(r"\b01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b"), "[전화번호]"),
    (re.compile(r"\b\d{6}[-\s]?[1-8]\d{6}\b"), "[주민번호]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[이메일]"),
]


def mask_text(text: str) -> str:
    for pat, rep in PRIVATE:
        text = pat.sub(rep, text)
    return text


def mask(*, data=None, **_kwargs):
    """Langfuse mask 함수: 글·목록·사전 안의 글을 모두 가린다"""
    if isinstance(data, str):
        return mask_text(data)
    if isinstance(data, list):
        return [mask(data=x) for x in data]
    if isinstance(data, tuple):
        return [mask(data=x) for x in data]
    if isinstance(data, dict):
        return {k: mask(data=v) for k, v in data.items()}
    return data


def enabled() -> bool:
    if (os.environ.get("LF_LANGFUSE") or "1").strip() == "0":
        return False
    return all((os.environ.get(k) or "").strip() for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"))


def client():
    """Langfuse 클라이언트(처음 한 번만 만든다). 쓸 수 없으면 None"""
    global _CLIENT, _TRIED
    if not enabled():
        return None
    with _LOCK:
        if _TRIED:
            return _CLIENT
        _TRIED = True
        try:
            from langfuse import Langfuse
            _CLIENT = Langfuse(mask=mask, environment=(os.environ.get("LANGFUSE_ENV") or "dev").strip() or "dev")
        except Exception:
            _CLIENT = None
        return _CLIENT


def reset_for_tests() -> None:
    global _CLIENT, _TRIED
    with _LOCK:
        _CLIENT, _TRIED = None, False


class _Noop:
    """기록을 안 할 때 대신 쓰는 빈 객체(update 등을 불러도 아무 일 없음)"""
    def update(self, **_kw):
        return self

    def __bool__(self):
        return False


NOOP = _Noop()


class _Safe:
    """실제 기록 객체를 감싸 update 실패가 챗봇을 막지 않게"""
    def __init__(self, obs):
        self._obs = obs

    def update(self, **kw):
        try:
            self._obs.update(**kw)
        except Exception:
            pass
        return self

    def __bool__(self):
        return True


@contextlib.contextmanager
def step(name: str, as_type: str = "span", **kw):
    """한 단계 기록. as_type: agent(에이전트) · retriever(문서 검색) · tool(물건 검색) · generation(모델 호출) · chain(전체)
    with step("planner", as_type="agent", input={...}) as obs: ...; obs.update(output=...)"""
    c = client()
    if c is None:
        yield NOOP
        return
    try:
        cm = c.start_as_current_observation(name=name, as_type=as_type, **kw)
        obs = cm.__enter__()
    except Exception:
        yield NOOP
        return
    try:
        yield _Safe(obs)
    except BaseException as e:
        with contextlib.suppress(Exception):
            cm.__exit__(type(e), e, e.__traceback__)
        raise
    else:
        with contextlib.suppress(Exception):
            cm.__exit__(None, None, None)


def graph_callbacks() -> list:
    """LangGraph 실행에 붙일 Langfuse 콜백(callback 방식 기록). 그래프의 칸(coordinator·planner·…) 하나하나가
    입력·출력과 함께 자동으로 기록된다. 쓸 수 없으면 빈 목록(LF_LANGFUSE_CALLBACK=0 으로 끔)"""
    if client() is None or (os.environ.get("LF_LANGFUSE_CALLBACK") or "1").strip() == "0":
        return []
    try:
        from langfuse.langchain import CallbackHandler
        return [CallbackHandler()]
    except Exception:
        return []


@contextlib.contextmanager
def callbacks_active(on: bool):
    """콜백이 칸을 기록하는 동안에는 node_step 이 같은 칸을 한 번 더 기록하지 않게"""
    token = _CALLBACK_ON.set(bool(on))
    try:
        yield
    finally:
        _CALLBACK_ON.reset(token)


@contextlib.contextmanager
def node_step(name: str, as_type: str = "agent", **kw):
    """그래프 칸 기록: 콜백이 켜져 있으면 콜백이 이미 기록하므로 건너뛰고, 아니면 step 으로 직접 기록"""
    if _CALLBACK_ON.get():
        yield NOOP
        return
    with step(name, as_type=as_type, **kw) as obs:
        yield obs


@contextlib.contextmanager
def conversation(session_id: str | None = None, trace_name: str = "lost-found-chatbot", tags: list | None = None):
    """질문 하나 = trace 하나. 같은 화면의 대화는 session_id 로 묶어 Langfuse 'Sessions' 에서 이어 볼 수 있게"""
    c = client()
    if c is None:
        yield
        return
    try:
        from langfuse import propagate_attributes
        cm = propagate_attributes(session_id=session_id, trace_name=trace_name, tags=tags or [])
        cm.__enter__()
    except Exception:
        yield
        return
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            cm.__exit__(None, None, None)


def flush() -> None:
    c = client()
    if c is not None:
        with contextlib.suppress(Exception):
            c.flush()


__all__ = ["client", "enabled", "mask", "mask_text", "step", "node_step", "graph_callbacks", "callbacks_active", "conversation", "flush", "NOOP", "reset_for_tests"]
