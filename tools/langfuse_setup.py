"""Langfuse 연결 확인 · 프롬프트 처음 올리기 (LF-5 · 11/7 변재원)

한줄 설명: .env 의 Langfuse 키로 접속이 되는지 확인하고, 챗봇 에이전트 프롬프트(agents/prompts.py 기본값)를
Langfuse 'Prompts' 화면에 올린다. 그 뒤로는 Langfuse 화면에서 프롬프트를 고치면 챗봇이 1분 안에 새 버전을 쓴다.

사용법 (저장소 폴더, .venv)
    python tools/langfuse_setup.py --check            # 접속 확인(키 값은 출력하지 않음)
    python tools/langfuse_setup.py --push-prompts     # 없는 프롬프트만 올림(라벨 production)
    python tools/langfuse_setup.py --push-prompts --force   # 코드 기본값을 새 버전으로 다시 올림(화면에서 고친 내용 위에 덮어씀 — 주의)
    python tools/langfuse_setup.py --test-trace       # 시험 기록 하나를 보내 Traces 화면에 보이는지 확인
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Langfuse 연결 확인·프롬프트 올리기")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--push-prompts", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--test-trace", action="store_true")
    args = ap.parse_args(argv)
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    from agents import observability, prompts
    missing = [k for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL") if not (os.environ.get(k) or "").strip()]
    if missing:
        print("다음 값이 .env 에 없습니다: " + ", ".join(missing))
        return 2
    try:
        import langfuse  # noqa: F401
    except ImportError:
        print("langfuse 패키지가 없습니다 → pip install langfuse")
        return 2
    c = observability.client()
    if c is None:
        print("Langfuse 클라이언트를 만들지 못했습니다(LF_LANGFUSE=0 인지 확인)")
        return 2
    print(f"접속 주소: {os.environ['LANGFUSE_BASE_URL'].strip()}")
    try:
        ok = c.auth_check()
    except Exception as e:
        print(f"접속 실패({type(e).__name__}) — 키·주소(미국 서버면 https://us.cloud.langfuse.com)를 확인하세요")
        return 1
    print("키 확인: " + ("OK" if ok else "실패"))
    if not ok:
        return 1
    if args.push_prompts:
        for name, text in prompts.DEFAULTS.items():
            exists = True
            try:
                c.get_prompt(name, label="production", type="text", max_retries=0, fetch_timeout_seconds=5, cache_ttl_seconds=0)
            except Exception:
                exists = False
            if exists and not args.force:
                print(f"  {name}: 이미 있음(건너뜀)")
                continue
            c.create_prompt(name=name, prompt=text, labels=["production"], type="text",
                            commit_message="agents/prompts.py 기본값(tools/langfuse_setup.py)")
            print(f"  {name}: 올림{'(새 버전)' if exists else ''}")
    if args.test_trace:
        with observability.conversation(session_id="setup-check-0001", tags=["setup"]):
            with observability.step("langfuse-setup-check", as_type="chain", input={"question": "연결 시험 010-1234-5678"}) as obs:
                obs.update(output={"answer": "연결 시험 기록(전화번호 모양은 가려져야 함)"})
        observability.flush()
        print("시험 기록을 보냈습니다 → Langfuse Traces 화면에서 'langfuse-setup-check' 를 찾아보세요(전화번호가 [전화번호]로 보이면 정상)")
    if not (args.push_prompts or args.test_trace):
        print("다음: --push-prompts 로 프롬프트를 올리고, --test-trace 로 기록이 보이는지 확인하세요")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
