# Studio 좌표 연결 조사·오프라인 목표 출력 (2026-11-05)

> **후속 운영 결정: 좌표 기반 자동 관절 계산 중단.** 사용자 결정으로 현재는 `home/raised/entry/observe` 등의 저장 자세 약 5개를 티칭하여 사용한다. 아래 XYZ·IK 관련 내용은 조사·실험 이력이며 현재 구현 우선순위나 실행 절차가 아니다. GUI의 저장 관절 자세 이동을 사용하고 다섯 번째는 실물 티칭 후 추가한다. [고정 자세 전환 결정](../reports/2026-11-05-fixed-pose-decision.md)을 우선한다. 기존 코드·실험 자료는 보존했고 좌표 계산을 실물 실행에 연결하지 않는다.

> 실물 연결 후속: 사용자 팔 준비·세션 정지/재시작 승인 후 v4 패치를 실제 실행 컨테이너에 적용했다. 가짜 관측 통합시험(명령 파싱·hold 스텝·stop·repair·API라우트 import)과 실측 관절6개 수신을 확인했다. OpenCV SO101 - LIVE 창을 실행하고4개 저장자세를 불러왔다. 자동 이동 목표는 보내지 않았다. 초기 미설치/의존성 미설치 표기는 아래 과거 작업 기록이다. 현재 실행법·백업·주의는 robot/README-panel.md를 우선한다.

## OpenCV 제어 패널 추가

최신 사용법은 robot/README-panel.md. robot/control_panel.py, panel_core.py, panel_transport.py 추가. 모의 모드의 관절 표시·목표입력·자세 저장/선택·단계별 확인·속도3단계·소프트웨어정지/상태복구·CSV 기록을 구현했다. 그리퍼 이동은 잠금이다. 리페어는 상태 재확인·목표 초기화이며 기구 수리/재보정/이동 재개가 아니다.

새 패치는 outputs/studio_panel_patch_v3에 생성했다. 앞선 v1/v2에는 패널 전용 attach-only endpoint와 stop/repair가 없어 호환되지 않는다. v3는 기존 runtime만 연결하고 직접 serial 연결·새 runtime 생성·camera claim을 하지 않는다. 한 팔에 수동 패널1개 제한이 있지만 기존 Studio 창의 조작까지 독점 잠그지는 않는다. 패널은 다른모드 전환/관측노후/에러에 승인 상태를 해제한다.

실물 패치는 미설치, websocket-client는 기존 비전환경에 미설치 상태다. 전용 패널환경 설치 명령만 문서화했다. live 연결·정지 명령·실물 이동 통합시험은 아직 하지 않았다. 모의 UI PNG 렌더와 테스트272개 중271통과·DB1스킵을 확인했다. 실물 승인이나 경로검증으로 해석하면 안 된다.

## Studio 패치 준비 (설치 전)

robot/stage_studio_patch.py가 실제 설치 소스의 정확한 anchor를 확인하고 별도 폴더에만 패치를 생성한다. outputs/studio_manual_joint_patch_v1/manifest.json에 원본/패치 SHA256 기록. 실행 중인 Studio 소스와 세션은 변경하지 않았다.

새 set_manual_joint_target 명령은 hold+stage_approved에서만 처리하며, 6관절 이름·normalized 범위·현재값 일치·추종오차를 검사한다. 한 명령의 hold 목표 변화는 최대0.25 normalized, 간격은 최소0.1초이며 그리퍼는 유지한다. runtime이 원래 사용하던 action source의 hold 목표만 갱신하므로 별도 모터 publisher를 만들지 않는다. 명령이 끊기면 마지막 hold 목표가 유지되는 구조이며 비상정지/토크해제를 대신하지 않는다. 충돌 감지는 아니다.

패치 설치에는 실행 세션 정지와 백엔드 재시작/배포 방식 확인이 필요하다. 팔이 hold 중인 상태에서 임의 재시작하지 않는다. 사용자 준비 확인 후 원본 백업·해시 재검증·패치 적용·컨테이너 소스 반영 여부 확인·소프트웨어 시험을 진행한다. 그 후에도 실제 이동은 별도 단계 승인 전 실행하지 않는다. 아직 실행 클라이언트의 승인/관측확인/중단 루프 통합 시험이 남아 있다.

현재 전체264시험 중263통과·DB1스킵. 새 handler는 가짜 관측으로 정상 스텝/모드·승인·큰변화·그리퍼 변경 거부/과속 거부를 검사했다. Studio 실제 세션 통합 시험 완료를 뜻하지 않는다.

## 관절값 이동 로직 (실물 전송 연결 전)

