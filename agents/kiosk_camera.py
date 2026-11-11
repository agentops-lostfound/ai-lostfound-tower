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
- 11/11 키오스크 검은 화면(계속 반복되던 문제) 완전 개선:
  · 화면은 끝나지 않는 MJPEG 대신 사진 한 장씩(GET .jpg?after=번호)을 받아 그린다 — 브라우저는 한 주소에 연결을 6개까지만 열어,
    발표 화면(틀 3개)·다른 탭이 MJPEG 를 붙잡고 있으면 새 영상 연결이 줄을 서다 까맣게 남았다. 이제 화면 하나 = 짧은 요청 하나씩
  · 사진마다 번호(X-Frame-Seq)·나이(X-Frame-Age-Ms)·어두움(X-Frame-Dark)을 붙여, 화면이 '멈춤'과 '까맘'을 구별해 다시 연결한다
  · 카메라 읽기가 멈추면(STALL_S 동안 새 사진 없음) 다른 쪽에서 카메라를 놓아 읽기를 풀고 다시 연다(Windows DirectShow 가 read 에서 멈춤)
- 11/11 노출 고정(TOWER_KIOSK_EXPOSURE): 회색 펠트를 깔자 카메라 자동 노출이 화면을 밝게 올려 연한 색(분홍·하늘색 핸드크림)과
  흰 물건이 하얗게 날아감(물건 픽셀의 40~87% 가 최댓값). 노출을 고정하면 바닥·조명이 바뀌어도 물건 밝기가 그대로다.
    TOWER_KIOSK_EXPOSURE=-6                       # 모든 키오스크 카메라(DirectShow 값: 2의 거듭제곱 초, -6 ≈ 1/64초, 작을수록 어두움)
    TOWER_KIOSK_EXPOSURE=KIOSK-A=-6,KIOSK-C=auto  # 기계별. 비우면 지금처럼 카메라가 정함(아무것도 건드리지 않음)
  값 고르기: 관제탑을 끄고 python tools/camera_exposure.py (값마다 사진·날아간 비율을 비교해 추천)
- 11/11 화이트밸런스 고정(TOWER_KIOSK_WB): 자동 화이트밸런스는 화면에 큰 색 물건이 들어오면 그 색을 빼 버려(분홍 크림 → 덜 분홍)
  물건마다 색 기준이 달라진다. 켈빈(빛의 색온도, 2800~6500) 값으로 고정한다. 형식은 노출과 같음(전체·기계별·auto, 비우면 건드리지 않음).
  값 고르기: python tools/camera_exposure.py --exposure -6 --wb auto,4000,4600,5200,6000 (회색 펠트가 가장 회색으로 찍히는 값을 추천)
- 11/11 교육원 웹캠은 노출 명령을 받지 않음(-1). 드라이버 설정 창(--dialog)에서 대비 260 → 200 이면 흰 폰이 날아가지 않음
  (clip 13% → 0%, 바닥 밝기 87). 그 값을 카메라를 열 때마다 넣는다(드라이버 값은 웹캠을 다시 꽂으면 풀릴 수 있음, 추정):
    TOWER_KIOSK_CAMPROPS=CONTRAST=200            # 이름: BRIGHTNESS·CONTRAST·SATURATION·GAMMA·GAIN·SHARPNESS·BACKLIGHT·HUE
    TOWER_KIOSK_MJPG=0                            # 교육원 웹캠은 MJPG 에서 대비가 영상에 안 먹음 → MJPG 없이 열기(추정, --try --no-mjpg 로 확인)
  확인: python tools/camera_exposure.py --try CONTRAST=200 (관제탑 끈 상태, 넣은 값·카메라가 읽은 값·날아간 점 %)
