# LF-21 로봇 PC 읽기 전용 관절 조회

재원님 관제탑 `/live` 가 단계 이름뿐 아니라 실제 팔로워 관절값으로 가상 팔을 그리기 위한 추가 API다. 관제탑의 `robot_state()` 연결과 그림의 영점·부호 변환은 관제탑에서 담당한다. 이 변경은 `vision/` 및 Qwen 프롬프트를 수정하지 않는다.

## 확정 응답

`GET http://10.10.21.30:8767/v1/joints`, 기존 원격 실행기와 같은 Bearer 토큰 및 IP 허용 목록을 사용한다. 브라우저에서 직접 호출하지 않고 관제탑 서버에서 최대 5 Hz(200 ms 간격)로 조회한다. 인증 실패는 기존처럼 403, 정상 인증 후 관측 부재·끊김은 HTTP 200과 `available: false`다.

```json
{
  "available": true,
  "instance": "원격 실행기의 현재 instance",
  "unit": "normalized",
  "positions": {
    "shoulder_pan.pos": -3.5976505279541016,
    "shoulder_lift.pos": -99.32942199707031,
    "elbow_flex.pos": 99.36851501464844,
    "wrist_flex.pos": -98.38298034667969,
    "wrist_roll.pos": 9.743589401245117,
    "gripper.pos": 4.438466548919678
  },
  "degrees": {
    "shoulder_pan.pos": -4.3076923076923075,
    "shoulder_lift.pos": -104.17582417582418,
    "elbow_flex.pos": 96.83516483516483,
    "wrist_flex.pos": -101.62637362637362,
    "wrist_roll.pos": 17.53846153846154,
    "gripper.pos": 4.438466548919678
  },
  "read_at": "2026-11-11T08:34:35.144062+00:00",
  "source": "studio_observation"
}
```

위 숫자는 실제 관측 예시이며 저장된 `home` 목표값과는 다르다. `positions`는 **팔로워 관측**이며 리더 관측이나 명령 목표값이 아니다. 팔 5축 normalized 범위는 -100~100, 집게는 0~100이다. `degrees`의 팔 5축은 `VendorCoordinates.degrees()`의 Studio/LeRobot 관례를 그대로 사용한다. **집게는 degrees 안에서도 0~100이며 도 단위가 아니다.** 관제탑 그림의 영점·부호·링크 길이는 여기서 바꾸지 않는다.

`read_at`은 로봇 PC 시계 기준 관측 시각 추정치(UTC ISO 8601)다. 구독기의 샘플 나이와 IPC 왕복시간을 반영해 보수적으로 계산한다. Windows/WSL 시계 차이에 영향받지 않으며 센서 자체의 하드웨어 타임스탬프가 아니다. HTTP 요청 시각으로 갱신하지 않는다. 1초 이상 오래된 샘플, 불완전한 6축, 연결 끊김은 아래처럼 표시한다. `available:false`일 때 이전 그림을 새 관측으로 처리하지 않는다. 실행기 재시작·arm에 따른 `instance` 변경은 기존 계약과 같다.

```json
{"available": false, "instance": "...", "reason": "Studio observation is stale"}
```

## 제어와의 분리

- 구독기 하나가 이미 실행 중인 Studio의 loopback IPC tick을 받아 최신 샘플 하나만 보관한다. serial·카메라를 열거나 런타임을 시작하지 않는다.
- 구독기에는 command publisher, runtime apply/request, 토크·모드·hold 목표 변경 경로가 없다. Windows 읽기 스레드는 구독기 자체의 캐시를 `sample`로 조회하며 Studio에 명령을 보내지 않는다. 한 번에 한 요청만 두어 지연된 응답도 검출한다. 종료도 이 구독기의 IPC 연결만 닫는다.
- HTTP 요청은 별도의 짧은 캐시 락만 사용한다. 실행기 제어 락, readiness, arm, backend 생성, job 제출, heartbeat, stop을 호출하지 않는다. DISARMED 및 시퀀스 실행 중에도 조회할 수 있다.
- 구독이 실패하면 관측만 unavailable이 된다. 진행 중 job·lease·실제 동작과 정지 보호를 바꾸지 않는다. 구독은 최대 10 Hz로 캐시에 전달하며 요청 수에 따라 연결을 추가하지 않는다.

## 로봇 PC 실행 설정

