"""LF-12 실험용 근거리 Home. 맨 아래 회전만 최대 정규화 1단위 복귀.

일반 작업 자세에서 접힌 자세로 가는 경로를 보장하지 않는다. 현재 다른
관절이 저장 자세의 0.2단위 이내일 때만 허용한다. 자동 장비 연결/토크 ON 없음.
"""
import argparse
import json
import math
from pathlib import Path
import time
import uuid

try:
    from .robot_bounded_stop_trial import Client
except ImportError:
    from robot_bounded_stop_trial import Client
try:
    from robot.home_profiles import validate_profile
except ImportError:
    from home_profiles import validate_profile

MAX_PAN_DISTANCE = 1.0
TOLERANCE = 0.2


class Interrupted(Exception):
    pass


def check_values(values):
    if (not isinstance(values, (tuple, list)) or len(values) != 6
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in values)
            or any(not -100 <= x <= 100 for x in values[:5]) or not 0 <= values[5] <= 100):
        raise RuntimeError("유효한 6개 정규화 관절 상태가 필요합니다")


def plan_local_return(start, profile):
    validate_profile(profile)
    check_values(start)
    target = profile["positions"]
    if abs(target[0]-start[0]) > MAX_PAN_DISTANCE:
        raise RuntimeError("Home에서 너무 멉니다. 현재 시험은 맨 아래 회전 1단위 이내만 허용합니다")
    if any(abs(target[i]-start[i]) > TOLERANCE for i in range(1, 6)):
        raise RuntimeError("다른 관절이 Home 자세와 다릅니다. 새 복귀 경로 확인이 필요합니다")
    # 다른 관절/집게는 출발 시 측정 위치 그대로 유지한다.
    end = list(start)
    end[0] = target[0]
    return end


