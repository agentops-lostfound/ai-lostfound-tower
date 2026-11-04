# LF-11·12 관제탑 변경 확인 및 로봇 부품 작업 브리핑

2026-11-04 · origin/main `413d05b` 코드·문서 조회 기준. pil2ya 유지, main 병합·로봇 구동·배포 없음.

## Git 반영 확인

main 이력에서 PR #40(ac43942), #41(49d3200), #43(3c6a6f7), #44(fa513b1), #45(d012ec2) 병합을 확인했다. 그 후 #46·#47도 병합돼 있어 공유 메시지보다 최신이다. 아래는 업로드 여부와 실제 장비 구현을 구분한 검토다.

| 공유 결정 | 확인한 파일·코드 | 판정 |
| --- | --- | --- |
| robot_approach(center_mm, center_px), mm 없으면 미동작 | agents/backends.py Protocol, agents/supervisor.py approach의 valid_point_mm 검사·실패 시 staff_check | 관제탑 구현 반영. 실제 mm→로봇 변환 부품은 별도 |
| 좌상단 원점·우하단 ArUco 총2개 | docs/design/swap_guide.md 4장에 배치 기록 | 배치 문서 반영, ID·길이·실측값 TBD |
| 2개 모두 보여야 보정 유효 | vision/aruco/calibration.py는 대응점4개 이상 검사, configs/vision.yaml markers_mm={} | 코드 강제 미반영. 단일 마커4코너도 통과 가능. 사용자 전달의 최신 결정에 맞춰 LF-3/21 담당 반영 필요 |
| stop 즉시 정지·home 별도 | agents/backends.py, tools.py, service.py, api.py /robot/stop·/robot/home | 계약·모의 부품·관제탑 API 반영. 실물 중단 구현 미확인 |
| 반환중→인계대기→직원확인 인계완료/보류 | supervisor.deliver, service.handover/hold_handover, contracts, DB 문서 | 관제탑 반영 |
| STT→Qwen→VLA GPU 사용권 | agents/gpu_lease.py, vision/sequence.py, supervisor.approach·service.GuardedBackend | 파일 잠금 및 Qwen 프로세스/VLA 관문 반영. 모든 실제 실행경로 참여·메모리 해제는 별도 확인 |
| YOLO26n·Qwen3-VL-2B | vision 설정·qwen 모델 설정 및 통합 문서 | 현재 기준 일치 |
| LLM 2차 검토 CPU | agents/llm_reviewer.py MAIN_AI_DEVICE=cpu일 때 options.num_gpu=0 | CPU 경로 구현. 기본값은 gpu이므로 시연 환경 설정 확인 필요. 3.8초는 팀 보고 실측, 여기서 재측정하지 않음 |

## 네 담당 LF-11·12에서 구현할 것

### 1. robot_stop

- 현재 위치에서 추가 이동을 중단하고 Home 이동을 시작하지 않는다. 정지와 무조건 torque OFF를 동일시하지 않는다. 전원/토크 제거 시 팔·물품 낙하 가능성을 고려한다.
- 접근·집기·전달이 실행 중에도 별도 호출에서 중단이 가능해야 한다. 긴 동작이 끝난 뒤 stop을 받는 구현은 요구를 충족하지 않는다.
- 관제탑의 stop_event는 이후 동작 요청을 막지만, 이미 부품 내부에서 실행 중인 동작을 물리적으로 중단하는 책임은 실제 로봇 부품에 있다.
- backend_factory가 실행·정지에서 별도로 호출되므로 같은 실제 컨트롤러/취소 신호를 공유해야 한다. 정지 요청이 이동 루프와 같은 긴 잠금을 기다리지 않도록 설계한다.
- 테스트: 모의 명령 기록 → 접근 중/집기 중/전달 중 중단 → 정지 뒤 새 명령 차단·재시도 금지 → 통신 실패 처리. 실물 시험은 준비 상태와 조작 화면 확인 후 별도 진행한다.

### 2. robot_home

- robot_stop과 별도 함수, 반환값 {ok, reason}. 직원 주변 확인 후 API 버튼 경로로 요청한다.
- 관제탑은 반환 실행 중 home 요청을409로 막고 staff_confirmed=true를 요구한다.
- Home은 저장된 안전 자세/경로다. 작업대 좌표원점(좌상단 마커), 관절 호밍/캘리브레이션과 혼동하지 않는다.
- 물체 보유·장애물·현재 자세를 고려해 검증한 경유점으로 이동한다. Home 도중에도 stop이 작동해야 한다.

### 3. 정상 바구니 전달 후 팔 위치 — 결정 미완료

