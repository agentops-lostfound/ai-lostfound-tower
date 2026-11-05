# 11/5 설치 좌표 변환 미리보기

> **잠정 구현 — 수정 가능성이 높음.** 실제 로봇 제어기의 원점·축 방향·단위·TCP 기준을 아직 확인하지 않았다. 현재 변환식, 설치 치수와 고정 접근 Z=280mm는 실물 연동 검증 결과에 따라 수정할 예정이다. 로봇 동작 검증이 완료된 구현으로 해석하면 안 된다.

사용자 실측: shoulder_pan 회전축 중심→보관함 입구106mm(이전100/104 대체), 입구 중앙 정렬, 내부 바닥은 설치면보다7mm 높음. 두 마커의 마주 보는 꼭짓점으로 만든324×150mm 직사각형은 입구에서 아래 긴 변까지37mm이고 좌우 중앙 정렬이다. 마커14mm 유지.

## 좌표 가정

실제 제어기 베이스 좌표는 아직 확인 전이다. 별도 `installation_shoulder_pan_mm` 프레임을 만들었다. 원점은 회전축 중심을 로봇 설치면에 수직 투영한 점, +X는 로봇 뒤에서 입구를 바라볼 때 오른쪽, +Y는 보관함 안쪽, +Z는 위다. 카메라 이미지의 축과 다르다.

고정된 트레이에서 ID0이 입구 쪽 오른쪽이라는 가정으로, 작업대 (14,14)인 공유 꼭짓점은 설치 좌표 (162,143)이다. 여기서143=106+37,162=324/2. 마커 작업대 +X는 로봇 왼쪽, +Y는 보관함 안쪽으로 대응시켰다.

```text
X_install = 176 - x_work
Y_install = 129 + y_work
```

확인점: ID0 공유 꼭짓점(14,14)→(162,143), ID1 공유 꼭짓점(338,164)→(-162,293), 기존 작업대 원점(0,0)→(176,129). 공유 꼭짓점까지 수평거리216.09mm. 이 설치값은 독립 TCP 접촉 보정이나 제어기 좌표 확인을 대체하지 않는다.

설정은 vision/configs/installation.yaml. 제안 접근Z280mm는 독립 설정이다. 바닥+7mm와 더하지 않으며 검출 물건 윗면Z를 측정했다는 의미도 아니다. controller_frame_verified=false. 원래 Adapter의 mm 허용 기준은 변경하지 않았다.

## 기존 사진에 대한 계산 시험

```powershell
$env:PYTHONIOENCODING='utf-8'
& ..\.venv-vision\Scripts\python.exe -m vision.installation_coordinates `
  --report outputs/vision/85fd0996652f44fa88051589bafa7e57/result.json `
  --output outputs/box_reach_review/installation_preview_20261105.json
```

위 사진은 09:21의 과거 장면이다. 계산 예시이며 현재 장면이나 이동 요청으로 쓰지 않는다.

| 관찰 물품 | ID | 설치 X,Y mm | 제안 접근Z mm |
|---|---|---|---|
| 오른쪽 폰 | 0 | (94.86,215.38) | 280 |
| 왼쪽 지갑 | 1 | (-58.52,210.30) | 280 |

기하 변환만 미리보기이므로 품목/매칭 상태와 무관하게 표시할 수 있지만 robot_authorized=false를 항상 유지한다. 실제 로봇·포트·모터에 접근하지 않았다. 다음에는 설치 방향·마커 관계를 현장에서 대조하고 실제 로봇 베이스 원점·축·단위·TCP 정의를 확인한 뒤 독립 대응점 보정·작업영역 검증을 진행해야 한다.

검증: 전체248개 실행,247통과·DB1스킵. 공유 브랜치: `LF-3-yolo-aruco`.

## YOLO 중심과 고정 Z 연결 구현

`vision/vision_pipeline.py`에서 결과 JSON에 `coordinate_context`와 `coordinate_chain`을 기록한다. bbox 중심 px를 다시 계산하고, 해당 사진의 homography로 작업대 XY mm를 구한 뒤 설치 변환과 고정 접근 Z를 적용한다. `run_pipeline.py`는 매칭 후보의 동일 object_id에 이 좌표를 연결한다. Qwen이 직접 좌표를 계산하지 않는다.

조정 파일은 `vision/configs/installation.yaml`이다. `work_xy_to_installation_xy.matrix`, `offset_mm`, `approach_z_mm`가 실제 변환값이다. `measurements_mm`는 실측 기록이므로 이 항목만 수정해도 변환식이 자동 변경되지는 않는다. 재설치 시 변환값을 함께 갱신하고 `config_version`을 올린다. 파이프라인에서는 `--installation-config`로 다른 설정을 지정할 수 있다.

설정 전체 스냅샷과 SHA256, 원본 마커 배치 스냅샷을 결과에 남긴다. 원본 배치가 없거나 다른 과거 결과는 `work_frame_unverified`로 표시하고 설치 좌표를 출력하지 않는다. 위의 과거 09:21 결과 표는 당시 수동 기하 계산 기록이며, 새 CLI 검증 대상은 09:33 사진으로 변경했다.

09:33 사진 재검출 결과: `outputs/vision/85fd0996652f44fa88051589bafa7e57/result.json`.

| 검출 ID | 설치 X mm | 설치 Y mm | 고정 접근 Z mm |
|---|---:|---:|---:|
| 0 | -101.99 | 229.92 | 280 |
| 1 | 46.12 | 212.56 | 280 |

마커 대응점 8개, 최대 재투영 잔차 0.339mm. 이 잔차는 실제 로봇 위치 오차를 검증한 값이 아니다. 두 좌표는 모두 `preview_only`, `robot_authorized=false`이다. 물체 높이로 인한 시차나 실제 집기 위치·작업영역 검증은 별도다.
