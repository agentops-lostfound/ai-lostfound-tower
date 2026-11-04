"""20 real CPU translations, each matched against every saved candidate group."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
from statistics import median
from .embedding import ROOT, read_candidates
from .hybrid import HybridMatcher
from .policy import load_config
from .query_parser import guard_decision
from .translated_query import TranslatedQueryParser

ALIASES = {'vpu':'db05d2b6f5a54d40837f0213969e2f55', 'phones':'262a3fbb20e1489495aa30dd55cf18e9',
           'usb':'94b94ac4e53c4314b2bfa42d96c4b34b', 'black_phone':'4560b8a53f4b4eeb96718439dc8f595a'}


def save_report(out, rows, config, runs):
    successful = [r for r in rows if 'parsed' in r]
    summary = {'completed':len(rows), 'translation_successes':len(successful),
               'exact_attribute_cases':sum(not r['attribute_mismatches'] for r in successful),
               'translation_median_seconds':median(r['parsed']['timing']['parse_seconds'] for r in successful) if successful else None,
               'primary_policy_states':dict(Counter(r['primary']['policy_decision']['status'] for r in successful)),
               'candidate_groups':len(runs), 'candidate_records':sum(len(c) for c in runs.values()),
               'matching_comparisons':sum(len(r.get('groups',[])) for r in rows)}
    summary['model']=successful[0]['parsed']['model'] if successful else None
    summary['mode']=successful[0]['parsed']['mode'] if successful else None
    summary['phrase_translation_calls']=sum(r['parsed'].get('timing',{}).get('translation_seconds',0)>0 for r in successful) if summary['mode']=='korean_first' else len(successful)
    (out/'results.json').write_text(json.dumps({'summary':summary,'config':config,'cases':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 한국어 통번역 → 코드 추출 20문장 시험','',
           '같은 모델 인스턴스를 유지하며 매 문장을 모든 기존 후보 그룹과 비교했습니다. 통번역 방식은 문장별 1회 번역 후 영어에서 조건을 추출합니다. korean_first는 한국어 규칙·사전으로 조건을 추출하고 자유 특징 구절이 있을 때만 번역합니다.',
           '주 평가 그룹과 기대 대상은 실행 전에 지정했습니다. 다른 그룹의 결과는 탐색용이며 정답률로 집계하지 않습니다. 중복 사진과 Qwen 기반 약한 정답이 포함됩니다.',
           '검사 필드 전체 일치는 category/colors/sticker_status에 한합니다. 번역·free_text의 부정·위치·정도·정보 추가는 별도로 사람이 검토해야 합니다.',
           'policy_decision은 검토 제한 전 실험 점수 판정, final_decision은 requires_review를 적용한 실제 보류 결과입니다. 점수는 확률이 아닙니다.',
           '', '```json',json.dumps(summary,ensure_ascii=False,indent=2),'```','',
           '| 번호 | 한국어 | 실제 번역 | 속성 오류 | 주 그룹 기대 | 정책 선택/상태 | 번역 초 |','|---|---|---|---|---|---|---|']
    for i,r in enumerate(rows,1):
        if 'parsed' not in r:
            lines.append(f"| {i} | {r['text']} | ERROR | {r['error']} | | | |")
            continue
        p=r['parsed']; d=r['primary']['policy_decision']
        lines.append(f"| {i} | {r['text']} | {p['translation'].replace('|','/')} | {', '.join(r['attribute_mismatches']) or '없음'} | {r['target']} | {d.get('selected_id')} / {d['status']} | {p['timing']['parse_seconds']:.2f} |")
    for i,r in enumerate(rows,1):
        lines += ['',f'## {i}. '+r['text'],'','```json',json.dumps(r,ensure_ascii=False,indent=2),'```']
    content='\n'.join(lines)
    (out/'REPORT.md').write_text(content,encoding='utf-8')
    (out/'REPORT.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><title>통번역 20문장 실험</title><style>body{max-width:1200px;margin:32px auto;padding:20px;font:15px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:20px}</style><h1>통번역 → 코드 추출 20문장 실험</h1><p><a href="REPORT.md">Markdown</a> · <a href="results.json">JSON</a></p><pre>'+html.escape(content)+'</pre></html>',encoding='utf-8')
    return summary


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('--offline',action='store_true')
    cli.add_argument('--translator',choices=('qwen','opus','deepl','korean-first'),default='korean-first')
    cli.add_argument('--output-dir',type=Path)
    cli.add_argument('--candidate-groups',type=Path,default=Path(__file__).parent/'configs/evaluation_candidates.json')
    args=cli.parse_args()
    if args.output_dir is None:
        args.output_dir = ROOT/('outputs/matching/translation_20' + ('' if args.translator=='qwen' else '_'+args.translator))
    args.output_dir.mkdir(parents=True,exist_ok=True)
    old=json.loads(args.candidate_groups.read_text(encoding='utf-8-sig'))
    runs={r['run']:r['candidates'] for r in old['runs']}
    cases=json.loads((Path(__file__).parent/'configs/translation_20_cases.json').read_text(encoding='utf-8'))
    config=load_config()
    if args.translator=='korean-first':
        from .korean_query import KoreanFirstParser
        model=KoreanFirstParser(offline=args.offline)
    elif args.translator=='deepl':
        from .api_translation import DeepLQueryParser
        model=DeepLQueryParser(offline=args.offline)
    elif args.translator=='opus':
        from .translated_query import OpusQueryParser
        model=OpusQueryParser(offline=args.offline)
    else:
        model=TranslatedQueryParser(offline=args.offline)
    matcher=HybridMatcher(config,offline=args.offline)
    rows=[]
    for case in cases:
        row=dict(case)
        try:
            p=model.parse(case['text'])
            row['parsed']=p
            row['attribute_mismatches']=[k for k,v in case['expected'].items() if
                (set(p['features'][k]) != set(v) if k=='colors' else p['features'][k]!=v)]
            groups=[]
            for run,candidates in runs.items():
                ranking,decision,timing=matcher.match(candidates,p['features'])
                groups.append({'run':run,'policy_decision':decision,'final_decision':guard_decision(decision,p),
                    'ranking':[{k:c[k] for k in ('id','features','cosine_similarity','final_score','eligible','rejection_reasons','unknown_attributes')} for c in ranking], 'timing':timing})
            row['groups']=groups
            row['primary']=next(g for g in groups if g['run']==ALIASES[case['source']])
        except (ValueError,RuntimeError) as error:
            row={'text':case['text'],'target':case['target'],'error':str(error)}
        rows.append(row)
        summary=save_report(args.output_dir,rows,config,runs)
        print(json.dumps({'completed':len(rows),'attribute_mismatches':row.get('attribute_mismatches'),
                          'translation':row.get('parsed',{}).get('translation'),'error':row.get('error')},ensure_ascii=True),flush=True)
    print(json.dumps(summary,indent=2))
    return 0 if len([r for r in rows if 'error' not in r])==len(cases) else 1


if __name__=='__main__':
    raise SystemExit(main())
