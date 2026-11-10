"""키오스크 서버 카메라 — 태블릿은 화면만, 웹캠은 관제탑 PC 에 꽂는다 (LF-2 · 11/9 변재원)

한줄 설명: 관제탑 PC 가 USB 웹캠을 읽어 키오스크 화면(태블릿 크롬)에 영상(MJPEG)으로 보내 준다.
태블릿 크롬은 카메라를 직접 열지 않으므로 https 설정·태블릿의 USB 웹캠 지원 여부와 상관없이 동작한다.

왜: 11/9 갤럭시탭 A8 시험 — USB Camera 앱에서는 웹캠 영상이 나오지만 크롬 카메라 목록에는 전면·후면 2개뿐
(안드로이드 외장 카메라 기능을 켜지 않은 기기). 그래서 웹캠은 PC 에 꽂고 PC 가 영상을 넘겨준다.

설정(.env, 관제탑 PC)
    TOWER_KIOSK_CAMERAS=KIOSK-A=0,KIOSK-C=1      # 키오스크 기계 번호 = OpenCV 카메라 번호(tools/list_cameras.py 로 확인, 교육원 PC 웹캠 1대 = 0)
    TOWER_KIOSK_CAMERAS=KIOSK-A=fake             # 웹캠 없이 시험 무늬(시험·클라우드용)
화면: /kiosk?machine=KIOSK-A&cam=server  → 영상 GET /api/kiosk/camera/KIOSK-A.mjpg
- 카메라는 처음 볼 때 열고, 아무도 안 보면 60초 뒤 닫는다(탑뷰 카메라 등 다른 프로그램과 오래 다투지 않게)
- 설정에 없는 기계 번호는 열지 않는다(404) — 주소만 바꿔 다른 카메라(탑뷰)를 훔쳐보지 못하게
- 11/9 저녁: 윈도우 DirectShow 로 안 열리면 Media Foundation 으로 한 번 더 연다. 처음 영상이 계속 새까마면 MJPG 를 빼고 다시 연다.
  열기에 실패하면 5초 동안은 다시 열지 않는다(화면이 0.1초마다 다시 열어 경고 줄이 쏟아지던 문제)
- 11/10 교육원: 조금 지나면 영상이 화면 왼쪽 위로 몰리고 나머지가 까맣게 나옴. 관제탑이 보낸 사진 자체가 1280×720 틀의
  왼쪽 위 640×480 에만 영상이 있었다(Media Foundation 으로 다시 열릴 때 요청한 크기와 실제 영상 크기가 어긋남). 고친 것:
  · 읽은 사진의 오른쪽·아래 까만 띠(값이 정확히 0)를 잘라 실제 영상만 쓴다(valid_size)
  · 내보내는 크기를 늘 960×720(4:3)으로 맞춘다(fit) — 중간에 크기가 바뀌면 브라우저 영상이 깨지고, 물건 감지 기준 화면도 흔들림
  · 압축 형식(MJPG)을 크기보다 먼저 정한다. DirectShow 가 방금 닫은 카메라를 못 열면 0.4초 뒤 한 번 더 연다
"""
from __future__ import annotations

import os
import threading
import time

IDLE_CLOSE_S = 60.0
RETRY_S = 5.0          # 열기 실패 뒤 다시 열기까지 기다리는 시간
DARK_LEVEL = 16        # 이 밝기(0~255) 아래면 새까만 영상으로 봄
DARK_FRAMES = 30       # 처음 이만큼 계속 새까마면 MJPG 를 빼고 다시 연다
FPS = 10
WIDTH, HEIGHT = 1280, 720          # 웹캠에 요청하는 크기
OUT_W, OUT_H = 960, 720            # 화면으로 내보내는 크기(늘 같음, 4:3 — 16:9 영상은 가운데를 자른다)


def parse_config(text: str | None) -> dict:
    """'KIOSK-A=1,KIOSK-C=2' → {'KIOSK-A': 1, 'KIOSK-C': 2}. 'fake' 는 시험 무늬. 이상한 칸은 건너뜀"""
    out = {}
    for part in (text or "").split(","):
        if "=" not in part:
            continue
        name, src = (x.strip() for x in part.split("=", 1))
        if not name or len(name) > 20 or not all(c.isalnum() or c in "-_" for c in name):
            continue
        if src == "fake":
            out[name] = "fake"
        elif src.isdigit() and int(src) < 16:
            out[name] = int(src)
    return out


class FakeSource:
    """웹캠 없이 시험용 무늬(회색 바닥 + 격자 + 시각에 따라 바뀌는 작은 숫자 칸)"""

    def __init__(self, *_):
        self.n = 0

    def isOpened(self) -> bool:
        return True

    def read(self):
        import numpy as np
        self.n += 1
        img = np.full((HEIGHT, WIDTH, 3), 200, np.uint8)
        img[::80, :] = 150
        img[:, ::80] = 150
        img[10:20, 10:10 + (self.n % 50)] = 90        # 살짝 바뀌는 칸(영상이 흐르는지 확인용, 물건 감지 기준보다 작음)
        return True, img

    def set(self, *_):
        return True

    def release(self):
        pass


