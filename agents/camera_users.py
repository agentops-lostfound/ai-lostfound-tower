"""지금 웹캠을 쓰고 있는 프로그램 찾기 — 윈도우 전용 (LF-18 · 11/12 변재원)

한줄 설명: 윈도우가 '카메라를 쓰는 중'으로 적어 두는 기록(개인 정보 설정의 카메라 사용 기록)을 읽어, 웹캠을 붙잡은 프로그램 이름을 알려 준다.

왜: 11/12 교육원 — 관제탑 로그에 `can't grab frame. Error: -1072875772`(0xC00D3704, 다른 프로그램이 웹캠을 쓰는 중)가
0.1초마다 쏟아지고 키오스크는 '8초 안에 카메라가 열리지 않음'만 보였다. 누가 웹캠을 잡았는지 알 수 없어 원인을 찾기 어려웠다.

어디를 읽나(읽기만 함, 바꾸지 않음):
    HKCU/HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\webcam
      ├ <스토어 앱 이름>               (예: Microsoft.WindowsCamera_8wekyb3d8bbwe = 윈도우 카메라 앱)
      └ NonPackaged\\<경로의 \\ 를 # 로>  (예: C:#Program Files#Google#Chrome#Application#chrome.exe)
    값 LastUsedTimeStart > 0 이고 LastUsedTimeStop == 0 이면 '지금 쓰는 중'
- 이 기록은 윈도우 10(1903)부터 있다. 오래된 기록이 남아 있을 수 있어(프로그램이 비정상 종료) '추정'으로만 쓴다
- 관제탑 자신(같은 python.exe)은 따로 표시한다 — 같은 경로의 python 이 남아 있는 옛 관제탑일 수도 있음
"""
from __future__ import annotations

import os
import sys

KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"
FRIENDLY = {"chrome.exe": "크롬", "msedge.exe": "엣지", "whale.exe": "웨일", "firefox.exe": "파이어폭스",
            "zoom.exe": "줌", "teams.exe": "팀즈", "ms-teams.exe": "팀즈", "discord.exe": "디스코드",
            "python.exe": "파이썬", "pythonw.exe": "파이썬", "obs64.exe": "OBS", "kakaotalk.exe": "카카오톡",
            "Microsoft.WindowsCamera": "윈도우 카메라 앱"}


def _norm(path: str) -> str:
    return str(path or "").replace("\\", "#").replace("/", "#").lower()


def _read_registry() -> list[tuple[str, bool, int, int]]:
    """(이름, NonPackaged 여부, 시작, 끝) 목록. 윈도우가 아니거나 못 읽으면 빈 목록"""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    out = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            root = winreg.OpenKey(hive, KEY)
        except OSError:
            continue
        with root:
            for name, nonpack in _subkeys(winreg, root):
                try:
                    k = winreg.OpenKey(root, ("NonPackaged\\" if nonpack else "") + name)
                except OSError:
                    continue
                with k:
                    start, stop = _qword(winreg, k, "LastUsedTimeStart"), _qword(winreg, k, "LastUsedTimeStop")
                out.append((name, nonpack, start, stop))
    return out


def _subkeys(winreg, root):
    i = 0
    while True:
        try:
            name = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        if name == "NonPackaged":
            try:
                np = winreg.OpenKey(root, "NonPackaged")
            except OSError:
                continue
            with np:
                j = 0
                while True:
                    try:
                        yield winreg.EnumKey(np, j), True
                    except OSError:
                        break
                    j += 1
        else:
            yield name, False


def _qword(winreg, key, value) -> int:
    try:
        v, _ = winreg.QueryValueEx(key, value)
        return int(v or 0)
    except (OSError, TypeError, ValueError):
        return 0


def label(name: str, nonpack: bool) -> str:
    """기록 이름 → 사람이 읽는 이름. 예: 'C:#…#chrome.exe' → '크롬(chrome.exe)'"""
    if nonpack:
        exe = name.split("#")[-1]
    else:
        exe = name.split("_")[0]
    friendly = FRIENDLY.get(exe) or FRIENDLY.get(exe.lower())
    return f"{friendly}({exe})" if friendly and friendly != exe else exe


def who_uses_camera(reader=_read_registry, self_exe: str | None = None) -> list[dict]:
    """지금 웹캠을 쓰는 중으로 기록된 프로그램 → [{"name": 사람이 읽는 이름, "path": 기록 이름, "self": 관제탑 자신인지}]"""
    me = _norm(self_exe if self_exe is not None else sys.executable)
    seen, out = set(), []
    for name, nonpack, start, stop in reader():
        if not start or stop:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": label(name, nonpack), "path": name, "self": bool(nonpack and me and _norm(name) == me)})
    return out


def describe(users: list[dict]) -> str:
    """화면·오류 문구용 한 줄. 예: '사용 중(추정): 크롬(chrome.exe)'"""
    others = [u["name"] for u in users if not u["self"]]
    if others:
        return "사용 중(추정): " + ", ".join(others[:3])
    if users:
        return "다른 프로그램 기록 없음 — 남은 옛 관제탑(python) 확인"
    return ""


__all__ = ["who_uses_camera", "describe", "label"]
