"""Fixed loopback-only model HTTP client: no proxies, redirects or unlimited responses."""
import json
import urllib.request


class NoModelRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('로컬 모델의 다른 주소 이동은 허용하지 않습니다')


def ask_local_model(payload, timeout=40, max_bytes=32_768):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoModelRedirect())
    req = urllib.request.Request('http://127.0.0.1:11434/api/chat', data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('로컬 모델 응답 크기가 제한을 초과했습니다')
    try:
        return json.loads(raw)
    except RecursionError:
        raise ValueError('로컬 모델 응답의 중첩 구조가 올바르지 않습니다') from None
