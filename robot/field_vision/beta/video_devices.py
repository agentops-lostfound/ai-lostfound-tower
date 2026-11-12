import json
import subprocess
from pathlib import Path

BRIDGE_URL = 'http://127.0.0.1:8765/camera.mjpg'
BRIDGE_CONFIG = Path(__file__).resolve().parents[2]/'soarm-setup'/'camera_config.json'


def video_devices():
    script = Path(__file__).with_name('list_video_devices.ps1')
    data = subprocess.check_output(
        ['powershell.exe','-NoProfile','-NonInteractive','-File',str(script)],
        timeout=6, creationflags=subprocess.CREATE_NO_WINDOW, encoding='utf-8')
    return json.loads(data)


def resolve_device(index, path=None):
    if not path:
        return index
    for device in video_devices():
        if device['path'].casefold() == path.casefold():
            return device['index']
    raise ValueError('저장된 USB 카메라가 연결되어 있지 않습니다.')
