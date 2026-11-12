"""지금 웹캠을 쓰고 있는 프로그램 보기 (LF-18 · 11/12 변재원)

한줄 설명: 관제탑 로그에 `can't grab frame. Error: -1072875772` 가 쏟아질 때, 웹캠을 붙잡은 프로그램이 무엇인지 알려 준다.

쓰는 법(관제탑 PC, 저장소 폴더, .venv 켠 상태 — 관제탑이 켜져 있어도 됨):
    python tools/camera_who.py
- 윈도우 '카메라 사용 기록'을 읽기만 한다(아무것도 끄거나 바꾸지 않음). 윈도우가 아니면 '확인할 수 없음'
- 결과의 프로그램을 닫은 뒤 키오스크 화면은 15초 안에 저절로 다시 연결된다(관제탑을 다시 켤 필요 없음)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from agents.camera_users import who_uses_camera
    if os.name != "nt":
        print("윈도우에서만 확인할 수 있어요(카메라 사용 기록이 윈도우에만 있음)")
        return 0
    users = who_uses_camera()
    if not users:
        print("✅ 지금 웹캠을 쓰는 중으로 기록된 프로그램이 없어요")
        print("   그래도 관제탑 로그에 -1072875772 가 나오면: 웹캠 USB 를 뽑았다 다시 꽂고 10초 뒤 키오스크 화면을 새로고침")
        return 0
    print("지금 웹캠을 쓰는 중으로 기록된 프로그램(추정 — 비정상 종료된 기록이 남아 있을 수 있음):")
    for u in users:
        mine = "  ← 관제탑과 같은 python(지금 관제탑 자신 또는 남아 있는 옛 관제탑)" if u["self"] else ""
        print(f"  - {u['name']}{mine}")
        print(f"      {u['path'].replace('#', chr(92))}")
    others = [u for u in users if not u["self"]]
    if others:
        print("→ 위 프로그램에서 카메라를 끄거나(크롬이면 카메라를 쓰는 탭 닫기) 프로그램을 닫아 주세요")
    else:
        print("→ 관제탑 python 만 보임. 관제탑을 끈 상태에서도 보이면 남은 옛 관제탑이 있음:")
        print("   PowerShell: Get-Process python | Select-Object Id, StartTime, Path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
