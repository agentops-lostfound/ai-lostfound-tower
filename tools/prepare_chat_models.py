"""Explicitly download approved local evaluation candidates through loopback Ollama."""
import argparse
import json
import time
import urllib.request
from agents.local_model import NoModelRedirect

CANDIDATES = ('qwen3:4b-instruct-2507-q4_K_M', 'qwen3.5:4b')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=CANDIDATES, required=True)
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoModelRedirect())
    request = urllib.request.Request('http://127.0.0.1:11434/api/pull',
        data=json.dumps({'model': args.model, 'stream': True}).encode(), headers={'Content-Type': 'application/json'})
    last = 0
    succeeded = False
    with opener.open(request, timeout=90) as response:
        for line in response:
            value = json.loads(line)
            if value.get('error'):
                raise RuntimeError(value['error'])
            succeeded = value.get('status') == 'success'
            now = time.monotonic()
            if now-last > 8 or succeeded:
                total, completed = value.get('total', 0), value.get('completed', 0)
                print(json.dumps({'model': args.model, 'status': value.get('status'),
                    'percent': round(completed/total*100, 1) if total else None}), flush=True)
                last = now
    return 0 if succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
