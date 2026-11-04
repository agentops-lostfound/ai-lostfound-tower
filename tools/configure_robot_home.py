"""LF-11/12 기록한 자세를 Home 목표 설정으로 저장. 장비를 움직이지 않는다."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robot.home_profiles import DEFAULT_STORE, load_home, select_candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("status", "set"))
    parser.add_argument("--candidate")
    parser.add_argument("--name", default="접힌 대기 자세")
    parser.add_argument("--store-dir", default=str(DEFAULT_STORE))
    args = parser.parse_args()
    if args.operation == "set":
        if not args.candidate:
            parser.error("--candidate에 기록한 자세 파일을 지정하세요")
        result = select_candidate(args.candidate, args.store_dir, name=args.name)
    else:
        result = {"result": "HOME_POSE_STATUS", **load_home(args.store_dir), "movement_commands_sent": 0}
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
