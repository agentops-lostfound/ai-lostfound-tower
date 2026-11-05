"""Persistent local worker lifecycle with bounded replies and process cleanup."""
import json
from pathlib import Path
import queue
import subprocess
import threading


class ResidentDetector:
    def __init__(self, root, python, timeout=180):
        self.timeout = timeout
        self.messages = queue.Queue()
        log = root / 'outputs/resident-sequence/yolo-worker.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        self.log = log.open('a', encoding='utf-8')
        try:
            self.process = subprocess.Popen([str(python), '-u',
                str(Path(__file__).with_name('vision_cpu_worker.py')),
                '--source-root', str(root)], cwd=root, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.log, text=True,
                encoding='utf-8', bufsize=1)
        except BaseException:
            self.log.close()
            raise

        def read():
            try:
                for line in self.process.stdout:
                    self.messages.put(line)
            finally:
                self.messages.put(None)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            if not self.reply().get('ready'):
                raise RuntimeError('YOLO worker did not become ready')
        except BaseException:
            self.close()
            raise

    def reply(self):
        try:
            line = self.messages.get(timeout=self.timeout)
        except queue.Empty as exc:
            raise TimeoutError('YOLO worker timed out; see yolo-worker.log') from exc
        if line is None:
            raise RuntimeError('YOLO worker exited; see yolo-worker.log')
        return json.loads(line)

    def detect(self, image, config):
        self.process.stdin.write(json.dumps({'image': str(image),
            'config': str(config) if config else None}) + '\n')
        self.process.stdin.flush()
        result = self.reply()
        if not result.get('ok'):
            raise RuntimeError(result.get('error', 'YOLO worker failed'))
        path = Path(result['path'])
        return json.loads(path.read_text(encoding='utf-8')), path

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('{"stop":true}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        self.process.stdin.close()
        self.reader.join(timeout=2)
        self.process.stdout.close()
        self.log.close()
