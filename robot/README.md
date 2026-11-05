# robot

**현재 운영 결정(2026-11-05): 미리 티칭한 커스텀 자세 5개를 선택해 이동한다.** YOLO 중심/XYZ로 모터값을 자동 계산하는 IK·Cartesian 제어 개발은 중단했다. 기존 `home`, `raised`, `entry`, `observe`를 보존하고 새 `pose_1`~`pose_5`를 기록해 GUI의 **커스텀 1~5** 버튼에 연결했다. 버튼은 미리보기이며 이동은 기존 단계별 승인 절차를 거친다. [결정 및 사용 절차](../docs/reports/2026-11-05-fixed-pose-decision.md).

오늘의 모델 변경·티칭·GUI 시험·실물 연결 결과와 남은 작업: [2026-11-05 작업 정리](../docs/reports/2026-11-05-daily-update.md).

버튼형 티칭 GUI: [검증 결과와 실행법](../docs/reports/2026-11-05-teaching-gui-verification.md). 기본은 Simulation이다. Studio v4 패치는 이전에 설치됐지만 저장 자세의 실물 이동은 검증 중이다.

기존 키보드 제어 패널: [실행 방법과 키 설명](README-panel.md).

본센터 로봇팔 SO-101 (LF-11·12): 보관함 보관·수령대 전달, 반환 안전 규칙(승인 기록 없으면 정지)
