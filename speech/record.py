"""Explicit, bounded microphone recording; no automatic matching."""
import argparse
from pathlib import Path
import wave


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--list-devices',action='store_true')
    cli.add_argument('--device',type=int)
    cli.add_argument('--seconds',type=float,default=8)
    cli.add_argument('--sample-rate',type=int,default=16000)
    cli.add_argument('--output',type=Path,default=Path('outputs/speech/input.wav'))
    args=cli.parse_args()
    if not 1 <= args.seconds <= 60 or args.sample_rate not in (16000,44100,48000):
        cli.error('seconds must be 1..60; sample-rate 16000, 44100 or 48000')
    try:
        import sounddevice as sd
    except ImportError as error:
        cli.exit(1,f'Recording dependency missing: {error}\n')
    try:
        if args.list_devices:
            print(sd.query_devices())
            return 0
        sd.check_input_settings(device=args.device,channels=1,dtype='int16',samplerate=args.sample_rate)
        print(f'Recording microphone for {args.seconds:g}s. Speak now; Ctrl+C cancels.',flush=True)
        audio=sd.rec(round(args.seconds*args.sample_rate),samplerate=args.sample_rate,channels=1,dtype='int16',device=args.device)
        try:
            sd.wait()
        except KeyboardInterrupt:
            sd.stop()
            cli.exit(130,'Recording cancelled; no new audio saved.\n')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(args.output),'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(args.sample_rate)
            out.writeframes(audio.tobytes())
    except (OSError,ValueError,RuntimeError,sd.PortAudioError) as error:
        cli.exit(1,f'Recording failed: {error}\n')
    print('Saved: '+str(args.output.resolve()))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
