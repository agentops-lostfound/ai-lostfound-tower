# 실제 SO101 연결 1단계

- Studio localhost:7860 / Docker physical-ai-studio-cuda 정상 확인.
- 현재 대상은 so101_new_pair의 New SO101 Follower, 시리얼 팔로워 일련번호. 다른 프로젝트의 동일 시리얼 중복 등록과 이전 장비 5B3D044791를 자동 선택하지 않는다.
- Studio 관측 WebSocket은 SharedRobot 소유자를 새로 만들 수 있고, 설치 드라이버 connect()는 PID/서보 설정/토크를 변경한다. 초기 조회에서는 사용하지 않았다.
- 대신 컨테이너 안에서 SDK read1ByteTxRx/read2ByteTxRx만 사용하는 단발 진단을 구현했다. position 56, torque 40 레지스터만 읽는다. 목표 위치/토크/보정값 쓰기 없음.
- runtime 세션이 있거나 다른 프로세스가 직렬 장치를 열고 있으면 직접 조회를 거부한다. 지속 제어 연결은 아직 구현하지 않았다.
- 실제 6축 응답·기존 보정 범위 확인. 최초 확인 시 토크 6축 모두 OFF. 최초 감사 결과는 work/robot_connection_audit.json.
- normalized는 기존 range_min/range_max에 따른 범위 정규화이며 로봇 각도나 mm가 아니다. 범위 밖 값을 클램프해 숨기지 않는다.
- UI: 관측 하단 SOARM 실제 연결 패널. 단발 조회 시각과 상태 표시. 자동 직렬 polling 없음.
- API GET /api/robot/status, POST /api/robot/probe. 외부 서비스 등록 변경·기존 보정 수정·학습 시작 없음.
- 검증: 30개 unittest 통과, 실제 장비 단발 조회 및 서버 API 검증.
- 다음: 보관함↔로봇 기준 보정, 로봇 모델의 관절↔각도 정합, IK 및 작업 공간/어프로치 경로 검증. 이후 실제 이동 어댑터 구현. 가상 보관함 mm/임의 관절값을 실제 이동에 사용하지 않는다.