기존 `python -m robot.remote_executor --live ...` 인수에 `--joint-calibration <파일>`을 추가한다. 파일은 현재 팔로워의 기존 보정값을 읽어 만든 사본이며, 쓰거나 새로 보정하는 기능은 없다.

```json
{
  "follower_id": "bc50f050-d0a5-4430-af97-0486cdaec3a2",
  "calibration": {
    "shoulder_pan":  {"drive_mode": 0, "range_min": 757,  "range_max": 3481},
    "shoulder_lift": {"drive_mode": 0, "range_min": 891,  "range_max": 3277},
    "elbow_flex":    {"drive_mode": 0, "range_min": 704,  "range_max": 2921},
    "wrist_flex":    {"drive_mode": 0, "range_min": 990,  "range_max": 3340},
    "wrist_roll":    {"drive_mode": 0, "range_min": 0,    "range_max": 4095},
    "gripper":       {"drive_mode": 0, "range_min": 2011, "range_max": 3498}
  }
}
```

2026-11-11 실제 Studio GET 로봇 정보의 `payload.calibration`과 대조한 값이다. 보정 파일 미지정·유효하지 않은 보정·다른 팔로워·지원하지 않는 drive mode이면 normalized 관측은 계속 제공하고 `degrees:null`로 둔다. 새 보정을 실제 적용한 경우 사본을 갱신하고 실행기를 유휴 상태에서 재시작한다. 측정치가 보정 범위를 벗어난 경우도 관측을 억지로 잘라내지 않고 degrees만 null로 둔다.

팔 5축 변환식(집게 제외):

```python
tick = round(range_min + (normalized + 100) / 200 * (range_max - range_min))
degrees = (tick - (range_min + range_max) / 2) * 360 / 4095
```

## 저장 자세와 칸 확인

2026-11-11 조회 시 `outputs/robot_panel_live/poses.json`의 **36개 자세 전부**가 Studio 설치본 `runtime/saved_poses.json`의 동명 자세와 값까지 일치했다. 설치본 43개 중 나머지 7개는 운반용 파생 자세다. 실시간 그림은 고정 보정·집게 유지 등이 적용된 실제 관측을 따라야 한다.

| 자세 | 의미 |
|---|---|
| pose_1 / pose_2 | R1-1 / R1-2, 휴대폰 |
| pose_3 / pose_4 | R2-1 / R2-2, 보조배터리 |
| pose_5 / pose_6 | R3-1 / R3-2, 핸드크림 |
| pose_7 / pose_8 | R4-1 / R4-2, 립밤 |
| pose_N_open → pose_N_target → pose_N_close | 해당 칸에서 열기 → 접근 → 집게 닫기 |
| outlet_return_1 | 제출보관함 위쪽 이동 경유 자세 |
| 공통 close → open | 집게를 닫은 상태로 제출보관함 쪽으로 내림 → 집게 열기 |

`pose_N_close` 도착은 닫기 단계 완료이지 실제 물건 집기 성공을 센서로 확인했다는 뜻은 아니다. `open` 도착 역시 물건의 실제 안착을 검증하는 신호는 아니다. `outlet_return*` 모든 이름을 무조건 동일한 위치로 간주하지 말고 현재 시퀀스에서 사용하는 `outlet_return_1`을 기준으로 한다.

## 검증

관측 구독 실물 확인에서 10개 샘플의 normalized/degrees를 받았으며, 전후 Studio 런타임 PID·시작 시각·activity가 유지됐다. 로봇 이동 명령 없이 확인했다. 단위 시험은 인증, 관측 부재·끊김·오래된 값, 각도 변환, 런타임 세대 구분, 제어 락 점유 중 응답, 실행 중 job·lease 보존을 포함한다.

`python -m unittest discover -s tests`: 1,586개 실행, 성공(환경 조건으로 23개 건너뜀). 관절 API 및 기존 원격 실행기 관련 43개 시험도 통과했다.

서버 반영 후 실제 `/v1/joints`를 5 Hz로 20회 조회해 전부 available/6축/degrees 및 서로 다른 관측 시각을 확인했다. 조회 전후 executor instance·arm·job 상태가 유지됐다. 실행기 교체 전후에도 Studio PID·activity를 유지했으며 기존 arm=true, 이동 3초 설정을 복구·확인했다. 로봇 이동 명령은 보내지 않았다.
