# 집기 준비 속도 개선 — 2026-11-11

## 적용 내용
- kinematics.Model.forward(with_points=False): IK 및 경로 검사 중 표시용 좌표 목록 생성 생략. 기본 호출의 points 반환은 유지.
- inverse residual에서 같은 q의 FK를 한 번만 계산해 위치/하향축/벌림축에 재사용. 해석 야코비안은 도입하지 않음.
- plan_path.solve는 양자화 후 위치/하향각/짧은축/관절 범위/roll_window를 모두 만족한 첫 자세를 반환.
- 후보 전체의 최소 관절 이동량 비교 대신 첫 유효 전체 경로에서 종료. 중간점에서 기존 목표를 재사용하되 전체 safe 검사 실패 시 해당 중간점을 seed로 목표를 다시 계산.
- safe의 301개 구간 샘플 및 허용 기준은 변경하지 않음. 별도 검증에서 좌·중·우 각 경로 1001개 샘플로 재확인.
- SIGN=[1,1,1,1,1], orientation_alignment rev3 유지. 캐시 불필요: 현재 세 기록 모두 1초 미만.
- OWLv2/SigLIP2 GPU 가중치/processor 캐시, 순차 추론 유지. Qwen 요청 전 캐시 해제.
- CUDA OOM 시 상주를 끄고 캐시/실패 추론 참조 해제 후 순차 방식으로 1회 재시도. 세션 중 상주 재활성화하지 않음. 순차 실행도 OOM이면 오류 보고.
- 임베딩 실패 시 부분 결과/콜백은 게시하지 않고 성공한 재시도 결과만 반영.
- GPU 모드 화면 설명, 로그와 health의 planner_revision/gpu_resident_enabled 추가.

## 경로 비교
동일 rev3, plane_z=15, robot_home.json, 동일 저장 입력. 시간은 이번 PC 실측이며 일반적인 모든 위치의 상한이 아님.

|위치/기록|변경 전|FK 중복 제거|탐색 개선 후|최종 roll|위치 오차|하향각 오차|짧은축 오차|
|---|---:|---:|---:|---:|---:|---:|---:|
|가운데 f4d4a1|24.1초|13.1초|0.1초|1301|0.27mm|0.088도|0.0도|
|오른쪽 ccfedd|2.0초|1.6초|0.8초|3534|1.31mm|2.021도|2.5도|
|왼쪽 49e7d8|24.1초|14.3초|0.1초|2937|0.13mm|0.001도 미만|0.0도|

세 기록 최종 roll/위치 오차는 변경 전과 동일. 가운데 inverse 368→2, forward 463549→2274. 중간점은 최종 물품 위치와의 오차로 평가하지 않음.

## GPU/서버 측정
저장된 detection-source.jpg, 검출 물체 4개, 검출+임베딩만 실행. 실제 팔 이동 없음.
- 독립 모델 실행: 첫 9.84초, 반복 0.838/0.834초.
- 최고 torch allocated 3298MiB, reserved 3860MiB. 반복 시 시스템 GPU 잔여 약920MiB. 여유는 다른 앱/입력에 따라 변동.
- 실제 서버 API, 사진 업로드 및 DB 비교/관측 저장 포함: 첫19.17초, 반복1.49초. 서버 측 관측 GPU 사용량5124MiB(전체 GPU, 연속 최고값 보장은 아님).
- 최초 로딩 및 Qwen 이후 재로딩은 여전히 발생. 전체 집기시간/물리 성공률 측정은 아님.

## 검증 및 적용
- 30개 임의 자세 FK 동일, IK 1e-9 rad 이내 일치.
- 관련 검사10개 통과: FK/IK, rev3 경로, OOM 재시도·중복 콜백 방지·Qwen 전 해제, 감지 중심 계획.
- 전체 기존 검사94개 실행에서 오류3개: 하나는 apply_alignment를 무시하는 mock을 수정하여 재검사 통과. 나머지 2개는 사전 보고된 test_stall_without_visual_contact_does_not_lift / test_home_preserves_gripper_and_segments_without_auto_open의 기존 오류이며 이번 최적화와 무관. 전체 통과로 보고하지 않음.
- 저장 경로 세 개 각각 1001샘플/구간으로 높이·하향각·관절 제한 통과.
- 유휴 상태 확인, 토크 변경 없이 serial 연결 종료 후 서버 재시작/재연결. health fast-first-valid-v1 및 SIGN 확인. 로봇 이동 명령 미실행.
- 자료: work/speed_review/before.txt, stage1.txt, after.txt, gpu.json, server_gpu.json, check_routes.py. 수정 전 소스도 같은 디렉터리에 보관.