def run_home(client, profile, *, expected_session, expected_epoch, confirmed=False,
             local_trial=False, sleep=time.sleep, clock=time.monotonic):
    if confirmed is not True or local_trial is not True:
        raise PermissionError("직원 확인 및 근거리 시험 선택이 필요합니다")
    validate_profile(profile)
    state = client.rpc("status")
    if (not state.get("ok") or state.get("session") != expected_session
            or state.get("epoch") != expected_epoch or not state.get("stop_requested")
            or not state.get("hold_commanded")):
        raise RuntimeError("화면에서 확인한 정지 상태가 바뀌었거나 다른 작업이 진행 중입니다")
    start = client.positions()
    end = plan_local_return(start, profile)
    result = {"result": "HOME_ABORTED", "route": "local_pan_trial",
              "profile_revision": profile["revision"], "start": start,
              "target": profile["positions"], "sent_targets": 0,
              "automatic_retry": False, "general_path_verified": False,
              "request_acknowledgement": "queued_only", "position_trace": [],
              "last_requested_target": None}
    if all(abs(start[i]-profile["positions"][i]) <= TOLERANCE for i in range(6)):
        latest = client.rpc("status")
        if (not latest.get("ok") or latest.get("session") != expected_session
                or latest.get("epoch") != expected_epoch or not latest.get("stop_requested")
                or not latest.get("hold_commanded")):
            raise RuntimeError("Home 위치 확인 중 상태 변경")
        return {**result, "result": "HOME_ALREADY_REACHED", "final_positions": start,
                "stop_requested_after_home": True, "hold_commanded_after_home": True}
    deadline = clock() + 12.0
    writer = "local-home-" + uuid.uuid4().hex
    token = None

    def status():
        if clock() > deadline:
            raise TimeoutError("Home 시험 제한 시간 초과")
        current = client.rpc("status")
        if not current.get("ok") or current.get("session") != expected_session:
            raise RuntimeError("Home 도중 소유자/응답 변경")
        return current

    def measured():
        position = client.positions()
        check_values(position)
        if abs(position[0]-start[0]) > MAX_PAN_DISTANCE + 0.5:
            raise RuntimeError("Home 관측 이동량 초과")
        if any(abs(position[i]-start[i]) > TOLERANCE for i in range(1, 6)):
            raise RuntimeError("Home 도중 다른 관절 위치 변화")
        return position

    try:
        # 복사/카운트다운 중 정지를 재개 요청으로 덮어쓰지 않는다.
        for _ in range(20):
            current = status()
            if current.get("epoch") != expected_epoch or not current.get("stop_requested"):
                raise Interrupted("Home 시작 전 정지/모드 변경으로 취소")
            sleep(0.05)
        resumed = client.rpc("resume", session=expected_session, epoch=expected_epoch,
                             writer=writer, staff_confirmed=True)
        if not resumed.get("ok") or resumed.get("session") != expected_session:
            raise Interrupted("Home 재개 요청 거부")
        token = resumed["epoch"]
        for index in range(1, 61):
            current = status()
            if current.get("stop_requested"):
                raise Interrupted("Home 도중 정지 요청")
            if current.get("epoch") != token:
                raise Interrupted("Home 도중 제어 세대 변경")
            observed = measured()
            target = list(start)
            target[0] = start[0] + (end[0]-start[0]) * index / 60
            reply = client.rpc("action", session=expected_session, epoch=token, writer=writer,
                               sequence=index, target=target)
            if not reply.get("ok"):
                if reply.get("session") == expected_session and reply.get("stop_requested"):
                    raise Interrupted("Home 도중 정지 요청")
                raise RuntimeError("Home 목표 요청 거부")
            result["sent_targets"] += 1
            result["last_requested_target"] = target
            if index == 1 or index % 10 == 0:
                result["position_trace"].append({"sequence": index,
                    "requested_pan": target[0], "observed_pan_before_request": observed[0]})
            sleep(0.05)
        # 모터가 마지막 작은 목표에 도달할 시간을 제한적으로 관측한다.
        for _ in range(30):
            current = status()
            if current.get("stop_requested") or current.get("epoch") != token:
                raise Interrupted("Home 도달 확인 중 정지 요청")
            final = measured()
            if abs(final[0]-end[0]) <= TOLERANCE:
                result["result"] = "HOME_REACHED"
                break
            sleep(0.05)
        else:
            raise TimeoutError("Home 도달 오차 확인 실패")
    except Interrupted as error:
        result.update(result="HOME_STOPPED", reason=str(error))
    except Exception as error:
        result.update(result="HOME_ABORTED", reason=str(error))
    finally:
        try:
            reply = client.rpc("stop", session=expected_session)
            result["stop_requested_after_home"] = bool(reply.get("ok")
                and reply.get("session") == expected_session and reply.get("stop_requested"))
        except Exception as error:
            result.update(stop_requested_after_home=False, stop_error=str(error))
    if not result.get("stop_requested_after_home"):
        result.update(result="HOME_ABORTED", reason="종료 정지 요청 확인 실패")
        return result
    hold_deadline = clock() + 2
    while clock() < hold_deadline:
        try:
            current = client.rpc("status")
            if (not current.get("ok") or current.get("session") != expected_session
                    or not current.get("stop_requested")):
                raise RuntimeError("Home 종료 상태 변경")
            if current.get("hold_commanded"):
                result["hold_commanded_after_home"] = True
                final = client.positions()
                check_values(final)
                result["final_positions"] = final
                if result["result"] == "HOME_REACHED" and any(
                        abs(final[i]-profile["positions"][i]) > TOLERANCE for i in range(6)):
                    result.update(result="HOME_ABORTED", reason="유지 후 Home 오차 초과")
                return result
        except Exception as error:
            result.update(result="HOME_ABORTED", reason=str(error))
            return result
        sleep(0.05)
    result.update(result="HOME_ABORTED", reason="유지 명령 완료 확인 실패")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--epoch", required=True, type=int)
    parser.add_argument("--confirm-ready", action="store_true")
    parser.add_argument("--local-trial", action="store_true")
    args = parser.parse_args()
    if not args.confirm_ready or not args.local_trial:
        parser.error("실물 시험에는 --confirm-ready --local-trial이 필요합니다")
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8-sig"))
    client = Client()
    try:
        print(json.dumps(run_home(client, profile, expected_session=args.session,
            expected_epoch=args.epoch, confirmed=True, local_trial=True), ensure_ascii=True, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