선택지는 제자리 유지 또는 검증된 대기 자세로 이동이다. 제안은 물품 놓기/그리퍼 분리 확인 후 사람의 수령 동선을 벗어나도록 짧은 안전 이탈→전용 대기 자세다. 다만 실제 바구니·로봇 배치/도달범위를 확인하기 전 확정하지 않는다. 정상 전달 경로의 이탈·대기와 비상정지 뒤 직원 요청 robot_home은 별도다. 자동 Home 복귀를 몰래 추가하지 않는다.

바구니에 놓아도 상태는 인계 대기다. 직원이 실제 분실자에게 건넨 후 인계 완료이며 건네지 않으면 반환 보류다. 손가락/팔이 수령 공간에서 빠졌는지와 물품 놓기 성공 판정을 함께 협의한다.

## LF-3·19·21과 맞출 항목

- 마커2개 모두 관측, 고유 ID·크기·원점 기준점(중심/모서리)·축·실측 mm 좌표 확정. 한 개 가림/누락 시 calibration_valid=false·mm=null로 막는 코드와 시험이 필요하다. 두 마커의 재투영 오차 통과만으로 작업대 전체 실제 정확도를 보장하지 않아 독립 실측점을 검증한다.
- center_mm은 작업대2D 좌표이고 로봇 베이스 변환·z 높이·접근 방향·파지점·도달범위는 별도다. 픽셀을 모터 좌표로 직접 쓰지 않는다.
- 집기 정책과 성공 판정·재시도 후 위치 재확인·명령 중단 경로를 공동 검증한다.
- 시연 GPU 순서는 STT 해제→Qwen 해제→VLA다. 모든 프로세스가 같은 GPU_LEASE_FILE을 사용해야 하며 Windows/WSL/컨테이너에서 서로 다른 임시 폴더/OS 잠금을 쓰면 하나의 열쇠가 되지 않을 수 있어 실행 위치를 맞춘다.

## 기존 속도 실험과 새 운영 규칙

pil2ya의 Qwen 상주 도구는 독립 사진 성능 시험용이다. gpu_lease와 명시적 unload/재획득이 없고 로더 lru_cache 및 bundle이 모델 참조를 유지한다. 단순 del model·empty_cache만으로 활성 참조가 해제되는 것은 아니다. 실행을 유지한 채 vla 열쇠만 넘겨 GPU를 공유하면 안 된다.

운영 연결 전에 qwen 열쇠 획득→분석→캐시/모델 참조 해제 또는 소유 프로세스 종료→메모리 확인→열쇠 반납을 설계한다. 긴 상주 세션이 열쇠를 계속 잡으면 STT·VLA가 대기하므로 공정한 인계도 필요하다. Ollama는 stop/keep_alive로 서버 측 unload까지 확인해야 한다. CPU YOLO 상주는 GPU를 점유하지 않아 별도로 유지할 수 있다. 기존 약5.68초는 VLA 전환·자원 해제/재로딩을 포함한 운영 시간으로 보고하지 않는다.

현재 photo 시험용 resident_result.json은 main의 파일 어댑터가 찾는 result_with_qwen.json과 이름/메타데이터 경로가 달라 자동 운영 연결 완료가 아니다. 팀 최신 captured_at/GPU 잠금 경로를 맞춘 명시적 어댑터 검토가 필요하다.

## 문서 정합성과 참고

- docs/design/swap_guide.md: 부품 교체 절차·6개 로봇 함수·모의→실물 검증. 다만 마커2개 동시 가시성은 아직 검토 중으로 적혀 있어 사용자 최신 확정 메시지와 차이가 있다.
- docs/design/gpu_lease.md: 사용권·메모리 인계 규칙.
- docs/design/vision-robot-integration-plan.md·docs/handoff/2026-11-04-context.md에는 단일 마커 시작·옛 계약 제안이 남아 있다. 최종 사용자 결정 및 최신 코드/계약을 우선하고 담당자와 문서를 정리해야 한다.
- Jira LF-22~34 범위는 최신 AGENTS/CLAUDE에서 확인했지만 개별 업무 제목·담당·상태는 Git만으로 확인하지 못했다. 이 검토에서 Jira를 조회/변경하지 않았다.
- 최신 main 규칙은 브랜치 LF-번호-이름-설명, CI 통과 후 요청 팀원이 병합(승인 필수 아님)으로 바뀌었다. 이 채팅은 사용자의 명시 지시에 따라 pil2ya에서만 커밋·푸시한다.

다음 실제 작업 순서: 최신 main 기준 무동작 로봇 부품/취소 구조 설계→정지·Home 분리 시험→정상 전달 후 대기 위치 합의→부품 교체 시험→사용자 준비 확인 후 제한된 실물 시험. 이 기록 자체로 로봇을 새로 구동하지 않는다.
