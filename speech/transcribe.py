"""python -m speech.transcribe --audio description.wav"""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from .transcriber import ROOT, SpeechConfig, KoreanTranscriber


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--audio',type=Path,required=True)
    cli.add_argument('--model',choices=('small','large-v3-turbo'),default='large-v3-turbo')
    cli.add_argument('--device',choices=('cpu','cuda'),default='cuda')
    cli.add_argument('--compute-type',choices=('int8','float32','float16','int8_float16'))
    cli.add_argument('--beam-size',type=int,default=5)
    cli.add_argument('--threads',type=int,default=2)
    cli.add_argument('--offline',action='store_true')
    cli.add_argument('--no-vad',action='store_true')
    cli.add_argument('--cuda-lib-dir',type=Path,action='append',default=[])
    cli.add_argument('--output-dir',type=Path)
    args=cli.parse_args()
    try:
        if not args.audio.is_file():
            raise ValueError('Audio file does not exist')
        config=SpeechConfig(model=args.model,device=args.device,
            compute_type=args.compute_type or ('int8' if args.device=='cpu' else 'int8_float16'),
            beam_size=args.beam_size,cpu_threads=args.threads,offline=args.offline,
            vad_filter=not args.no_vad,cuda_lib_dirs=tuple(args.cuda_lib_dir))
        print('[1/2] Loading Korean STT model...',flush=True)
        with KoreanTranscriber(config) as stt:
            print('[2/2] Transcribing audio (Korean, not translation)...',flush=True)
            report=stt.transcribe(args.audio)
        output=args.output_dir or ROOT/'outputs/speech'/uuid4().hex
        output.mkdir(parents=True,exist_ok=True)
        (output/'transcript.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        (output/'transcript.txt').write_text(report['text']+'\n',encoding='utf-8')
    except (ImportError,OSError,ValueError,RuntimeError) as error:
        cli.exit(1,f'STT failed: {error}\n')
    print(json.dumps({'result':str((output/'transcript.json').resolve()),'status':report['status'],
                      'text':report['text'],'timing':report['timing']},ensure_ascii=True,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
