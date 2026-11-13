"""Small offline Smol-only prompt experiment. Original Qwen code is read-only."""
import json
import re
from pathlib import Path
from datetime import datetime
from time import perf_counter
from uuid import uuid4
from scripts.compare_smolvlm import ROOT, SMOL_ID, SMOL_CACHE, sha256, protected_hashes, write_json
from src.schemas import WalletFeatures

PROMPT = '''Look at the wallet in this image.

Describe only what you can clearly see.

Color:
Shape:
Visible logo or text:
Sticker shape:
Sticker position:

Write one short answer per line.
Use "unknown" if unsure.
Do not guess.'''
LABELS = ['Color', 'Shape', 'Visible logo or text', 'Sticker shape', 'Sticker position']
UNKNOWN = {'unknown', 'unsure', 'not sure', 'unclear', 'n/a', 'not visible', 'cannot tell'}
ABSENT = {'none', 'no', 'absent', 'no sticker', 'no stickers'}
COLORS = {'black','white','brown','beige','tan','gray','grey','red','blue','green','yellow',
          'orange','pink','purple','gold','silver','navy','burgundy','cream'}


def parse_features(raw):
    """Only map explicit labelled evidence. No wallet/material/type inference."""
    fields = {}
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*(?:[-*]\s*)?('+ '|'.join(map(re.escape,LABELS)) +r'):\s*(.+?)\s*',
                             line, flags=re.IGNORECASE)
        if not match:
            raise ValueError(f'Unrecognized line: {line}')
        key = match[1].lower()
        if key in fields:
            raise ValueError(f'Duplicate field: {key}')
        value = match[2].strip().strip('"').rstrip('.').strip()
        if not value:
            raise ValueError(f'Empty field: {key}')
        fields[key] = value
    if set(fields) != {label.lower() for label in LABELS}:
        raise ValueError('All five labelled lines are required')
    def known(value):
        return None if value.lower() in UNKNOWN else value
    color = known(fields['color'])
    colors = [] if color is None else re.split(r'\s*(?:,|/|\band\b)\s*',color.lower())
    if any(value not in COLORS for value in colors):
        raise ValueError(f'Ambiguous/unsupported color: {color}')
    shape = known(fields['shape'])
    if shape is not None and shape.lower() in ABSENT:
        raise ValueError('Object shape cannot be absent')
    logo = known(fields['visible logo or text'])
    logos = [] if logo is None or logo.lower() in ABSENT else [logo]
    sticker_shape = known(fields['sticker shape'])
    position = known(fields['sticker position'])
    absent_shape = sticker_shape is not None and sticker_shape.lower() in ABSENT
    absent_position = position is not None and position.lower() in ABSENT
    if (absent_shape and position is not None and not absent_position) or (
            absent_position and sticker_shape is not None and not absent_shape):
        raise ValueError('Contradictory sticker evidence')
    if absent_shape or absent_position:
        status, stickers = 'absent', []
    elif sticker_shape is not None or position is not None:
        status, stickers = 'present', [{'shape':sticker_shape,'position':position}]
    else:
        status, stickers = 'unknown', []
    if not colors and shape is None and not logos and status == 'unknown':
        raise ValueError('All features unknown; not a successful extraction')
    return WalletFeatures.model_validate(dict(category='unknown',colors=colors,shape=shape,
        wallet_type=None,materials=[],logos_or_text=logos,sticker_status=status,
        stickers=stickers,distinctive_features=[])).model_dump()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--qa-only', action='store_true', help='Ask each feature in a separate short question')
    args = parser.parse_args()
    import torch
    from PIL import Image
    from huggingface_hub import snapshot_download
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from src.image_preprocess import preprocess_image
    import shutil
    previous = ROOT/'data/output/comparison-smolvlm/20261102-174231-4433b918'
    manifest = json.loads((previous/'manifest.json').read_text(encoding='utf-8'))
    run = ROOT/'data/output/smol-diagnosis'/f'{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}'
    run.mkdir(parents=True)
    baseline = protected_hashes()
    write_json(run/'protected-before.json',baseline)
    write_json(run/'previous-manifest.json',manifest)
    (run/'prompt.txt').write_text(PROMPT,encoding='utf-8')
    local = snapshot_download(SMOL_ID,cache_dir=str(SMOL_CACHE),local_files_only=True)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required')
    torch.cuda.init()
    torch.cuda.synchronize()
    started = perf_counter()
    processor = AutoProcessor.from_pretrained(local,local_files_only=True)
    model = AutoModelForImageTextToText.from_pretrained(local,local_files_only=True,
        dtype=torch.float16,device_map={'':0},attn_implementation='sdpa').eval()
    if any(p.device.type!='cuda' for p in model.parameters()):
        raise RuntimeError('GPU placement failed')
    torch.cuda.synchronize()
    write_json(run/'load.json',{'seconds':perf_counter()-started,'snapshot':local,
        'gpu':torch.cuda.get_device_name(0),'dtype':'float16','no_package_install':True})
    rows = []
    cases = []
    for repeat in [1,2]:
        for image in manifest['images']:
            source = previous/'images'/image['name']
            if sha256(source)!=image['sha256']:
                raise RuntimeError('Source image hash changed')
            cases.append((image['name'],source,PROMPT,'simple',repeat))
    cases.append(('blank-control',None,PROMPT,'blank',1))
    for image in manifest['images']:
        cases.append((image['name'],previous/'images'/image['name'],
            'Describe this image in one short sentence. Do not guess unreadable text.','caption',1))
    if args.qa_only:
        questions = {
            'Color':'What color is the wallet? Answer only the color, or unknown.',
            'Shape':'What is the outer shape of the wallet? Answer only the shape, or unknown.',
            'Visible logo or text':'What text is printed on the wallet itself? Answer only that text, or unknown.',
            'Sticker shape':'What is the shape of an attached sticker on the wallet? Answer only the shape, none, or unknown.',
            'Sticker position':'Where is an attached sticker on the wallet? Answer only the position, none, or unknown.'}
        cases = [(image['name'],previous/'images'/image['name'],question,'qa:'+label,1)
                 for image in manifest['images'] for label,question in questions.items()]
    for index,(name,source,prompt,kind,repeat) in enumerate(cases):
        image,_ = preprocess_image(source,768) if source else (Image.new('RGB',(640,640),'white'),{})
        messages = [{'role':'user','content':[{'type':'image','image':image},{'type':'text','text':prompt}]}]
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        start = perf_counter()
        inputs = processor.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,
            return_dict=True,return_tensors='pt').to('cuda',dtype=torch.float16)
        row = {'image':name,'kind':kind,'repeat':repeat,'prompt':prompt,'validation_success':False,
               'features':None,'visual_accuracy':'user_review_required',
               'tensor_shapes':{k:list(v.shape) for k,v in inputs.items() if hasattr(v,'shape')}}
        # Save template independently: verify assistant generation boundary, not prompt echo decoding.
        row['chat_template'] = processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
        token_cap = 64 if kind.startswith('qa:') or kind=='caption' else 512
        with torch.inference_mode():
            output = model.generate(**inputs,do_sample=False,temperature=None,top_p=None,top_k=None,max_new_tokens=token_cap)
        torch.cuda.synchronize()
        generated = output[:,inputs['input_ids'].shape[1]:]
        raw = processor.batch_decode(generated,skip_special_tokens=True)[0]
        row.update(raw_response=raw,output_tokens=generated.shape[1],
            token_limit_reached=generated.shape[1]>=token_cap,last_token_id=generated[0,-1].item(),
            max_new_tokens=token_cap)
        if kind in {'simple','blank'}:
            try:
                if row['token_limit_reached']:
                    raise ValueError('Token cap reached; refuse conversion of potentially truncated response')
                row['features']=parse_features(raw)
                row['validation_success']=True
            except ValueError as exc:
                row['parse_error']=str(exc)
        row.update(inference_seconds=perf_counter()-start,
            peak_vram_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_vram_reserved_bytes=torch.cuda.max_memory_reserved())
        write_json(run/f'{index+1:02d}-{kind}-repeat{repeat}.json',row)
        (run/f'{index+1:02d}-{kind}-repeat{repeat}.raw.txt').write_text(raw,encoding='utf-8')
        rows.append(row)
        write_json(run/'records.json',rows)
        print(f'{name} {kind} repeat={repeat}: {raw!r} JSON={row["validation_success"]}',flush=True)
        del inputs,output,generated
    # Preserve previous Qwen and Smol results side-by-side, without rerunning/changing Qwen.
    pairs = []
    for image in manifest['images']:
        qwen=json.loads((previous/'qwen/records.json').read_text(encoding='utf-8'))
        smol=json.loads((previous/'smol/records.json').read_text(encoding='utf-8'))
        pairs.append({'image':image,'qwen_previous':[r for r in qwen if r['image']==image['name']],
            'smol_before':[r for r in smol if r['image']==image['name']],
            'smol_after':[r for r in rows if r['image']==image['name']],
            'visual_accuracy':'user_review_required'})
        shutil.copy2(previous/'images'/image['name'],run/image['name'])
    write_json(run/'paired-results.json',pairs)
    if args.qa_only:
        conversions = []
        for image in manifest['images']:
            answers = [r for r in rows if r['image']==image['name']]
            assembled = '\n'.join(r['kind'][3:]+': '+r['raw_response'].strip() for r in answers)
            conversion = {'image':image['name'],'assembled_response':assembled,'features':None,
                          'validation_success':False,'visual_accuracy':'user_review_required',
                          'total_inference_seconds':sum(r['inference_seconds'] for r in answers)}
            try:
                if any(r['token_limit_reached'] for r in answers):
                    raise ValueError('One or more answers hit token cap; conversion refused')
                conversion['features'] = parse_features(assembled)
                conversion['validation_success'] = True
            except ValueError as exc:
                conversion['parse_error'] = str(exc)
            conversions.append(conversion)
        write_json(run/'qa-conversions.json',conversions)
    changed=[name for name,digest in baseline.items() if not (ROOT/name).is_file() or sha256(ROOT/name)!=digest]
    write_json(run/'preservation.json',{'unchanged':not changed,'changed':changed})
    print(f'Results: {run}',flush=True)


if __name__=='__main__':
    main()
