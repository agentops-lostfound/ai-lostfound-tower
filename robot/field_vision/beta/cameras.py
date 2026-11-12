import io
import json
import threading
import time
from urllib.parse import urlparse, quote
from uuid import UUID

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw
from .overlay import LiveOverlay
from .video_devices import resolve_device, BRIDGE_URL


def jpeg(image, quality=80):
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=quality)
    return out.getvalue()


class Camera:
    def __init__(self, key, config, log):
        self.key, self.config, self.log = key, dict(config), log
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.input_size = None
        self.device_index = None
        self.jpeg = None
        self.display_jpeg = None
        self.latest_image = None
        self.overlay=LiveOverlay()
        self.seq = 0
        self.last = 0
        self.fps = 0
        self.fps_at = time.time()
        self.fps_count = 0
        self.error = '연결 대기'
        self.kind = 'live'
        self.flat_frames = 0
        self.signal_warning = None
        self.thread = threading.Thread(target=self.run, daemon=True, name='camera-'+key)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)

    def publish(self, image):
        # Bound source resolution; camera capture is independent of the GPU worker.
        input_size = image.size
        image = image.convert('RGB')
        image.thumbnail((1280, 960))
        flat=float(np.asarray(image.resize((32,24))).std())<1
        self.flat_frames=self.flat_frames+1 if flat else 0
        previous=self.signal_warning
        self.signal_warning='거의 단색인 영상입니다. 렌즈·카메라 장치 상태를 확인하세요.' if self.flat_frames>=10 else None
        if self.signal_warning and not previous:
            self.log('warning','camera',f'{self.config["name"]}: {self.signal_warning}')
        self.overlay.update(image)
        data = jpeg(image)
        display=jpeg(self.overlay.draw(image)) if self.overlay.visible() else data
        with self.lock:
            now = time.time()
            self.fps_count+=1
            if now-self.fps_at>=1:
                self.fps=self.fps_count/(now-self.fps_at)
                self.fps_at=now;self.fps_count=0
            self.jpeg, self.last = data, now
            self.display_jpeg=display
            self.input_size=input_size
            self.latest_image=image.copy()
            self.seq += 1
            self.error = None

    def snapshot(self):
        with self.lock:
            if self.jpeg is None or (self.kind == 'live' and time.time()-self.last > 4):
                raise ValueError(f'{self.config["name"]}: 최신 카메라 프레임이 없습니다.')
            return Image.open(io.BytesIO(self.jpeg)).convert('RGB'), self.seq, self.last

    def state(self):
        with self.lock:
            age = time.time()-self.last if self.last else None
            return dict(**self.config, id=self.key, connected=self.jpeg is not None and (self.kind=='sample' or age < 4),
                        frame_id=self.seq, last_frame=self.last, age=age, fps=round(self.fps, 1), error=self.error, kind=self.kind,
                        input_size=self.input_size, frame_size=self.latest_image.size if self.latest_image else None,
                        device_index=self.device_index,signal_warning=self.signal_warning,overlay=self.overlay.visible())

    def crop(self, track_id):
        with self.lock:
            track=next((t for t in self.overlay.visible() if t['id']==track_id),None)
            if track is None or self.latest_image is None: return None
            x1,y1,x2,y2=track['bbox']
            box=(max(0,int(x1)),max(0,int(y1)),min(self.latest_image.width,int(x2)),min(self.latest_image.height,int(y2)))
            if box[2]<=box[0] or box[3]<=box[1]: return None
            image=self.latest_image.crop(box)
            image.thumbnail((160,120))
            return jpeg(image)

    def run(self):
        if not self.config.get('enabled') or not self.config.get('source'):
            self.error = '카메라 설정에서 영상 소스를 지정하세요.'
            return
        source = self.config['source']
        while not self.stop.is_set():
            try:
                if source.startswith('device:'):
                    self.usb(resolve_device(int(source[7:]),self.config.get('device_path')))
                elif source.startswith('studio:'):
                    self.studio(source)
                else:
                    self.http(source)
            except Exception as exc:
                self.error = str(exc)[:200]
                self.log('warning', 'camera', f'{self.config["name"]}: {self.error}')
            self.stop.wait(4)

    def studio(self, source):
        from websocket import create_connection
        project, camera = source[7:].split('/')
        UUID(project);UUID(camera)
        config=requests.get(f'http://127.0.0.1:7860/api/projects/{project}/cameras/{camera}',timeout=5)
        config.raise_for_status()
        url='ws://127.0.0.1:7860/api/cameras/ws?camera='+quote(json.dumps(config.json()))
        connection=create_connection(url,timeout=5,origin='http://127.0.0.1:7860')
        try:
            self.log('info','camera',f'{self.config["name"]}: Studio 영상 스트림 연결 · 로봇 연결 없음')
            while not self.stop.is_set():
                raw=connection.recv()
                if isinstance(raw,bytes):
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.width*image.height>16_000_000: raise ValueError('영상 해상도 초과')
                        self.publish(image)
                elif not raw:
                    raise ValueError('Studio 영상 스트림이 종료되었습니다.')
        finally:
            connection.close()

    def http(self, source):
        if urlparse(source).scheme not in ('http', 'https'):
            raise ValueError('http(s) MJPEG 주소 또는 device:0 형식을 사용하세요.')
        if source==BRIDGE_URL:
            try:
                self.device_index=requests.get('http://127.0.0.1:8765/health',timeout=2).json().get('index')
            except (requests.RequestException,ValueError):
                self.device_index=None
        with requests.get(source, stream=True, timeout=(3, 5)) as response:
            response.raise_for_status()
            self.log('info', 'camera', f'{self.config["name"]} 영상 연결')
            buf = b''
            for chunk in response.iter_content(8192):
                if self.stop.is_set():
                    break
                buf += chunk
                if len(buf) > 12*1024*1024:
                    raise ValueError('MJPEG 프레임 버퍼 초과')
                while True:
                    start, end = buf.find(b'\xff\xd8'), buf.find(b'\xff\xd9')
                    if start < 0 or end < start:
                        break
                    raw, buf = buf[start:end+2], buf[end+2:]
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.width*image.height > 16_000_000:
                            raise ValueError('카메라 영상 해상도가 너무 큽니다.')
                        self.publish(image)

    def usb(self, index):
        # Explicit opt-in only: no probing/stealing Studio-owned USB devices.
        self.device_index = index
        requested_width = self.config.get('width',1280)
        requested_height = self.config.get('height',720)
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        try:
            if not cap.isOpened():
                raise ValueError('USB 카메라를 열 수 없습니다. Studio 점유 여부를 확인하세요.')
            # VGA mode crops the sensor on some webcams. Request the tested
            # wide HD mode; MJPEG avoids excessive USB bandwidth with two feeds.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, requested_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, requested_height)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.log('info', 'camera', f'{self.config["name"]}: USB 입력 {width}×{height} (요청 {requested_width}×{requested_height})')
            while not self.stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    raise ValueError('USB 카메라 프레임 읽기 실패')
                self.publish(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
                self.stop.wait(.04)
        finally:
            cap.release()
