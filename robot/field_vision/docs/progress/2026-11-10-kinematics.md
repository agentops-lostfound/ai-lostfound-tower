# SO101 FK/IK 모델 미리보기

- 설치된 Studio 컨테이너의 SO101 URDF를 beta/assets/so101_follower.urdf에 복사하여 고정했다. 원본: /app/application/backend/.venv/lib/python3.13/site-packages/urdf/so101-follower/so101_follower.urdf. SHA256은 모델 API와 감사 파일에 기록한다. meshes는 표시하지 않고 관절 origin/axis/limit만 사용한다.
- beta/kinematics.py: URDF 순기구학(FK), 관절 제한을 적용한 수치 역기구학(IK), quintic 보간 모델 경로 계산. 별도 scipy 설치 없음.
- 기본 IK는 위치만 제약한다. ‘집게 수직 아래’ 옵션은 방향까지 제약하며 충분한 해가 없을 수 있다. 모델에서 해를 못 찾았다는 결과는 실물의 절대적 도달 불가능 판정이 아니다.
- 모델 원점은 shoulder_pan 회전축의 URDF 바닥 투영 기준으로 옮겼다. 측정한 전방이 모델 +X와 일치한다고 임시 가정한다. 실제 설치 yaw/높이 오프셋은 미검증이다.
- 임시 집게 기준은 gripper_frame_link다. 실제 집게의 닫힘 중심/TCP/카메라 부착물은 검증되지 않았다.
- 기존 실제 장비의 range_min/max는 normalized 입출력 범위이며, URDF 관절 영점/회전 방향을 보장하지 않는다. 임의 normalized→각도 환산을 추가하지 않았다.
- UI: 설정 하단 SO101 관절 계산·모델 미리보기. 5개 모델 각도 입력/FK, 대상 좌표 IK, 측면/탑뷰 모델 경로 표시.
- 경로는 모델 0도 자세에서 출발한다. 실제 현재 관절에서 출발하는 경로가 아니고 충돌 검증을 하지 않았다. 실제 이동 어댑터는 미구현이며 모든 결과 motion_sent=false, robot_ready=false.
- 모델 각도를 실제 모터에 입력하면 안 된다. 다음 단계는 실제 관절 영점·회전 방향·TCP와 기준 좌표축을 맞추고 독립 측정으로 검증하는 것.
- 검증: 38개 unittest 통과. 실제 서버 FK/IK API에서 목표 (181.75,-2,95)mm의 위치 계산 수렴 확인. 실제 장비는 SDK 읽기로만 6축 상태 재조회했으며 토크/목표 위치 쓰기 없음.
- 순기구학/역기구학 오차는 모델 내부 수치 오차이지 실제 팔 위치 정확도가 아니다.
