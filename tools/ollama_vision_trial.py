"""Local Ollama comparison using upstream preprocessing, prompt and validation."""
import argparse
import base64
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
from time import perf_counter
import urllib.error
import urllib.request
from uuid import uuid4


def chat(payload, timeout):
    request = urllib.request.Request('http://127.0.0.1:11434/api/chat',
        data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    # Local loopback only; do not send photos through the session HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = json.load(response)
    if data.get('error'):
        raise RuntimeError(data['error'])
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--max-edge', type=int, default=384)
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    root, image = args.source_root.resolve(), args.image.resolve()
    if args.repeat < 1 or args.max_edge < 32 or not image.is_file():
        parser.error('Check image, repeat >= 1 and max-edge >= 32')
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'qwen'))
    from src.image_preprocess import preprocess_image
    from vision.item_features import PROMPT, OUTPUT_TEMPLATE, validate_response
    from config.settings import Settings
    settings = Settings()
    model = 'qwen3-vl:2b-instruct'
    output = root / 'outputs/ollama-trial' / uuid4().hex
    output.mkdir(parents=True)
    records = []
    print('Local Ollama only. First image includes cold model loading; '
          'compare subsequent requests separately. Output:', output, flush=True)
    for index in range(args.repeat):
        started = perf_counter()
        prepared, sizes = preprocess_image(image, args.max_edge)
        buffer = BytesIO()
        prepared.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
        prompt = PROMPT + json.dumps(OUTPUT_TEMPLATE)
        record = {'request': index + 1, 'timestamp': datetime.now(timezone.utc).isoformat(),
                  'model': model, 'max_edge': args.max_edge, **sizes,
                  'preprocess_and_encode_seconds': perf_counter() - started,
                  'validation_success': False, 'attempts': []}
        last_error = None
        try:
            for attempt in range(settings.retries + 1):
                t0 = perf_counter()
                response = chat({'model': model, 'stream': False, 'keep_alive': '5m',
                    'messages': [{'role': 'user', 'content': prompt, 'images': [encoded]}],
                    'options': {'temperature': 0, 'top_k': 1, 'top_p': 1,
                                'num_predict': settings.max_new_tokens, 'num_ctx': 4096}}, 180)
                raw = response.get('message', {}).get('content', '')
                timing = {'attempt': attempt + 1, 'http_seconds': perf_counter() - t0,
                    'done_reason': response.get('done_reason'),
                    'input_tokens': response.get('prompt_eval_count'),
                    'output_tokens': response.get('eval_count')}
                for field in ('total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration'):
                    if isinstance(response.get(field), (float, int)):
                        timing[field.replace('_duration', '_seconds')] = response[field] / 1e9
                record['attempts'].append(timing)
                try:
                    record['features'] = validate_response(raw)
                except (ValueError, TypeError) as exc:
                    last_error = str(exc)
                    timing['validation_error'] = last_error
                    (output / f'invalid-{index+1}-{attempt+1}.json').write_text(
                        json.dumps({'raw_response': raw, 'error': last_error}, ensure_ascii=False, indent=2),
                        encoding='utf-8')
                    prompt = PROMPT + json.dumps(OUTPUT_TEMPLATE) + (
                        '\nPrevious output failed validation. Produce complete valid JSON. Error: ' + last_error)
                    continue
                record['validation_success'] = True
                break
            if not record['validation_success']:
                record['error'] = last_error
        except (OSError, ValueError, RuntimeError) as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
        record['request_seconds'] = perf_counter() - started
        records.append(record)
        (output / 'summary.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)
        if not record['validation_success']:
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
