"""Trace one actual CPU extraction and matching request into console + HTML."""
import argparse
import html
import json
from pathlib import Path
from time import perf_counter
from .embedding import ROOT, read_candidates
from .hybrid import HybridMatcher
from .policy import load_config
from .query_parser import QueryParser, guard_decision

LABELS = {"korean_extraction":"한국어 특징·원문 근거", "loading": "1. 추출 모델 로딩", "input": "2. 한국어 원문", "prompt": "3. 실제 모델 입력·설정",
          "model_output": "4. 실제 모델 원문 출력", "validated": "5. JSON 형식 검증·정규화",
          "comparison": "6. 수작업 기대값과 비교", "matching": "7. Qwen 후보별 비교·판정", "error": "오류"}


def render(report):
    esc = lambda value: html.escape(str(value))
    sections = []
    for event in report["events"]:
        stage, value = event["stage"], event["value"]
        body = '<pre>'+esc(json.dumps(value, ensure_ascii=False, indent=2))+'</pre>'
        if stage == "comparison":
            body = '<p>형식 검증은 내용의 정확성을 보장하지 않습니다. 아래는 사람이 미리 적은 정답 필드와의 비교입니다.</p>'+body
        if stage == "matching":
            body = '<p>원래 매칭 판정과 실험 전처리 검토 제한을 적용한 최종 판정을 분리했습니다. 점수는 확률이 아닙니다.</p>'+body
        sections.append('<details '+('' if stage == 'prompt' else 'open')+'><summary>'+esc(LABELS[stage])+f' <small>{event["seconds"]:.2f}s</small></summary>'+body+'</details>')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>한국어 전처리 실제 실행 과정</title><style>
body{font:16px/1.65 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#f3f5f8;color:#172238}h1{font-size:28px}details{background:white;padding:18px;margin:14px 0;border:1px solid #d7deea;border-radius:10px}summary{font-weight:700;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:16px;font:14px/1.6 Consolas,monospace}small{float:right;color:#59687a}.note{background:#fff0d8;padding:16px;border-radius:10px}
</style><h1>한국어 설명 → 실제 추출 → 매칭</h1><p class="note">선택한 전처리 방식의 CPU/API 실험입니다. 모델 출력에 정보 추가·누락 오류가 확인돼 자동 확정을 제한합니다. 이 화면은 실제 실행 기록이며 모델의 내부 사고 과정을 보여주는 것은 아닙니다.</p><p><a href="trace.json">전체 기록 JSON</a> · 입력 파일을 수정한 뒤 명령을 다시 실행하고 이 화면을 새로고침하세요.</p>'''+''.join(sections)+'</html>'


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--input", type=Path, default=Path(__file__).parent/'configs/query_demo.txt')
    cli.add_argument("--candidates", type=Path)
    cli.add_argument("--config", type=Path, default=Path(__file__).parent/'configs/matching.yaml')
    cli.add_argument("--output-dir", type=Path, default=ROOT/'outputs/matching/query_demo')
    cli.add_argument("--offline", action="store_true")
    cli.add_argument("--mode", choices=("direct", "translate", "korean-first"), default="korean-first")
    cli.add_argument("--translator", choices=("qwen", "opus", "deepl"), default="opus")
    args = cli.parse_args()
    started = perf_counter()
    report = {"status": "running", "events": []}
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def save():
        (args.output_dir/'trace.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (args.output_dir/'REPORT.html').write_text(render(report), encoding='utf-8')

    def event(stage, value):
        report['events'].append({'stage': stage, 'seconds': perf_counter()-started, 'value': value})
        print('\n['+LABELS[stage]+']', flush=True)
        if stage == 'prompt':
            print(f"input_tokens={value['input_tokens']}; actual prompt is saved in HTML", flush=True)
        else:
            print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)
        save()

    try:
        text = args.input.read_text(encoding='utf-8-sig').strip()
        event('loading', {'status': 'loading', 'device': 'cpu', 'offline': args.offline})
        if args.mode == 'korean-first':
            from .korean_query import KoreanFirstParser
            model=KoreanFirstParser(offline=args.offline)
        elif args.mode == 'translate':
            from .translated_query import TranslatedQueryParser, OpusQueryParser
            from .api_translation import DeepLQueryParser
            model = {'opus':OpusQueryParser,'qwen':TranslatedQueryParser,'deepl':DeepLQueryParser}[args.translator](offline=args.offline)
        else:
            model = QueryParser(offline=args.offline)
        parsed = model.parse(text, on_event=event)
        cases = json.loads((Path(__file__).parent/'configs/query_parser_cases.json').read_text(encoding='utf-8'))
        expected = next((c['expected'] for c in cases if c['text'] == text), None)
        if expected is not None:
            observed = {**parsed['features'], 'needs_clarification': parsed['needs_clarification']}
            event('comparison', {key: {'expected': value, 'actual': observed[key],
                  'equal': set(value) == set(observed[key]) if key == 'colors' else value == observed[key]}
                  for key, value in expected.items()})
        else:
            event('comparison', {'note': 'No human-labeled expected values for this input; inspect raw output manually.'})
        if args.candidates:
            candidates, skipped = read_candidates(json.loads(args.candidates.read_text(encoding='utf-8-sig')))
            ranking, decision, timing = HybridMatcher(load_config(args.config), offline=args.offline).match(candidates, parsed['features'])
            event('matching', {'policy_decision': decision, 'final_decision': guard_decision(decision, parsed),
                  'skipped': skipped, 'timing': timing,
                  'candidates': [{k: r[k] for k in ('id','features','eligible','rejection_reasons','unknown_attributes',
                                 'attribute_scores','cosine_similarity','final_score')} for r in ranking]})
        report['status'] = 'complete'
        report['parsed_query'] = parsed
        save()
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        report['status'] = 'failed'
        event('error', {'message': str(error), 'raw_output': getattr(error, 'raw_output', None)})
        return 1
    print('\nOpen: '+str((args.output_dir/'REPORT.html').resolve()), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
