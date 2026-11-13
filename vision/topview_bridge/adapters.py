"""기존 Studio 공유 카메라 소비 및 관제탑 GET 어댑터."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import cv2
import numpy as np


def now():
    return datetime.now(timezone.utc).isoformat()


def get_json(url, timeout=5, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
        return json.load(response)


def storage_snapshot(base, token=None):
    started = now()
    layout = get_json(base.rstrip("/") + "/api/admin/storage", token=token)
    if not isinstance(layout, dict):
        raise ValueError("잘못된 보관함 응답")
    # The storage endpoint is the operational authority, even when PostgreSQL is only a mirror.
    return {"layout": layout.get("layout", layout), "requested_at": started, "received_at": now(),
            "source": base.rstrip("/") + "/api/admin/storage"}


def camera_config(config):
    base = config["studio_url"].rstrip("/")
    sessions = get_json(base + "/api/runtime/sessions")
    if not any(row.get("status") == "running" and config["camera_name"] in row.get("camera_keys", []) for row in sessions):
        raise RuntimeError("Studio의 기존 탑뷰 공유 세션이 없습니다. Studio에서 세션을 연결해 주세요.")
    env = get_json(base + f'/api/projects/{config["project_id"]}/environments/{config["environment_id"]}')
    camera = next((row for row in env["cameras"] if row["name"] == config["camera_name"]), None)
    if camera is None or camera["id"] != config["camera_id"]:
        raise RuntimeError("설정한 탑뷰 카메라 ID가 현재 환경과 다릅니다.")
    return camera


def frames(config, stop):
    from websockets.sync.client import connect
    camera = camera_config(config)
    base = config["studio_url"].rstrip("/")
    url = base.replace("http://", "ws://").replace("https://", "wss://")
    url += "/api/cameras/ws?" + urllib.parse.urlencode({"camera": json.dumps(camera)})
    with connect(url, open_timeout=8, close_timeout=2, max_size=8_000_000) as websocket:
        last_emit = 0
        while not stop.is_set():
            raw = websocket.recv(timeout=5)
            if not isinstance(raw, bytes) or time.monotonic() - last_emit < .3:
                continue
            frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if frame is None or frame.std() < 5:
                continue
            last_emit = time.monotonic()
            yield raw, frame, now(), last_emit


def anchors(frame):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
    corners, ids, _ = cv2.aruco.ArucoDetector(dictionary).detectMarkers(frame)
    return {str(int(key)): corner[0].tolist() for corner, key in zip(corners, ids.flatten())} if ids is not None else {}


def check_calibration(frame, config, camera_id):
    if camera_id != config.get("camera_id"):
        return "카메라 변경 — 영역 재설정 필요"
    if [frame.shape[1], frame.shape[0]] != config.get("image_size_px"):
        return "해상도 변경 — 영역 재설정 필요"
    reference = config.get("anchors", {})
    if not reference:
        return "영역 기준 마커 없음 — 영역 저장 필요"
    current = anchors(frame)
    for key, points in reference.items():
        if key not in current:
            return f"기준 마커 {key} 가림/미검출"
        if float(np.max(np.linalg.norm(np.array(points)-np.array(current[key]), axis=1))) > config.get("anchor_tolerance_px", 12):
            return "카메라/보관판 이동 — 영역 재설정 필요"
    return None
