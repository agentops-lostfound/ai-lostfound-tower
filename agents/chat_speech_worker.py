"""Offline support STT in a killable subprocess; no credentials or audio in logs."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BoundedSpeechWorker:
    def __init__(self, timeout=75):
        self.timeout = timeout

    def transcribe(self, path):
        try:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'agents.chat_speech_worker', str(path)],
                cwd=ROOT, timeout=self.timeout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='utf-8', errors='replace')
            if result.returncode != 0 or len(result.stdout) > 16_384:
                raise ValueError()
            data = json.loads(result.stdout)
            if not isinstance(data, dict) or set(data) != {'status', 'text'}:
                raise ValueError()
            return data
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise RuntimeError('음성 처리 시간을 초과했거나 모델을 사용할 수 없습니다') from None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def main():
    # Called only with a server-created temporary WAV path, never a path from HTTP JSON.
    if len(sys.argv) != 2:
        return 1
    from speech.transcriber import KoreanTranscriber, SpeechConfig
    try:
        with KoreanTranscriber(SpeechConfig(model='small', device='cpu', compute_type='int8', offline=True)) as worker:
            result = worker.transcribe(Path(sys.argv[1]))
        text = result.get('text', '')
        if not isinstance(text, str) or len(text) > 2000:
            return 1
        print(json.dumps({'status': result['status'], 'text': text}, ensure_ascii=False))
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