def _backends() -> list:
    import cv2
    if os.name == "nt":                                   # 윈도우: DirectShow 가 USB 웹캠을 빨리 열고, 안 되면 Media Foundation
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF]
    return [cv2.CAP_ANY]


def _open(src, mjpg: bool = True):
    """카메라 열기. 여러 방식(backend)을 차례로 시도해 처음 열리는 것을 돌려준다(모두 실패하면 닫힌 카메라)"""
    if src == "fake":
        return FakeSource()
    import cv2
    cap = None
    backends = _backends()
    for n, backend in enumerate(backends):
        for attempt in range(2 if n == 0 and len(backends) > 1 else 1):   # 첫 방식(DirectShow)은 한 번 더: 방금 닫은 카메라가 아직 안 풀렸을 수 있음
            cap = cv2.VideoCapture(src, backend)
            if cap.isOpened():
                break
            cap.release()
            if attempt == 0 and n == 0 and len(backends) > 1:
                time.sleep(0.4)
        if not cap.isOpened():
            continue
        if mjpg:
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # 1080p 웹캠은 MJPG 로 받아야 초당 프레임이 나옴(크기보다 먼저)
            except Exception:
                pass
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        return cap
    return cap


def valid_size(frame) -> tuple[int, int]:
    """사진에서 실제 영상이 들어 있는 (너비, 높이). 오른쪽·아래에 붙은 까만 띠(값이 정확히 0)를 뺀 크기.
    띠가 15% 넘고 남는 크기가 8의 배수일 때만 자른다 — 어두운 장면·검은 배경지를 영상 밖으로 착각하지 않게"""
    try:
        h, w = frame.shape[:2]
        flat = frame.reshape(h, w, -1)
        cols = flat.max(axis=(0, 2)).nonzero()[0]
        rows = flat.max(axis=(1, 2)).nonzero()[0]
        if not len(cols) or not len(rows):
            return w, h                                   # 전체가 까맘(렌즈 가림) — 그대로
        vw, vh = int(cols[-1]) + 1, int(rows[-1]) + 1
    except Exception:
        return frame.shape[1], frame.shape[0]
    if (vw <= w * 0.85 or vh <= h * 0.85) and vw >= 160 and vh >= 120 and vw % 8 == 0 and vh % 8 == 0:
        return vw, vh
    return w, h


def fit(frame, out_w: int = OUT_W, out_h: int = OUT_H):
    """실제 영상만 잘라 → 가운데를 4:3 으로 맞춰 자르고 → 늘 같은 크기로. (사진, 까만 띠를 잘랐는지) 를 돌려준다"""
    import cv2
    h, w = frame.shape[:2]
    vw, vh = valid_size(frame)
    cropped = (vw, vh) != (w, h)
    if cropped:
        frame = frame[:vh, :vw]
    if vw * out_h > vh * out_w:                           # 더 넓음 → 좌우를 자른다
        nw = max(1, round(vh * out_w / out_h))
        x0 = (vw - nw) // 2
        frame = frame[:, x0:x0 + nw]
    elif vw * out_h < vh * out_w:                         # 더 높음 → 위아래를 자른다
        nh = max(1, round(vw * out_h / out_w))
        y0 = (vh - nh) // 2
        frame = frame[y0:y0 + nh, :]
    if frame.shape[1] != out_w or frame.shape[0] != out_h:
        frame = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA if frame.shape[1] > out_w else cv2.INTER_LINEAR)
    return frame, cropped


def is_dark(frame) -> bool:
    try:
        return int(frame.max()) < DARK_LEVEL
    except Exception:
        return False


