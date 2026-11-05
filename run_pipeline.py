"""Photo/report + Korean text/audio -> inspection report. Never drives a robot."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parent


def match_report(report, text, parser, matcher, installation_config=None):
    from agents.vision_adapter import adapt_report
    from matching.inspect_sequence import inspect
    parsed = parser.parse(text)
    comparison = inspect(report, parsed, matcher)
    detections = {d['vision_id']: d for d in adapt_report(report)}
    originals = {o['id']: o for o in report.get('objects', [])}
    from vision.installation_coordinates import coordinate_chain, load_installation
    chain=coordinate_chain(report,installation_config or load_installation())
    coordinate_by_id={r['object_id']:r for r in chain['objects']}
    candidates = []
    for row in comparison['top3']:
        det = detections[row['object_id']]
        obj = originals[row['object_id']]
        candidates.append({**row, 'bbox_px': det['box'], 'center_px': det['center'],
                           'center_mm': det.get('center_mm'),
                           'features': obj.get('qwen', {}).get('features'),
                           'warnings': obj.get('qwen', {}).get('warnings', []),
                           'crop_path': obj.get('crop_path')})
        candidates[-1]['coordinates']=coordinate_by_id[row['object_id']]
    return {'parsed_query': parsed, 'matching': comparison, 'candidates': candidates,
            'coordinate_chain':chain,
            'requires_staff_confirmation': True, 'robot_authorized': False}


def save(output, result):
    output.mkdir(parents=True, exist_ok=True)
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                                allow_nan=False), encoding='utf-8')
    lines = ['# 통합 파이프라인 실행 결과', '',
             '검사 전용. 후보·좌표 표시는 로봇 실행 승인이나 정답 검증이 아닙니다.', '',
             f"실행 상태: {result['status']}", f"전체 시간: {result['total_seconds']:.2f}초", '']
    if 'error' in result:
        lines += [f"실패 단계: {result['stage']}", f"오류: {result['error']}"]
    if 'matching' in result:
        m = result['matching']
        lines += [f"한국어 입력: {result['text']}", '',
                  f"비전 상태: {result['vision_status']}",
                  f"내부 점수 판정: {m['engine_decision']}",
                  f"질의 검증 후: {m['query_policy_decision']}",
                  f"최종 판정: {m['final_decision'] or m['contract_result']}", '',
                  '| 후보 ID | 점수(확률 아님) | 중심 px | 작업대 mm | 설치 XY / 고정 접근Z mm |', '|---|---|---|---|---|']
        for c in result['candidates']:
            lines.append(f"| {c['object_id']} | {c['score']} | {c['center_px']} | {c['center_mm']} | {c['coordinates'].get('approach_xyz_mm',c['coordinates']['status'])} |")
        if not result['candidates']:
            lines += ['', '적격 후보 없음. 전체 제외 이유는 result.json의 matching.ranking 참고.']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    vision = cli.add_mutually_exclusive_group(required=True)
    vision.add_argument('--image', type=Path)
    vision.add_argument('--vision-report', type=Path)
    query = cli.add_mutually_exclusive_group(required=True)
    query.add_argument('--text')
    query.add_argument('--query-file', type=Path)
    query.add_argument('--audio', type=Path)
    cli.add_argument('--output-dir', type=Path)
    cli.add_argument('--config', type=Path, help='Vision config')
    cli.add_argument('--installation-config',type=Path,help='XY transform and fixed approach Z settings')
    cli.add_argument('--device', default='cpu', help='YOLO device')
    cli.add_argument('--qwen-python', type=Path, default=ROOT.parent/'qwen/.python/cpython-3.11.18-windows-x86_64-none/python.exe')
    cli.add_argument('--qwen-site-packages', type=Path, default=ROOT.parent/'qwen/.venv/Lib/site-packages')
    cli.add_argument('--qwen-cache-dir', type=Path, default=ROOT.parent/'qwen/.cache/huggingface')
    cli.add_argument('--speech-python', type=Path, default=ROOT.parent/'.venv-speech/Scripts/python.exe')
    cli.add_argument('--cuda-lib-dir', type=Path, default=ROOT.parent/'qwen/.venv/Lib/site-packages/torch/lib')
    args = cli.parse_args()
    output = (args.output_dir or ROOT/'outputs/pipeline'/uuid4().hex).resolve()
    output.mkdir(parents=True, exist_ok=True)
    start = perf_counter()
    result = {'status': 'running', 'stage': 'input', 'robot_authorized': False,
              'notice': 'Local inspection output may contain private observations. Do not publish raw output.'}
    exit_code = 0
    try:
        if args.audio:
            result['stage'] = 'speech'
            print('[1/3] STT (separate process; releases GPU before Qwen)', flush=True)
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            with (output/'speech.log').open('w', encoding='utf-8') as log:
                subprocess.run([str(args.speech_python.resolve()), '-m', 'speech.transcribe',
                                '--audio', str(args.audio.resolve()), '--offline',
                                '--cuda-lib-dir', str(args.cuda_lib_dir.resolve()),
                                '--output-dir', str(output/'speech')], cwd=ROOT, env=env,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            transcript = json.loads((output/'speech/transcript.json').read_text(encoding='utf-8'))
            text = transcript['text']
            result['speech'] = transcript
            result['transcript_confirmed'] = False
        else:
            text = args.query_file.read_text(encoding='utf-8-sig') if args.query_file else args.text
        if not text or not text.strip():
            raise ValueError('No usable query text; inspect speech output or provide text')
        result['text'] = text.strip()
        result['stage'] = 'vision'
        print('[2/3] Vision: existing report or YOLO/ArUco -> Qwen', flush=True)
        if args.vision_report:
            path = args.vision_report.resolve()
            report = json.loads(path.read_text(encoding='utf-8-sig'))
        else:
            from vision.sequence import run_sequence
            report, path = run_sequence(args.image.resolve(), ROOT/'qwen', args.qwen_python.resolve(),
                                        config=args.config, device=args.device,
                                        site_packages=args.qwen_site_packages.resolve(),
                                        cache_dir=args.qwen_cache_dir.resolve())
        result.update(vision_report=str(path), vision_status=report.get('sequence', {}).get('status'),
                      calibration=report.get('calibration'))
        result['stage'] = 'matching'
        print('[3/3] Korean extraction -> clause translation -> CPU matching', flush=True)
        from matching.korean_query import KoreanFirstParser
        from matching.hybrid import HybridMatcher
        from matching.policy import load_config
        from vision.installation_coordinates import load_installation
        result.update(match_report(report, result['text'], KoreanFirstParser(offline=True),
                                   HybridMatcher(load_config(), offline=True),
                                   load_installation(args.installation_config) if args.installation_config else None))
        result['status'] = 'inspection_complete' if result['vision_status']=='complete' else 'vision_incomplete'
        exit_code = 0 if result['status']=='inspection_complete' else 2
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, ImportError, subprocess.CalledProcessError) as exc:
        result.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        exit_code = 1
    except KeyboardInterrupt:
        result.update(status='cancelled')
        exit_code = 130
    finally:
        result['total_seconds'] = perf_counter()-start
        save(output, result)
    print(json.dumps({'status': result['status'], 'result': str(output/'result.json'),
                      'report': str(output/'REPORT.md'), 'robot_authorized': False}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