"""
from __future__ import annotations

import os
import threading
import weakref
import time

IDLE_CLOSE_S = 60.0
RETRY_S = 5.0          # 열기 실패 뒤 다시 열기까지 기다리는 시간
DARK_LEVEL = 16        # 이 밝기(0~255) 아래면 새까만 영상으로 봄
DARK_FRAMES = 30       # 이만큼 계속 새까마면 카메라를 다시 연다(MJPG 를 빼고/넣고 번갈아)
DARK_RETRY_MAX_S = 10.0   # 다시 열기 사이 간격의 최댓값(2초부터 늘어남)
STALL_S = 4.0             # 11/11 보는 사람이 있는데 이만큼 새 사진이 없으면 카메라 읽기가 멈춘 것으로 보고 놓았다가 다시 연다
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


EXPOSURE_MIN, EXPOSURE_MAX = -13, 0     # DirectShow 노출 값 범위(대부분의 USB 웹캠, 추정 — 카메라마다 받아들이는 범위가 다를 수 있음)
AUTO_ON, AUTO_OFF = 0.75, 0.25          # OpenCV DirectShow 에서 CAP_PROP_AUTO_EXPOSURE 의 자동/수동 값
WB_MIN, WB_MAX = 2800, 6500             # 화이트밸런스 켈빈 범위(대부분의 USB 웹캠, 추정)


def parse_exposure(text: str | None, lo: float = EXPOSURE_MIN, hi: float = EXPOSURE_MAX) -> dict:
    """노출(또는 화이트밸런스) 설정 읽기. '-6' → {'*': -6.0}, 'KIOSK-A=-6,KIOSK-C=auto' → {'KIOSK-A': -6.0, 'KIOSK-C': 'auto'}.
    범위(lo~hi) 밖·숫자 아닌 값은 버린다(잘못 쓴 값이 카메라를 새까맣게 만들지 않게)"""
    def value(s: str):
        s = s.strip().lower()
        if s == "auto":
            return "auto"
        try:
            v = float(s)
        except ValueError:
            return None
        return v if lo <= v <= hi else None
    out: dict = {}
    for part in (text or "").split(","):
        if not part.strip():
            continue
        if "=" in part:
            name, s = (x.strip() for x in part.split("=", 1))
            if not name or len(name) > 20 or not all(c.isalnum() or c in "-_" for c in name):
                continue
        else:
            name, s = "*", part
        v = value(s)
        if v is not None:
            out[name] = v
    return out


def exposure_for(config: dict, machine: str):
    """기계 하나의 노출 값(None = 건드리지 않음)"""
    return config.get(machine, config.get("*"))


def apply_exposure(cap, value) -> dict | None:
    """열린 카메라에 노출을 정한다. None = 아무것도 안 함, 'auto' = 자동으로 되돌림, 숫자 = 자동을 끄고 그 값으로 고정.
    → {'requested': 값, 'auto': 읽은 자동 값, 'now': 읽은 노출 값} (카메라가 값을 안 받아들이면 now 가 다르게 나옴)"""
    if value is None:
        return None
    import cv2
    try:
        if value == "auto":
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTO_ON)
        else:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTO_OFF)
            cap.set(cv2.CAP_PROP_EXPOSURE, float(value))
        get = getattr(cap, "get", None)
        auto = get(cv2.CAP_PROP_AUTO_EXPOSURE) if get else None
        now = get(cv2.CAP_PROP_EXPOSURE) if get else None
        return {"requested": value, "auto": auto, "now": now}
    except Exception as e:                                # 노출을 못 바꿔도 영상은 계속 보낸다
        return {"requested": value, "error": type(e).__name__}


CAM_PROPS = ("BRIGHTNESS", "CONTRAST", "SATURATION", "GAMMA", "GAIN", "SHARPNESS", "BACKLIGHT", "HUE")


def parse_props(text: str | None) -> dict:
    """11/11 웹캠 영상 설정(드라이버 '비디오 프로세서 앰프' 값) 읽기: 'CONTRAST=200,GAMMA=18' → {'CONTRAST': 200.0, ...}.
    정해 둔 이름(CAM_PROPS)·숫자(-10000~10000)만 받는다"""
    out: dict = {}
    for part in (text or "").split(","):
        if "=" not in part:
            continue
        name, v = (x.strip() for x in part.split("=", 1))
        name = name.upper()
        if name not in CAM_PROPS:
            continue
        try:
            f = float(v)
        except ValueError:
            continue
        if -10000 <= f <= 10000:
            out[name] = f
    return out


def apply_props(cap, props: dict | None) -> dict | None:
    """영상 설정을 넣고 카메라가 읽어 준 값을 돌려준다({'CONTRAST': {'requested': 200, 'now': 200}}). 비었으면 None"""
    if not props:
        return None
    import cv2
    out = {}
    for name, v in props.items():
        pid = getattr(cv2, "CAP_PROP_" + name, None)
        if pid is None:
            continue
        try:
            cap.set(pid, float(v))
            get = getattr(cap, "get", None)
            out[name] = {"requested": v, "now": get(pid) if get else None}
        except Exception as e:
            out[name] = {"requested": v, "error": type(e).__name__}
    return out


def parse_wb(text: str | None) -> dict:
    """화이트밸런스 설정 읽기('5000', 'KIOSK-A=4600,KIOSK-C=auto')"""
    return parse_exposure(text, WB_MIN, WB_MAX)


def apply_wb(cap, value) -> dict | None:
    """화이트밸런스를 정한다. None = 안 함, 'auto' = 자동으로 되돌림, 숫자(켈빈) = 자동을 끄고 고정.
    OpenCV 가 카메라 종류에 따라 온도(WB_TEMPERATURE) 또는 파랑 축(WHITE_BALANCE_BLUE_U)으로 받으므로 둘 다 넣는다"""
    if value is None:
        return None
    import cv2
    try:
        if value == "auto":
            cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        else:
            cap.set(cv2.CAP_PROP_AUTO_WB, 0)
            cap.set(cv2.CAP_PROP_WB_TEMPERATURE, float(value))
            cap.set(cv2.CAP_PROP_WHITE_BALANCE_BLUE_U, float(value))
        get = getattr(cap, "get", None)
        auto = get(cv2.CAP_PROP_AUTO_WB) if get else None
        now = get(cv2.CAP_PROP_WB_TEMPERATURE) if get else None
        return {"requested": value, "auto": auto, "now": now}
    except Exception as e:
        return {"requested": value, "error": type(e).__name__}


class FakeSource:
    """웹캠 없이 시험용 무늬(회색 바닥 + 격자 + 시각에 따라 바뀌는 작은 숫자 칸)"""

    def __init__(self, *_):
        self.n = 0
        self.props: dict = {}

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

    def set(self, prop=None, value=None, *_):
        self.props[prop] = value
        return True

    def get(self, prop):
        return self.props.get(prop, 0.0)

    def release(self):
        pass


def _backends() -> list:
    import cv2
    if os.name == "nt":                                   # 윈도우: DirectShow 가 USB 웹캠을 빨리 열고, 안 되면 Media Foundation
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF]
    return [cv2.CAP_ANY]


def mjpg_default() -> bool:
    """11/11 TOWER_KIOSK_MJPG=0 이면 압축 형식(MJPG)을 쓰지 않고 연다. 교육원 웹캠은 MJPG 에서 대비(CONTRAST) 설정이
    영상에 반영되지 않았음(읽은 값은 200 인데 날아감 12% 그대로, MJPG 없이 연 드라이버 설정 창에서는 0%)"""
    return str(os.environ.get("TOWER_KIOSK_MJPG", "1")).strip().lower() not in ("0", "false", "no", "off")


def _open(src, mjpg: bool | None = None):
    """카메라 열기. 여러 방식(backend)을 차례로 시도해 처음 열리는 것을 돌려준다(모두 실패하면 닫힌 카메라)"""
    if src == "fake":
        return FakeSource()
    import cv2
    if mjpg is None:
        mjpg = mjpg_default()
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


_ALL: "weakref.WeakSet" = weakref.WeakSet()        # 만들어진 카메라 묶음(관제탑을 끌 때 한꺼번에 놓으려고)


def stop_all(timeout: float = 1.5) -> bool:
    """열려 있는 서버 카메라를 모두 놓는다 → 모두 제때 멈췄는지(tools/run_tower.py · 관제탑 종료 때)"""
    return all([c.stop(timeout) for c in list(_ALL)])


class CameraFeed:
    """카메라 하나를 뒤에서 읽어 최신 JPEG 하나를 들고 있는다. 보는 사람이 없으면 닫는다"""

    def __init__(self, src, opener=_open, clock=time.monotonic, exposure=None, wb=None, props=None):
        self.src, self._opener, self._clock = src, opener, clock
        self.exposure = exposure      # 11/11 노출 고정 값(None = 카메라가 정함)
        self.wb = wb                  # 11/11 화이트밸런스 고정 값(켈빈, None = 카메라가 정함)
        self.props = props or {}      # 11/11 영상 설정(대비 등, TOWER_KIOSK_CAMPROPS)
        self.props_state: dict | None = None
        self.exposure_state: dict | None = None   # 마지막으로 정한 결과(상태 화면용)
        self.wb_state: dict | None = None
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._seen = 0.0
        self._thread: threading.Thread | None = None
        self._failed_at = None
        self._stop = False            # 11/10 관제탑을 끌 때: 읽기를 멈추고 카메라를 놓는다(안 놓으면 Windows 에서 프로그램이 안 꺼질 수 있음)
        self.error = ""
        self.dark = False
        self.cropped = False          # 11/10 읽은 사진에 까만 띠가 있어 실제 영상만 잘라 보내는 중(카메라가 낮은 화질로 열림)
        self.source_size = None       # 웹캠이 준 사진 크기(너비, 높이)
        self.seq = 0                  # 11/11 새 사진 번호(화면이 같은 사진을 다시 받지 않게·멈춤 감지)
        self._at = None               # 마지막 새 사진 시각
        self._cap = None              # 지금 읽는 카메라(멈춤을 풀려고 다른 쪽에서 놓을 수 있게)
        self.stalls = 0               # 멈춤을 풀어 다시 연 횟수(상태 화면용)

    def _settings(self, cap) -> None:
        """카메라를 열거나 다시 열 때마다 노출·화이트밸런스를 다시 정한다(다시 열면 풀릴 수 있음)"""
        self.exposure_state = apply_exposure(cap, self.exposure)
        self.wb_state = apply_wb(cap, self.wb)
        self.props_state = apply_props(cap, self.props)

    def touch(self) -> None:
        """누군가 보고 있음 → 없으면 읽기 시작"""
        with self._lock:
            self._seen = self._clock()
            if self._stop:
                return                                    # 끄는 중 — 다시 열지 않는다
            alive = self._thread is not None and self._thread.is_alive()
            if alive and self._at is not None and self._clock() - self._at > STALL_S and self._cap is not None:
                # 11/11 읽기가 멈춤 — 카메라를 놓으면 read() 가 풀려 읽기가 끝나고, 다음 touch 에서 새로 연다
                cap, self._cap, self._at = self._cap, None, None
                self.stalls += 1
                try:
                    cap.release()
                except Exception:
                    pass
                return
            if self._thread is None or not self._thread.is_alive():
                if self.error and self._failed_at is not None and self._clock() - self._failed_at < RETRY_S:
                    return                                # 방금 실패 — 잠깐 쉬었다가 다시 연다
                self.error = ""
                self._thread = threading.Thread(target=self._run, daemon=True, name=f"kiosk-cam-{self.src}")
                self._thread.start()

    def stop(self, timeout: float = 1.5) -> bool:
        """읽기를 멈추고 카메라를 놓는다 → 제때 멈췄는지. 관제탑을 끌 때 부른다"""
        with self._lock:
            self._stop = True
            t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout)
            return not t.is_alive()
        return True

    def latest(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def frame(self) -> tuple[bytes | None, int, float | None]:
        """(최신 JPEG, 번호, 나이 초) — 나이는 마지막 새 사진 뒤 지난 시간(없으면 None)"""
        with self._lock:
            age = None if self._at is None else max(0.0, self._clock() - self._at)
            return self._jpeg, self.seq, age

    def _fail(self, msg: str) -> None:
        self.error = msg
        self._failed_at = self._clock()

    def _run(self) -> None:
        import cv2
        cap = None
        try:
            cap = self._opener(self.src)
            with self._lock:
                self._cap, self._at = cap, self._clock()
            if not cap.isOpened():
                self._fail("카메라를 열 수 없음(번호·USB 연결·다른 프로그램 사용 중 확인 — python tools/list_cameras.py)")
                return
            self._settings(cap)
            fails, dark_run, reopens, next_reopen = 0, 0, 0, 0.0
            while not self._stop and self._clock() - self._seen < IDLE_CLOSE_S:
                ok, frame = cap.read()
                if self._cap is not cap:                  # 11/11 멈춤으로 다른 쪽이 카메라를 놓음 → 이 읽기를 끝내고 새로 연다
                    return
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
                    # 계속 새까마면 카메라를 다시 연다. 11/10: 전에는 한 번만 다시 열어, 그래도 까맣면 관제탑을 다시 켤 때까지 까만 채였다
                    # (교육원: 영상 값이 전부 0 — 조명이 아니라 카메라가 빈 화면을 보냄). 이제 MJPG 를 빼고/넣고 번갈아, 간격을 늘려 가며(최대 10초) 계속 시도
                    if dark_run >= DARK_FRAMES and self.src != "fake" and self._clock() >= next_reopen:
                        reopens += 1
                        cap.release()
                        time.sleep(min(1.0, 0.3 * reopens))        # 방금 놓은 카메라가 풀릴 시간
                        cap = _open(self.src, mjpg=mjpg_default() ^ (reopens % 2 == 1)) if self._opener is _open else self._opener(self.src)
                        with self._lock:
                            self._cap = cap
                        if not cap.isOpened():
                            self._fail("카메라를 다시 열 수 없음(다른 프로그램이 쓰는 중인지 확인)")
                            return
                        self._settings(cap)                   # 다시 열면 카메라 설정이 풀릴 수 있음
                        dark_run = 0
                        next_reopen = self._clock() + min(DARK_RETRY_MAX_S, 2.0 * reopens)
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
                        self.seq += 1
                        self._at = self._clock()
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
                if self._cap is cap:
                    self._cap = None


class KioskCameras:
    def __init__(self, config: dict | None = None, opener=_open, exposure: dict | None = None, wb: dict | None = None,
                 props: dict | None = None):
        self.config = parse_config(os.environ.get("TOWER_KIOSK_CAMERAS")) if config is None else config
        self.exposure = parse_exposure(os.environ.get("TOWER_KIOSK_EXPOSURE")) if exposure is None else exposure
        self.wb = parse_wb(os.environ.get("TOWER_KIOSK_WB")) if wb is None else wb
        self.props = parse_props(os.environ.get("TOWER_KIOSK_CAMPROPS")) if props is None else props
        # 11/11 교육원: 웹캠 1대를 두 기계(KIOSK-A=0,KIOSK-C=0)에 같이 쓰면 카메라를 두 번 열어 한쪽 화면이 새까맸다
        #   → 같은 카메라 번호는 읽기(CameraFeed) 하나를 함께 쓴다(노출·화이트밸런스는 먼저 적힌 기계 값). 'fake' 는 따로
        by_src: dict = {}
        self._feeds = {}
        for name, src in self.config.items():
            if src != "fake" and src in by_src:
                self._feeds[name] = by_src[src]
                continue
            feed = CameraFeed(src, opener, exposure=exposure_for(self.exposure, name), wb=exposure_for(self.wb, name),
                              props=self.props)
            self._feeds[name] = feed
            if src != "fake":
                by_src[src] = feed
        _ALL.add(self)

    def stop(self, timeout: float = 1.5) -> bool:
        return all([f.stop(timeout) for f in {id(f): f for f in self._feeds.values()}.values()])

    def feed(self, machine: str) -> CameraFeed | None:
        return self._feeds.get(machine)

    def status(self) -> dict:
        return {name: {"source": "fake" if f.src == "fake" else "usb", "streaming": f.latest() is not None,
                       **({"error": f.error} if f.error else {}),
                       **({"warning": "영상이 새까맘(렌즈 가림·조명·다른 카메라 번호 확인)"} if f.dark else
                          {"warning": "웹캠이 낮은 화질로 열림 — 실제 영상만 잘라 보내는 중(다른 프로그램이 웹캠을 쓰는지 확인)"} if f.cropped else {}),
                       **({"size": [OUT_W, OUT_H]} if f.latest() is not None else {}),
                       **({"stalls": f.stalls} if f.stalls else {}),
                       **({"exposure": f.exposure_state} if f.exposure_state else {}),
                       **({"white_balance": f.wb_state} if f.wb_state else {}),
                       **({"props": f.props_state} if f.props_state else {})} for name, f in self._feeds.items()}


def add_camera_routes(app, cameras: KioskCameras | None = None) -> KioskCameras:
    """GET /api/kiosk/camera/{기계}.mjpg (영상) · /api/kiosk/camera/{기계}.jpg (한 장) · /api/kiosk/cameras (상태)"""
    import asyncio
    from fastapi import HTTPException
    from fastapi.responses import Response, StreamingResponse
    cams = cameras or KioskCameras()
    try:                                                  # 11/10 관제탑이 꺼질 때 카메라를 놓는다(Windows 에서 안 꺼지던 것 예방)
        app.add_event_handler("shutdown", lambda: cams.stop(1.5))
    except Exception:
        pass

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
    async def camera_jpg(machine: str, after: int = -1):
        """사진 한 장. 11/11 화면은 이것을 이어 부른다: after=받은 번호 → 그보다 새 사진이 올 때까지 최대 1.5초 기다림.
        머리말 X-Frame-Seq(번호)·X-Frame-Age-Ms(마지막 새 사진 뒤 시간)·X-Frame-Dark(1 = 새까만 영상)"""
        f = get(machine)
        await first_frame(f)
        t0 = time.monotonic()
        jpg, seq, age = f.frame()
        while after >= 0 and seq <= after and time.monotonic() - t0 < 1.5:
            f.touch()
            await asyncio.sleep(0.03)
            jpg, seq, age = f.frame()
        f.touch()
        if jpg is None:
            raise HTTPException(status_code=503, detail=f.error or "카메라 영상이 끊김 — 다시 여는 중")
        return Response(jpg, media_type="image/jpeg", headers={
            "Cache-Control": "no-store", "X-Frame-Seq": str(seq), "X-Frame-Age-Ms": str(int((age or 0) * 1000)),
            "X-Frame-Dark": "1" if f.dark else "0"})

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


__all__ = ["mjpg_default", "KioskCameras", "CameraFeed", "FakeSource", "parse_config", "parse_exposure", "exposure_for", "apply_exposure",
           "parse_wb", "apply_wb", "parse_props", "apply_props",
           "add_camera_routes", "is_dark", "valid_size", "fit"]