robot/joint_motion.py는 normalized 단위의 시작·목표를0.5단위 이하/10Hz 이하로 보간한다. 단계별 승인, 제어권 확인, 시작값 불일치/추종 오차 검사, 취소 시 현재 자세 유지 요청을 포함한다. 그리퍼는 접근 시 유지한다. 이는 명령 변화율 제한이며 실제 관절 속도·충돌 안전을 보장하지 않는다.

실물 transport는 아직 구현하지 않았다. Studio runtime hold도 계속 명령을 발행하므로 SharedRobot에 별도 publisher로 붙는 것만으로는 제어권이 확보되지 않는다. send_action은 fire-and-forget이며 disconnect도 정지를 뜻하지 않는다. 따라서 has_exclusive_control/read_normalized/send_normalized/hold_current 계약을 실제 runtime action source와 연결하기 전에는 실행할 수 없다. 현재 단계는 오프라인 계획 및 가짜 transport 시험이다.

기록된 observe→entry 스냅샷의 예비 계획은 outputs/robot_poses/observe_to_entry_plan.json. 최대0.5 normalized/회,10Hz,예상17초. 현재 관절값 재조회와 경로 확인 전에는 사용할 수 없다. 전체260시험 중259통과·DB1스킵. 로봇에는 이동 명령을 보내지 않았다.

## 사용자 지정 접근 순서·자세 수집

접힌 home → 위로 펼치는 raised → 팔꿈치를 굽혀 안쪽으로 진입하는 entry → 손목4번 보정을 포함한 observe 순서다. 아직 경로 실물 검증이나 자동 재생을 구현한 것은 아니다. 마지막 관측 자세에서 TCP 목표를 맞춰야 하며 손목 보정이 XYZ를 바꾸는 효과를 무시하지 않는다.

사용자가 리더로 자세를 잡고 Studio에서 Teleoperate를 끄면 기존 runtime의 hold를 확인한 뒤 아래 명령으로 관절값5회를 읽는다. 스크립트는 모터 명령·토크·모드 변경을 하지 않는다. 출력은 로컬 outputs/robot_poses/시각_자세/pose.json이며 매번 별도 저장한다. 관절값 변동1 normalized 이내 여부는 관측 안정성일 뿐 충돌 검증이 아니다. 카메라 별도 preview가 검은 프레임인 문제가 있어 동기 사진은 아직 포함하지 않는다.

```powershell
powershell -NoProfile -File robot/record_pose.ps1 -Pose home
# 이후 자세를 각각 직접 잡은 뒤 raised / entry / observe로 별도 수집
```

## 턱 실측 추가

사용자 실측: 내부 바닥부터 턱 윗면114mm, 턱 두께14mm. 기존 내부 바닥이 설치면보다7mm 높다는 실측과 같은 기준이면 턱 윗면은 잠정 설치Z=121mm다. 설정 버전2026-11-05.2에 기록했다. 두께가 차지하는 XY 구간과 방향, 턱 전체 길이는 미확정이다. 자동 충돌 검사나 모터2 단독 제한을 구현한 것은 아니다. 고정 접근Z280mm는 그대로 잠정값이며, TCP가 턱보다 높아도 다른 링크가 턱에 닿을 수 있다. 접촉 실험은 하지 않는다.

> 후속 확인: 실제 모델은 site-packages/urdf/so101-follower/so101_follower.urdf에 존재한다. 아래 초기 조사에서 미발견이라고 한 범위는 플러그인 폴더 내부였다. 로컬 outputs/robot_ik/에 실험 복사본을 저장했다.

실제 설치 소스 /home/user/physical-ai-studio 커밋 f071fe6과 실행 컨테이너 physical-ai-studio-cuda의 physicalai_so101_plugin0.2.0 소스를 읽어 확인했다. 이번 작업에서 연결·토크·모터 명령은 호출하지 않았다.

## 확인한 제어 경로

