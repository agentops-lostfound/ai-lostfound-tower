"""Langfuse 실행 기록(trace) 연결 (LF-5 · 11/7 변재원)

한줄 설명: 챗봇이 질문 하나를 처리하는 동안 어떤 에이전트가 어떤 순서로 무엇을 했는지(입력·출력·시간·모델)를
Langfuse 화면(us.cloud.langfuse.com)에 남긴다. 문제가 난 에이전트를 찾아 프롬프트를 고치는 데 쓴다.

- .env: LANGFUSE_PUBLIC_KEY · LANGFUSE_SECRET_KEY · LANGFUSE_BASE_URL(미국 서버 https://us.cloud.langfuse.com)
  셋 중 하나라도 비었거나 langfuse 패키지가 없으면 아무것도 보내지 않고 챗봇은 그대로 동작한다(LF_LANGFUSE=0 으로 끔)
- 보내기 전에 전화번호·주민번호·이메일 모양은 가린다(시연 번호라도 실제 번호가 들어올 수 있어서)
- 기록 실패는 절대 챗봇 답을 막지 않는다(모든 호출을 감싸 실패하면 조용히 넘김)
- 11/10 화면용 리스너: set_listener(이름, 함수) 로 등록하면 같은 단계의 시작/끝을 그 함수에도 알린다(Langfuse 가 꺼져 있어도).
  통합 시연 화면(/showcase)이 에이전트 흐름을 그리는 데 쓴다. 보내는 값은 가린 뒤 짧게 자른 요약뿐이다
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import os
import re
import threading
import time

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
            env = (os.environ.get("LANGFUSE_ENV") or "dev").strip() or "dev"
            try:      # 11/9 대화가 바로바로 보이게: 1초마다 보냄(기본 5초)
                _CLIENT = Langfuse(mask=mask, environment=env, flush_interval=float(os.environ.get("LANGFUSE_FLUSH_INTERVAL") or 1))
            except TypeError:
                _CLIENT = Langfuse(mask=mask, environment=env)
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


# ---------- 11/10 화면용 리스너(통합 시연 화면의 에이전트 흐름) ----------
_LISTENERS: dict[str, object] = {}
_TRACE = contextvars.ContextVar("lf_local_trace", default=None)      # 지금 질문 하나(trace)의 {id, name, session}
_STACK = contextvars.ContextVar("lf_local_stack", default=())        # 지금 열려 있는 칸 이름들(부모 → 자식)
_TRACE_NO = [0]
BRIEF_LIMIT = 280


def set_listener(key: str, fn) -> None:
    """화면용 리스너 등록(같은 이름이면 바꿈, fn=None 이면 뺌). fn(dict) — 실패해도 챗봇을 막지 않는다"""
    with _LOCK:
        if fn is None:
            _LISTENERS.pop(key, None)
        else:
            _LISTENERS[key] = fn


def _one(value, limit: int = 110) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def brief(value, limit: int = BRIEF_LIMIT) -> str:
    """화면에 낼 짧은 한 줄: {칸: 값} 은 '칸: 값 · 칸: 값' 으로 → 개인정보 모양을 가리고 → 자른다"""
    if value is None:
        return ""
    if isinstance(value, dict):
        text = " · ".join(f"{k}: {_one(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    else:
        text = _one(value, limit)
    text = mask_text(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _emit(data: dict) -> None:
    for fn in list(_LISTENERS.values()):
        try:
            fn(data)
        except Exception:
            pass


class _Tap:
    """Langfuse 기록 객체(또는 빈 객체)를 감싸 update 값을 화면용으로도 기억한다. 참/거짓은 안쪽 객체를 따른다"""
    def __init__(self, name: str, as_type: str, kw: dict):
        self.inner = NOOP
        self.name, self.as_type = name, as_type
        self.model = kw.get("model")
        self.input = None if as_type == "generation" else kw.get("input")     # 모델 호출의 입력(프롬프트 전문)은 화면에 안 냄
        self.output, self.level, self.message = None, None, None
        self.started = time.perf_counter()
        tr = _TRACE.get() or {}
        stack = _STACK.get()
        self.base = {"trace": tr.get("id"), "trace_name": tr.get("name"), "name": name, "type": as_type,
                     "parent": stack[-1] if stack else None, "role": ROLES.get(name, "")}
        self._token = _STACK.set(stack + (name,))
        _emit({**self.base, "kind": "start", "input": brief(self.input), "model": self.model})

    def update(self, **kw):
        if "output" in kw:
            self.output = kw["output"]
        if kw.get("level"):
            self.level, self.message = kw.get("level"), kw.get("status_message")
        self.inner.update(**kw)
        return self

    def __bool__(self):
        return bool(self.inner)

    def end(self, error: str | None = None) -> None:
        with contextlib.suppress(Exception):
            _STACK.reset(self._token)
        _emit({**self.base, "kind": "end", "output": brief(self.output), "model": self.model,
               "ms": int((time.perf_counter() - self.started) * 1000),
               "error": error or (f"{self.level}: {self.message}" if self.level else None)})


@contextlib.contextmanager
def _tapped(inner_cm, name: str, as_type: str, kw: dict):
    """안쪽 기록(Langfuse 또는 없음)을 그대로 하면서 리스너에도 시작/끝을 알린다. 리스너가 없으면 안쪽 그대로"""
    if not _LISTENERS:
        with inner_cm as obs:
            yield obs
        return
    tap = _Tap(name, as_type, kw)
    try:
        with inner_cm as obs:
            tap.inner = obs
            yield tap
    except BaseException as e:
        tap.end(error=type(e).__name__)
        raise
    else:
        tap.end()


def step(name: str, as_type: str = "span", **kw):
    """한 단계 기록. as_type: agent(에이전트) · retriever(문서 검색) · tool(물건 검색) · generation(모델 호출) · chain(전체)
    with step("planner", as_type="agent", input={...}) as obs: ...; obs.update(output=...)"""
    return _tapped(_lf_step(name, as_type, **kw), name, as_type, kw)


@contextlib.contextmanager
def _lf_step(name: str, as_type: str = "span", **kw):
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


def router(fn, name: str):
    """LangGraph 조건 연결 함수에 이름을 붙이고 Langfuse 에서 DEBUG 단계로 기록되게(langsmith:hidden 태그) 감싼다.
    11/9 검토 의견(나무가 어색함): 'route_next_worker'·'RunnableCallable' 같은 칸이 에이전트 사이마다 끼어 있었다"""
    try:
        from langchain_core.runnables import RunnableLambda
        return RunnableLambda(fn, name=name).with_config(tags=["langsmith:hidden"], run_name=name)
    except Exception:
        return fn


# 칸 이름 → 역할(Langfuse 칸 metadata 'role' 에 남김: 나무만 보고도 무슨 에이전트인지 알게)
ROLES = {
    "coordinator": "agent · 접수 담당(말 분류)", "planner": "agent · 계획 담당(일꾼 순서)",
    "supervisor": "agent · 감독(일꾼 결과를 보고 다음 행동 판단)", "researcher": "retriever+generation · 안내 문서 답",
    "item_search": "tool · 분실물 후보 검색(읽기 전용)", "intake": "agent · 대화 접수(분실 접수·습득 신고)",
    "ops_analyst": "agent · 관제 분석 팀(직원 전용)", "reporter": "agent · 결과 정리",
    # 관제탑 메인 AI 묶음(agents/tower_brain.py)
    "main_ai": "agent · 관제탑 메인 AI(다음에 누구에게 물을지 판단)", "matching_agent": "tool · 매칭 에이전트(탑뷰 물건 고르기)",
    "storage_agent": "tool · 보관 칸 에이전트(칸 위치 확인)", "vision_agent": "tool · 비전 에이전트(다시 보기)",
}


class _Current:
    """콜백이 만든 지금 칸(span)에 metadata 로 판단·요약을 덧붙인다(출력은 콜백이 칸의 반환값으로 기록)"""
    def __init__(self, c, name):
        self._c, self._name = c, name

    def update(self, **kw):
        meta = {"role": ROLES.get(self._name, "agent")}
        if "output" in kw:
            meta["detail"] = kw["output"]
        try:
            self._c.update_current_span(metadata=meta)
        except Exception:
            pass
        return self

    def __bool__(self):
        return True


def node_step(name: str, as_type: str = "agent", **kw):
    """그래프 칸 기록: 콜백이 켜져 있으면 콜백이 칸을 만들므로 그 칸에 역할·판단(metadata)만 덧붙이고, 아니면 step 으로 직접 기록"""
    return _tapped(_lf_node(name, as_type, **kw), name, as_type, kw)


@contextlib.contextmanager
def _lf_node(name: str, as_type: str = "agent", **kw):
    if _CALLBACK_ON.get():
        c = client()
        cur = _Current(c, name) if c is not None else NOOP
        cur.update()
        yield cur
        return
    with _lf_step(name, as_type=as_type, **kw) as obs:
        yield obs


@contextlib.contextmanager
def conversation(session_id: str | None = None, trace_name: str = "lost-found-chatbot", tags: list | None = None):
    """질문 하나 = trace 하나. 같은 화면의 대화는 session_id 로 묶어 Langfuse 'Sessions' 에서 이어 볼 수 있게"""
    if not _LISTENERS:
        with _lf_conversation(session_id, trace_name, tags):
            yield
        return
    with _LOCK:
        _TRACE_NO[0] += 1
        tid = f"Q{_TRACE_NO[0]:04d}"
    info = {"id": tid, "name": trace_name, "session": session_id}
    token = _TRACE.set(info)
    started = time.perf_counter()
    _emit({"kind": "trace_start", "trace": tid, "trace_name": trace_name, "name": trace_name, "type": "trace",
           "tags": list(tags or []), "langfuse": enabled()})
    try:
        with _lf_conversation(session_id, trace_name, tags):
            yield
    finally:
        _emit({"kind": "trace_end", "trace": tid, "trace_name": trace_name, "name": trace_name, "type": "trace",
               "ms": int((time.perf_counter() - started) * 1000)})
        with contextlib.suppress(Exception):
            _TRACE.reset(token)


@contextlib.contextmanager
def _lf_conversation(session_id: str | None = None, trace_name: str = "lost-found-chatbot", tags: list | None = None):
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


def flush_soon() -> None:
    """11/9 질문 하나가 끝나면 뒤에서 바로 보냄(답을 늦추지 않게 별도 실행 줄). 기록이 꺼져 있으면 아무 일 없음"""
    if client() is None:
        return
    import threading
    threading.Thread(target=flush, daemon=True, name="langfuse-flush").start()


def status() -> dict:
    """/chat/health 용: 기록이 켜졌는지와 꺼진 이유(키 값은 절대 넣지 않음)"""
    if (os.environ.get("LF_LANGFUSE") or "1").strip() == "0":
        return {"enabled": False, "reason": "LF_LANGFUSE=0(끔)"}
    missing = [k for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL") if not (os.environ.get(k) or "").strip()]
    if missing:
        return {"enabled": False, "reason": ".env 에 없음: " + ", ".join(missing)}
    try:
        import langfuse  # noqa: F401
    except ImportError:
        return {"enabled": False, "reason": "langfuse 패키지 없음(pip install -r agents/requirements.txt)"}
    if client() is None:
        return {"enabled": False, "reason": "클라이언트를 만들지 못함"}
    return {"enabled": True, "reason": "", "callback": bool(graph_callbacks()),
            "host": (os.environ.get("LANGFUSE_BASE_URL") or "").strip()}


__all__ = ["client", "enabled", "mask", "mask_text", "step", "node_step", "graph_callbacks", "callbacks_active", "conversation", "flush",
           "flush_soon", "status", "router", "ROLES", "NOOP", "reset_for_tests"]
