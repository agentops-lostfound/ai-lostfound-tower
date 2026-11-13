"""Isolated Qwen NF4 vs SmolVLM2 FP16 experiment; never writes existing outputs.

Run with .venv-smol/Scripts/python.exe -m scripts.compare_smolvlm.
One subprocess/model keeps each model loaded for all image repetitions and releases
its CUDA context before the other model starts. No automatic JSON repair or retry.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter
from datetime import datetime
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SMOL_ID = 'HuggingFaceTB/SmolVLM2-500M-Video-Instruct'
SMOL_CACHE = ROOT / '.cache' / 'smolvlm2'


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def protected_hashes():
    """Read-only evidence that original code, Qwen snapshot and results survive."""
    files = []
    for folder in ['src', 'config', 'scripts']:
        files.extend(p for p in (ROOT / folder).glob('*.py') if p.name != 'compare_smolvlm.py')
    files += list((ROOT / 'data/output').glob('*.json'))
    files += [ROOT / name for name in ['requirements.txt', 'requirements.lock.txt', '.gitignore',
                                      'README.md', 'VALIDATION.md']]
    cache = ROOT / '.cache/huggingface/models--Qwen--Qwen3-VL-2B-Instruct/snapshots'
    files += [p for p in cache.rglob('*') if p.is_file()]
    return {str(p.relative_to(ROOT)): sha256(p) for p in files if p.is_file()}


def download():
    os.environ.setdefault('HF_XET_CACHE', str(ROOT / '.cache/xet-smol'))
    from huggingface_hub import snapshot_download
    start = perf_counter()
    local = snapshot_download(SMOL_ID, cache_dir=str(SMOL_CACHE),
        allow_patterns=['*.json', '*.safetensors', '*.txt', '*.jinja', '*.model'], max_workers=1)
    print(json.dumps({'snapshot': local, 'download_or_cache_seconds': perf_counter()-start}))


def worker(args):
    import torch
    import transformers
    from config.settings import Settings
    from src.feature_extractor import PROMPT
    from src.schemas import WalletFeatures
    from src.image_preprocess import preprocess_image
    from src.json_validator import validate_response
    run = args.run_dir
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    results = run / args.worker
    results.mkdir()
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required; CPU fallback is disabled')
    torch.cuda.init()
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    load_start = perf_counter()
    if args.worker == 'qwen':
        from src.model_loader import load_model
        bundle = load_model(Settings(offline=True))
        model, processor = bundle.model, bundle.processor
        load_info = dict(bundle.metadata)
    else:
        from huggingface_hub import snapshot_download
        from transformers import AutoProcessor, AutoModelForImageTextToText
        local = snapshot_download(SMOL_ID, cache_dir=str(SMOL_CACHE), local_files_only=True,
            allow_patterns=['*.json', '*.safetensors', '*.txt', '*.jinja', '*.model'])
        processor = AutoProcessor.from_pretrained(local, local_files_only=True)
        model = AutoModelForImageTextToText.from_pretrained(local, local_files_only=True,
            dtype=torch.float16, device_map={'': 0}, attn_implementation='sdpa').eval()
        load_info = {'model_id': SMOL_ID, 'snapshot': local, 'quantization': 'none / float16'}
        if any(p.is_floating_point() and p.dtype != torch.float16 for p in model.parameters()):
            raise RuntimeError('SmolVLM floating parameters must all be FP16')
    if any(p.device.type != 'cuda' for p in model.parameters()):
        raise RuntimeError('Non-CUDA parameter placement detected')
    torch.cuda.synchronize()
    load_info.update(model_and_processor_load_seconds=perf_counter()-load_start,
        load_peak_vram_bytes=torch.cuda.max_memory_allocated(),
        gpu=torch.cuda.get_device_name(0), torch=torch.__version__,
        transformers=transformers.__version__, cuda=torch.version.cuda,
        all_parameters_cuda=True, parameter_dtypes=sorted({str(p.dtype) for p in model.parameters()}))
    write_json(results / 'load.json', load_info)
    prompt = PROMPT + json.dumps(WalletFeatures.model_json_schema())
    rows = []
    for repeat in range(1, manifest['repeats'] + 1):
        for index, item in enumerate(manifest['images']):
            record = {'model': args.worker, 'image': item['name'], 'repeat': repeat,
                'call_index': len(rows)+1, 'phase': 'first_call' if not rows else 'subsequent',
                'validation_success': False, 'visual_accuracy': 'not_reviewed',
                'features': None, 'raw_response': None, 'output_tokens': None}
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            total_start = perf_counter()
            try:
                image, sizes = preprocess_image(run / 'images' / item['name'], manifest['max_edge'])
                record.update(sizes, preprocess_seconds=perf_counter()-total_start)
                messages = [{'role': 'user', 'content': [
                    {'type': 'image', 'image': image}, {'type': 'text', 'text': prompt}]}]
                torch.cuda.synchronize()
                inference_start = perf_counter()
                inputs = processor.apply_chat_template(messages, tokenize=True,
                    add_generation_prompt=True, return_dict=True, return_tensors='pt')
                inputs = inputs.to('cuda:0', dtype=torch.float16) if args.worker == 'smol' else inputs.to('cuda:0')
                record['tensor_shapes'] = {key: list(value.shape) for key, value in inputs.items()
                                            if hasattr(value, 'shape')}
                torch.cuda.synchronize()
                gen_start = perf_counter()
                with torch.inference_mode():
                    output = model.generate(**inputs, do_sample=False, temperature=None,
                        top_p=None, top_k=None, max_new_tokens=manifest['max_new_tokens'])
                torch.cuda.synchronize()
                record['generate_seconds'] = perf_counter()-gen_start
                generated = output[:, inputs['input_ids'].shape[1]:]
                record['output_tokens'] = generated.shape[1]  # includes generated EOS
                record['token_limit_reached'] = generated.shape[1] >= manifest['max_new_tokens']
                raw = processor.batch_decode(generated, skip_special_tokens=True)[0]
                record['raw_response'] = raw
                try:
                    record['features'] = validate_response(raw).model_dump()
                    record['validation_success'] = True
                except (ValueError, TypeError) as exc:
                    record['validation_error'] = str(exc)
                torch.cuda.synchronize()
                record['inference_seconds'] = perf_counter()-inference_start
                del inputs, output, generated
            except Exception as exc:
                record['execution_error'] = f'{type(exc).__name__}: {exc}'
            finally:
                torch.cuda.synchronize()
                record.update(total_seconds=perf_counter()-total_start,
                    peak_vram_allocated_bytes=torch.cuda.max_memory_allocated(),
                    peak_vram_reserved_bytes=torch.cuda.max_memory_reserved())
                name = f'{index+1:03d}-repeat-{repeat}'
                write_json(results / (name+'.json'), record)
                if record['raw_response'] is not None:
                    (results / (name+'.raw.txt')).write_text(record['raw_response'], encoding='utf-8')
                rows.append(record)
                print(f"{args.worker} {item['name']} repeat={repeat} "
                      f"seconds={record.get('inference_seconds')} JSON={record['validation_success']}", flush=True)
    write_json(results / 'records.json', rows)


def report(run):
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    records, loads = {}, {}
    for model in ['qwen', 'smol']:
        records[model] = json.loads((run/model/'records.json').read_text(encoding='utf-8'))
        loads[model] = json.loads((run/model/'load.json').read_text(encoding='utf-8'))
    pairs = []
    for i, item in enumerate(manifest['images']):
        pairs.append({'image': item, 'visual_accuracy': 'not_reviewed',
            'historical_qwen': manifest['historical_qwen'][item['name']],
            **{m: [r for r in records[m] if r['image'] == item['name']] for m in records}})
    write_json(run/'paired-results.json', pairs)
    fields = ['model','image','repeat','phase','inference_seconds','generate_seconds','output_tokens',
              'peak_vram_allocated_bytes','peak_vram_reserved_bytes','validation_success','visual_accuracy']
    with (run/'measurements.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records['qwen']+records['smol'])
    lines = ['# Qwen / SmolVLM2 GPU comparison', '',
        'Visual accuracy: **not reviewed**. JSON validity is not visual correctness.', '',
        'Same source bytes, EXIF/RGB preprocessing, max edge, prompt/schema, greedy decoding and token cap. '
        'Model-specific internal resize/patch splitting differs. No retries or automatic JSON repair.', '',
        'Sequential model subprocesses; each model loaded once. First call is cold; subsequent calls reuse '
        'the model and CUDA allocator. This small fixed-order sample is not a general speed benchmark.', '',
        '| Model | Model+processor load (s) | Load peak allocated GiB | Format |',
        '|---|---:|---:|---|']
    for model, info in loads.items():
        lines.append(f"| {model} | {info['model_and_processor_load_seconds']:.3f} | "
                     f"{info['load_peak_vram_bytes']/2**30:.3f} | {info['quantization']} |")
    lines += ['', '| Image | Model | Repeat | Phase | Inference s | Generate s | Tokens | Peak allocated GiB | Peak reserved GiB | JSON valid |',
              '|---|---|---:|---|---:|---:|---:|---:|---:|---|']
    for row in records['qwen']+records['smol']:
        lines.append(f"| {row['image']} | {row['model']} | {row['repeat']} | {row['phase']} | "
            f"{row.get('inference_seconds',0):.3f} | {row.get('generate_seconds',0):.3f} | {row['output_tokens']} | "
            f"{row['peak_vram_allocated_bytes']/2**30:.3f} | {row['peak_vram_reserved_bytes']/2**30:.3f} | {row['validation_success']} |")
    for pair in pairs:
        lines += ['', '## '+pair['image']['name'], '', f"[Source image](images/{pair['image']['name']})", '',
                  '| Field (repeat 1) | Qwen | SmolVLM2 |', '|---|---|---|']
        for key in ['category','colors','shape','wallet_type','materials','logos_or_text',
                    'sticker_status','stickers','distinctive_features']:
            values = [json.dumps(pair[m][0]['features'].get(key),ensure_ascii=False).replace('|','\\|')
                      if pair[m][0]['validation_success'] else 'Validation failed; see raw response'
                      for m in ['qwen','smol']]
            lines.append(f'| {key} | {values[0]} | {values[1]} |')
        for model in ['qwen','smol']:
            for row in pair[model]:
                lines += ['', f"### {model}, repeat {row['repeat']}", '',
                    '```json' if row['validation_success'] else '```text',
                    json.dumps(row['features'],ensure_ascii=False,indent=2) if row['validation_success'] else
                        (row['raw_response'] or row.get('execution_error','No output')), '```']
                if not row['validation_success']:
                    lines += ['', 'Validation error: '+row.get('validation_error',row.get('execution_error',''))]
    lines += ['', '## Limits', '',
        'No human labels or visual scoring. No claims of correct logos/materials/stickers. '
        'Only the selected images/repetitions were measured; no 42-image evaluation, statistical inference, '
        'or fresh-process repeat-load distribution. Qwen uses NF4 and Smol uses FP16, so architecture and '
        'precision both differ. Token counts include EOS and tokenizers differ. Inference time includes '
        'processor, transfer, generation, decode and validation, with CUDA synchronization. '
        'Download and Python imports are excluded from model+processor load time. '
        'VRAM is PyTorch allocation/reservation, not total system GPU usage.', '',
        'Official model: https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct']
    (run/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--input', type=Path, default=ROOT/'data/input')
    parser.add_argument('--limit', type=int, default=2, help='0 = all images')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--max-edge', type=int, default=768)
    parser.add_argument('--max-new-tokens', type=int, default=512)
    parser.add_argument('--worker', choices=['qwen','smol'], help=argparse.SUPPRESS)
    parser.add_argument('--run-dir', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.download_only:
        download()
        return
    if args.worker:
        worker(args)
        return
    if args.limit < 0 or args.repeats < 2 or args.max_edge < 32 or args.max_new_tokens < 1:
        parser.error('limit >= 0, repeats >= 2, max-edge >= 32, max-new-tokens >= 1 required')
    files = sorted(p for p in args.input.iterdir() if p.is_file() and p.suffix.lower() in {'.jpg','.jpeg','.png'})
    if args.limit:
        files = files[:args.limit]
    if not files:
        parser.error('No input images')
    run = ROOT/'data/output/comparison-smolvlm'/f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
    (run/'images').mkdir(parents=True)
    baseline = protected_hashes()
    write_json(run/'protected-before.json', baseline)
    manifest = {'repeats':args.repeats,'max_edge':args.max_edge,'max_new_tokens':args.max_new_tokens,
                'images':[], 'historical_qwen':{}, 'python':sys.executable}
    for file in files:
        shutil.copy2(file,run/'images'/file.name)
        manifest['images'].append({'name':file.name,'source':str(file.resolve()),'sha256':sha256(file)})
        previous = ROOT/'data/output'/(file.name+'.json')
        manifest['historical_qwen'][file.name] = json.loads(previous.read_text(encoding='utf-8')) if previous.exists() else None
    write_json(run/'manifest.json',manifest)
    environment = dict(os.environ, HF_HUB_OFFLINE='1')
    failures = []
    for model in ['qwen','smol']:
        with (run/f'{model}-console.txt').open('w',encoding='utf-8') as console:
            result = subprocess.run([sys.executable,'-u','-m','scripts.compare_smolvlm',
                '--worker',model,'--run-dir',str(run)], cwd=ROOT, env=environment,
                stdout=console, stderr=subprocess.STDOUT)
        print(f'{model} worker exit={result.returncode}',flush=True)
        if result.returncode:
            failures.append(model)
    current = {name:sha256(ROOT/name) if (ROOT/name).is_file() else None for name in baseline}
    write_json(run/'preservation.json',{'unchanged':current==baseline,
        'changed':[name for name in baseline if baseline[name]!=current[name]]})
    if failures:
        raise RuntimeError(f'Worker failures {failures}; inspect {run}')
    report(run)
    print(f'Report: {run / "REPORT.md"}',flush=True)


if __name__ == '__main__':
    main()
