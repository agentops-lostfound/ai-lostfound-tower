"""Fixed loopback-only model HTTP client: no proxies, redirects or unlimited responses.

11/8 GPU 6GB 안전(교육원 RTX 3050): 다른 프로그램이 GPU 사용권(agents/gpu_lease.py — Qwen 사진 분석·로봇 VLA)을
쥐고 있는 동안에는 Ollama 를 CPU 로 돌린다(num_gpu=0). 사용권을 받은 쪽은 unload_local_models() 로 Ollama 모델을
그래픽카드에서 내린다. 근거·시뮬레이션: tools/gpu_budget_sim.py, docs/design/gpu_lease.md §5
"""
import json
import os
import urllib.request

BASE = 'http://127.0.0.1:11434'


class NoModelRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('로컬 모델의 다른 주소 이동은 허용하지 않습니다')


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoModelRedirect())


def gpu_taken() -> bool:
    """다른 프로그램이 GPU 사용권을 쥐고 있나(Qwen 분석·로봇 VLA 중). OLLAMA_GPU_GUARD=0 이면 확인 안 함"""
    if str(os.environ.get('OLLAMA_GPU_GUARD') or '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    try:
        from agents.gpu_lease import holder
        return holder() is not None
    except Exception:
        return False


def with_gpu_guard(payload: dict) -> dict:
    """사용권 중이면 이번 요청만 CPU 로(options.num_gpu=0) — 그래픽카드를 넘치게 하지 않음(느리지만 정상)"""
    if not gpu_taken():
        return payload
    return {**payload, 'options': {**(payload.get('options') or {}), 'num_gpu': 0}}


def unload_local_models(timeout=3.0) -> list:
    """Ollama 가 그래픽카드에 올려 둔 모델을 모두 내린다(keep_alive=0). 내린 이름 목록. 실패해도 예외 없이 []"""
    done = []
    try:
        with _opener().open(BASE + '/api/ps', timeout=timeout) as r:
            models = [m.get('name') or m.get('model') for m in (json.loads(r.read(65_536) or b'{}').get('models') or [])]
        for name in filter(None, models):
            req = urllib.request.Request(BASE + '/api/generate', data=json.dumps({'model': name, 'keep_alive': 0}).encode(),
                                         headers={'Content-Type': 'application/json'})
            with _opener().open(req, timeout=timeout) as r:
                r.read(4096)
            done.append(name)
    except Exception:
        pass
    return done


def ask_local_model(payload, timeout=40, max_bytes=32_768):
    opener = _opener()
    req = urllib.request.Request(BASE + '/api/chat', data=json.dumps(with_gpu_guard(payload)).encode(),
                                 headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('로컬 모델 응답 크기가 제한을 초과했습니다')
    try:
        return json.loads(raw)
    except RecursionError:
        raise ValueError('로컬 모델 응답의 중첩 구조가 올바르지 않습니다') from None