class CameraFeed:
    """카메라 하나를 뒤에서 읽어 최신 JPEG 하나를 들고 있는다. 보는 사람이 없으면 닫는다"""

    def __init__(self, src, opener=_open, clock=time.monotonic):
        self.src, self._opener, self._clock = src, opener, clock
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._seen = 0.0
        self._thread: threading.Thread | None = None
        self._failed_at = None
        self.error = ""
        self.dark = False
        self.cropped = False          # 11/10 읽은 사진에 까만 띠가 있어 실제 영상만 잘라 보내는 중(카메라가 낮은 화질로 열림)
        self.source_size = None       # 웹캠이 준 사진 크기(너비, 높이)

    def touch(self) -> None:
        """누군가 보고 있음 → 없으면 읽기 시작"""
        with self._lock:
            self._seen = self._clock()
            if self._thread is None or not self._thread.is_alive():
                if self.error and self._failed_at is not None and self._clock() - self._failed_at < RETRY_S:
                    return                                # 방금 실패 — 잠깐 쉬었다가 다시 연다
                self.error = ""
                self._thread = threading.Thread(target=self._run, daemon=True, name=f"kiosk-cam-{self.src}")
                self._thread.start()

    def latest(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def _fail(self, msg: str) -> None:
        self.error = msg
        self._failed_at = self._clock()

    def _run(self) -> None:
        import cv2
        cap = None
        try:
            cap = self._opener(self.src)
            if not cap.isOpened():
                self._fail("카메라를 열 수 없음(번호·USB 연결·다른 프로그램 사용 중 확인 — python tools/list_cameras.py)")
                return
            fails, dark_run, reopened = 0, 0, False
            while self._clock() - self._seen < IDLE_CLOSE_S:
                ok, frame = cap.read()
                if not ok or frame is None:
                    fails += 1
                    if fails > 20:
                        self._fail("카메라 영상이 들어오지 않음")
                        return
                    time.sleep(0.1)
                    continue
                fails = 0
                if is_dark(frame):
                    dark_run += 1
                    if dark_run == DARK_FRAMES and not reopened and self.src != "fake":
                        reopened = True                   # 일부 웹캠은 MJPG 로 열면 검은 화면 → 기본 형식으로 다시 연다
                        cap.release()
                        cap = _open(self.src, mjpg=False) if self._opener is _open else self._opener(self.src)
                        dark_run = 0
                        continue
                else:
                    dark_run = 0
                self.dark = dark_run >= DARK_FRAMES
                self.source_size = (int(frame.shape[1]), int(frame.shape[0]))
                frame, self.cropped = fit(frame)          # 실제 영상만 · 늘 같은 크기로
                ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if ok:
                    with self._lock:
                        self._jpeg = buf.tobytes()
                time.sleep(1.0 / FPS)
        except Exception as e:                        # 오류 문구만 남김(경로·내부 정보는 화면에 안 나감)
            self._fail(f"카메라 오류({type(e).__name__})")
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            with self._lock:
                self._jpeg = None


class KioskCameras:
    def __init__(self, config: dict | None = None, opener=_open):
        self.config = parse_config(os.environ.get("TOWER_KIOSK_CAMERAS")) if config is None else config
        self._feeds = {name: CameraFeed(src, opener) for name, src in self.config.items()}

    def feed(self, machine: str) -> CameraFeed | None:
        return self._feeds.get(machine)

    def status(self) -> dict:
        return {name: {"source": "fake" if f.src == "fake" else "usb", "streaming": f.latest() is not None,
                       **({"error": f.error} if f.error else {}),
                       **({"warning": "영상이 새까맘(렌즈 가림·조명·다른 카메라 번호 확인)"} if f.dark else
                          {"warning": "웹캠이 낮은 화질로 열림 — 실제 영상만 잘라 보내는 중(다른 프로그램이 웹캠을 쓰는지 확인)"} if f.cropped else {}),
                       **({"size": [OUT_W, OUT_H]} if f.latest() is not None else {})} for name, f in self._feeds.items()}


def add_camera_routes(app, cameras: KioskCameras | None = None) -> KioskCameras:
    """GET /api/kiosk/camera/{기계}.mjpg (영상) · /api/kiosk/camera/{기계}.jpg (한 장) · /api/kiosk/cameras (상태)"""
    import asyncio
    from fastapi import HTTPException
    from fastapi.responses import Response, StreamingResponse
    cams = cameras or KioskCameras()

    def get(machine: str) -> CameraFeed:
        f = cams.feed(machine)
        if f is None:
            raise HTTPException(status_code=404, detail="이 기계에는 서버 카메라가 설정되지 않았어요(.env TOWER_KIOSK_CAMERAS)")
        return f

    async def first_frame(f: CameraFeed, wait_s: float = 8.0) -> bytes:
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait_s:
            f.touch()
            jpg = f.latest()
            if jpg:
                return jpg
            if f.error:
                break
            await asyncio.sleep(0.1)
        raise HTTPException(status_code=503, detail=f.error or "8초 안에 카메라 영상이 오지 않았어요")

    @app.get("/api/kiosk/cameras")
    def camera_status() -> dict:
        return {"machines": cams.status()}

    @app.get("/api/kiosk/camera/{machine}.jpg")
    async def camera_jpg(machine: str):
        jpg = await first_frame(get(machine))
        return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/kiosk/camera/{machine}.mjpg")
    async def camera_mjpg(machine: str, frames: int = 0):
        """frames: 0 = 끝없이(화면용), 1 이상 = 그 장수만 보내고 끝(시험·점검용)"""
        f = get(machine)
        jpg = await first_frame(f)
        limit = max(0, min(int(frames), 1000))

        async def stream():
            last, sent = None, 0
            cur = jpg
            while not limit or sent < limit:
                f.touch()
                if cur is not None and cur is not last:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(cur)).encode() + b"\r\n\r\n" + cur + b"\r\n"
                    last, sent = cur, sent + 1
                await asyncio.sleep(1.0 / FPS)
                cur = f.latest()
                if cur is None and f.error:
                    return
        return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    return cams


__all__ = ["KioskCameras", "CameraFeed", "FakeSource", "parse_config", "add_camera_routes", "is_dark", "valid_size", "fit"]