- backend/src/robots/catalog/so101.py와 설치 플러그인의 studio_catalog.py는 보정된 SO101을 unit=normalized로 생성한다.
- backend/src/robots/physicalai_adapter.py의 set_joints_state는 관절 이름별 `<joint>.pos`를 배열로 바꾸고 send_action에 전달한다. XYZ를 받는 함수가 아니다.
- 설치 플러그인 so101.py의 몸통 관절 범위는 -100..100, gripper는0..100이다. 각 관절의 실측 range_min/max에 따라 ticks로 선형 변환한다. 정규화 값100을100도라고 해석하면 안 된다. URDF 영점/부호와 실측 보정의 대응은 별도 검증해야 한다.
- 같은 send_action은 goal_time을 무시한다고 명시한다. 이 인자만 늘려서 저속 이동을 보장할 수 없다. 이후 속도 제한·보간·중단 처리를 실제 제어 경로에서 검증해야 한다.
- backend/src/api/robot_observations.py는 읽기 전용 SharedRobot WebSocket 관측 API를 제공한다. 다만 연결 시 owner 동작을 확인하지 않은 상태에서 이번 작업에서는 실제 구독하지 않았다.
- 현재 조사한 backend 및 설치 SO101 플러그인에서 XYZ IK 구현을 찾지 못했다. URDF는 카탈로그에 asset 경로로 등록돼 있지만 조사한 소스/플러그인 디렉터리에서 실제 파일은 발견하지 못했다. 시스템 전체에 IK/모델이 없다고 확정한 것은 아니다.
- Studio runtime은 hold/teleop/policy의 action source를 선택한다. 기존 세션 소유권을 무시하고 별도 serial 제어를 연결하지 않는다.

## 구현된 연결 단계

`robot/prepare_target.py`가 특정 object_id의 bbox→작업대→설치XYZ와 설정 근거를 JSON으로 출력한다. 네트워크·serial·모터 라이브러리를 사용하지 않는다. 모션 명령은 생성하지 않으며 joint_targets=null, robot_authorized=false다.

```powershell
& ..\.venv-vision\Scripts\python.exe -m robot.prepare_target `
  --report outputs/vision/62b6e6e43b324206b22e3385a710cd31/result.json `
  --object-id 0 `
  --output outputs/robot_target_preview/target_0.json
```

저장 사진의 ID0(보조배터리)을 예시로 지정했다. Qwen/매칭이 선택한 최종 후보가 아니다. 출력 설치XYZ는 (6.156,209.461,280)mm, 지위는 preview_only다. 실제 로봇 도달을 의미하지 않는다.

## 남은 연결

1. 실제 모델 asset과 base/TCP 프레임, 관절 영점/부호 대응 확인.
2. 설치 프레임→모델 base 변환 및 고정Z 검증.
3. IK 계산 후 FK 잔차·관절 범위 확인, normalized 변환 검증.
4. Studio의 세션 소유권을 유지하는 모션 전송 경로 구현과 속도·중단 검증.
5. 사용자 준비 확인 후 실물 접근 시험. 현재는 실행 단계 미연결이다.

테스트251개 실행,250통과·DB1스킵. 커밋·푸시는 이번 요청에 포함하지 않았다.

## 실제 설치 모델의 오프라인 IK 추가

`robot/offline_ik.py`는 URDF의 origin XYZ/RPY, axis, 관절 한계를 읽어 FK와 위치 전용 수치 IK를 계산한다. 입력은 명시적으로 URDF base_link 기준 mm이며, 출력 관절값은 URDF radians다. normalized 모터값으로 자동 변환하거나 실행하지 않는다. gripper_frame_link까지의 체인에는 이동 그리퍼 관절이 포함되지 않으므로 그리퍼 열림 명령도 만들지 않는다.

```powershell
& ..\.venv-vision\Scripts\python.exe -m robot.offline_ik `
  --urdf outputs/robot_ik/so101_follower.urdf `
  --base-xyz-mm 200 0 280 `
  --output outputs/robot_ik/model_test.json
```

이 목표는 물체 좌표가 아니라 모델 검증용 임의 점이다. IK→FK 위치 잔차0.0703mm로 해를 찾았다. 실물 오차·자세 적합성·충돌·경로 유효성을 검증한 결과가 아니다. 자세는 자유이므로 바로 집기/접근에 사용할 수 없다. 수치 IK의 no_solution_found는 수학적 도달 불가능 증명이 아니다.

모델 shoulder_pan 원점은 base_link에서 (38.8353, 약0, 62.4)mm에 있다. 우리가 정의한 설치 원점은 회전축을 설치면에 투영한 점이므로 두 원점을 같다고 놓지 않는다. 모델의 base 높이 기준·설치 방향과 실제 관절 영점/부호를 대응하는 작업이 남는다. 실측 대응 없이 임의로 설치XYZ를 모델 입력에 넣지 않는다.

모델 SHA256: 3a65d2d35e68a8d2f0c2cc176d19b884506543c93ba72980145b80abe276022c.
추가 검증: 해석적으로 계산 가능한 별도1관절 모델로 FK/IK/한계/도달 실패를 시험. 전체255개 실행,254통과·DB1스킵. 로봇에는 명령을 보내지 않았다.
