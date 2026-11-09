# Physical AI Studio 저장 자세 통합

2026-11-09 현재 **Studio에 설치·재시작하고 팔로워·리더·두 카메라의 runtime 재연결을 확인**했다.
저장 자세 이동·복귀를 실물로 시험하면서 보완했으며, 최신 3·4·5초 선택의 실물 소요 시간은 별도 확인이 필요하다.
자세한 현재 상태와 백업 위치는 [설치 결과](../../docs/reports/2026-11-06-studio-pose-installed.md)를 따른다.

## 동작

Studio 녹화 화면과 Model Run 화면에 저장 자세 컨트롤을 추가한다.
기존 RuntimeSession/StudioActionSource가 로봇·카메라를 계속 소유하고 같은 update 루프에서 명령을 전환한다.
Windows LIVE GUI나 별도 serial 연결은 사용하지 않는다.

1. `pose_1`~`pose_8` 선택 → 경로 확인 → `선택 자세로 이동`.
2. 실제 관절 피드백으로 도착이 확인되면 해당 자세를 복귀 위치로 고정한다.
3. 녹화 화면에서 리더를 팔과 비슷한 자세로 맞춘 뒤 `리더 정렬 후 텔레 켜기` → `Start episode`.
4. 사람이 텔레로 집고 안전한 높이까지 들어 올린다.
5. `집기 완료 · 저장 후 복귀` → HOLD → 저장 ACK 대기 → 그리퍼 포함 같은 어프로치의 6축 저장값으로 이동.
6. 복귀가 도착 상태가 되면 같은 연결에서 다음 에피소드를 준비한다.

녹화 없이 집기 시험도 가능하다. `선택 자세로 이동` → 리더 정렬 후 텔레 켜기 → 집고 들어 올리기 → 경로 확인 → `집기 완료 · 어프로치 복귀`로 사용한다.
이때 에피소드를 시작하거나 저장하지 않는다. 도착 확인에 실패한 경우에도 마지막으로 이동 요청한 `pose_1`~`pose_8`을 같은 버튼으로 다시 시도할 수 있으며, UI에 `도착 미확인`을 표시한다.
드롭다운만 바꿔도 복귀 대상이 바뀌지는 않는다. 녹화 시작과 저장 후 복귀에는 실제 도착이 확인된 어프로치가 필요하다.

녹화 시작은 어프로치 도착 후 텔레 상태에서만 허용한다. 시작 시 현재 팔 관절이 어프로치에서 2 normalized 이내인지 확인한다.
HOLD 구간은 기존 RecordingCallback이 기록하지 않으므로 저장 자세 이동이 집기 데이터에 섞이지 않는다.
저장이 실패하거나 저장 대기 중 정지/연결 해제가 발생하면 자동 복귀하지 않는다.
새 자세 이동을 시작하면 이전 복귀 위치를 무효화하며, 실패·중단된 어프로치를 다음 녹화의 시작으로 사용하지 않는다.

운영 시에는 Model Run의 Play로 집기 모델을 실행하고, 충분히 들어 올렸을 때
`집기 완료 · 어프로치 복귀`를 누르면 같은 런타임에서 policy → hold → 저장 자세로 전환한다.
**모델의 집기 성공·종료 자동 판정은 구현하지 않았다.** 모델 학습 후 그 판정이 확정되면 같은 명령 계약에 연결한다.
배출구 전체 경로의 자동 연쇄 실행도 이번 구현에 포함하지 않았다.

## 자세와 제어 조건

- 입력은 `outputs/robot_panel_live/poses.json`의 12개 자세다.
  `home`, `pose_1`~`pose_8`, `close`, `open`, `outlet_return_1`.
- 설치 묶음에 그 시점의 자세를 복사한다. 원본 JSON 변경이 설치본에 자동 반영되지는 않는다.
- Follower `bc50f050-d0a5-4430-af97-0486cdaec3a2`에 묶여 있다. WebSocket의 세션 ID와도 대조한다.
- 일반 이동과 어프로치 복귀는 **그리퍼를 포함해 저장된 6축 값을 적용**한다. `pose_1`의 그리퍼 목표는 약 3.70이다.
- `open`을 선택하면 저장된 그리퍼 열림 값도 함께 적용한다.
- API의 명시적인 `include_gripper=false`는 기존 호출 호환을 위해 직전 그리퍼 명령을 유지한다. Studio 버튼은 항상 `true`를 보낸다.
- 팔 5축 + 그리퍼의 normalized 값이다. mm 또는 각도가 아니다.
- `이동 시간`에서 3초·4초·5초를 선택한다. 기본값은 3초이며 선택 자세 이동과 어프로치 복귀 모두 같은 선택을 사용한다.
- 선택한 시간 동안 부드럽게 가속·감속하며, 한 tick의 반영 시간은 최대 0.1초다.
- 보간이 끝나면 목표 자세를 계속 명령하며 실제 도착을 기다린다. 3초가 지났다는 이유로 중단하지 않는다.
- 목표값 전송이 끝나면 `목표값 유지 · 도착 확인 중`으로 표시하고 다음 저장 자세 선택·이동을 허용한다. 새 제어나 이동을 선택하면 이전 자세의 도착 감시를 종료한다.
- 추종 판정은 통신·모터 응답 지연을 반영해 최근 0.15초의 명령 경로를 기준으로 한다. 실제 팔이 이 경로에서 10 normalized 초과 벗어나면 관절명과 오차를 표시하고 HOLD.
- 관측 갱신 0.5초 초과 중단, 클라이언트 heartbeat 1초 초과 누락 시 HOLD.
- 팔 도착은 오차 1.5 이내가 0.3초 유지되는지 확인한다. 이 상태는 물건 집기 성공이나 그리퍼 접촉 성공을 의미하지 않는다.
- 이동 중 텔레·정책 시작·녹화·다른 자세 명령은 서버에서도 거부한다.
- 텔레 재개는 리더와 팔 6축 차이 5 이내로 정렬해야 한다. 자동으로 리더를 움직이지 않는다.
- 같은 런타임 관측으로 리더·팔로워의 6축 값과 차이를 실시간 표시한다. 값이 오래되면 대기 표시로 바뀐다.
- `이동 정지 / HOLD`는 소프트웨어 정지다. 토크 해제나 하드웨어 비상정지는 아니다.
- 저장 자세 간 관절 보간이며 충돌 회피·안전 경유점 계산은 없다. 실제 경로 검증이 필요하다.

## 파일

| 파일 | 역할 |
|---|---|
| `runtime/saved_pose.py` | 6축 보간, 클라이언트 lease, 관측·상태 검사 |
| `stage.py` | 실제 설치된 v4 backend 소스에 anchor 검사 후 별도 overlay 생성 |
| `stage_ui.py` | 해당 Studio 버전 UI에 컨트롤과 저장→복귀 흐름 삽입 |
| `ui/` | 새 React 컴포넌트, 흐름 함수, 테스트 |
| `test_runtime.py` | Studio Python 환경에서 실행하는 하드웨어 없는 통합 테스트 |
| `package.py` | 빌드 결과와 원본 해시를 설치 묶음으로 생성 |
| `install.py` | 기본 읽기 전용 점검, 명시적 적용·백업·복구 |

로컬 결과는 `outputs/studio_pose_integration/`에 있다.

- `original/backend/` — 실행 컨테이너의 변경 전 소스 복사본.
- `exact/application/ui/` — 실행 이미지와 같은 revision의 UI 소스 + 이번 변경.
- `backend/` — 새 backend overlay.
- `build/dist/` — 배포용 정적 UI.
- `build/source/` — 실제 빌드·검사를 수행한 최종 UI 소스와 생성된 API 타입.
- `bundle/` — 설치 입력. `bundle.json`에 파일별 SHA256 및 설치 전 backend 해시.
- `ui/` — 최초 조사 때 사용한 다른 revision의 UI. **설치·재빌드에 사용하지 말 것.**

`outputs/`는 Git에서 제외되므로 다른 PC에는 이 문서·`robot/studio_extension/`와 `bundle/`을 함께 전달한다.
장치·보정이 다른 팔에 이 자세 파일을 그대로 적용하면 안 된다.

## 설치 준비 및 적용

대상은 컨테이너 `physical-ai-studio-cuda`, Studio 이미지 revision
`e5dd66a38cf1e682fdead3ca0fefa60f5bf3459d`이다.
WSL의 `/home/user/physical-ai-studio` checkout은 `f071fe6`이므로 그 UI로 빌드하면 설치 backend와 API 타입이 맞지 않는다.
이번 결과는 이미지 revision의 소스를 따로 가져와 빌드했다. 기존 checkout은 변경하지 않았다.

먼저 읽기 전용 검사. PowerShell에서 실행한다.

```powershell
wsl -d Ubuntu-24.04 -- python3 `
  /mnt/c/Users/user/AI-LostFound/team-repo/robot/studio_extension/install.py `
  --bundle /mnt/c/Users/user/AI-LostFound/team-repo/outputs/studio_pose_integration/bundle
```

이 명령은 로봇 연결·이동·Studio 재시작을 하지 않는다. 현재 장치가 빠져 있으므로 `missing_restart_devices`가 출력된다.

사용자가 설치를 진행할 때, 기존 장치 설정에 맞게 팔·리더·카메라를 연결하고 WSL attach를 먼저 확인한다.
활성 로봇 세션을 종료하고 안전한 상태에서 다음 명령으로 적용한다.

```powershell
wsl -d Ubuntu-24.04 -- python3 `
  /mnt/c/Users/user/AI-LostFound/team-repo/robot/studio_extension/install.py `
  --bundle /mnt/c/Users/user/AI-LostFound/team-repo/outputs/studio_pose_integration/bundle `
  --apply
```

설치기는 버전·파일 해시·세션 없음·Docker 재시작에 필요한 장치 경로를 확인한다.
변경 전 backend와 UI를 `backup-날짜-시각/`에 저장하고 파일을 반영한 다음 컨테이너를 재시작한다.
설치 후 health 확인 실패 시 백업을 복구한다. 브라우저는 새로고침한다.
**이 설치는 기존 컨테이너에 적용된다. 컨테이너를 삭제·재생성하거나 Studio를 업데이트하면 다시 준비·적용해야 한다.**
컨테이너 restart에는 유지된다. 설치기가 로봇 연결이나 이동을 시작하지는 않는다.

복구도 장치가 있고 활성 세션이 없는 상태에서 실행한다.

```powershell
wsl -d Ubuntu-24.04 -- python3 `
  /mnt/c/Users/user/AI-LostFound/team-repo/robot/studio_extension/install.py `
  --bundle /mnt/c/Users/user/AI-LostFound/team-repo/outputs/studio_pose_integration/bundle `
  --rollback /mnt/c/Users/user/AI-LostFound/team-repo/outputs/studio_pose_integration/backup-실제시각
```

## 2026-11-09 최신 검증과 남은 확인

- backend 통합 테스트 25개, UI·복귀 흐름·관절 비교 테스트 17개 통과.
- 팀 저장소 전체 테스트 312개 실행, 303개 통과·9개 skip. 3·4·5초 보간, 시간이 지나도 목표 유지, 추종 오차 10 초과 정지 회귀시험 포함.
- TypeScript 타입 검사, 변경 UI 파일 ESLint·Prettier, production build 통과.
- 배포 UI 해시가 검증한 빌드와 일치하고 `duration_seconds: Literal[3, 4, 5] = 3` 계약을 확인했다. 서버 재시작 후 HOLD·녹화 꺼짐·12개 자세 목록을 확인했다.
- 최신 시간 선택별 실제 이동 시간과 물건을 든 전체 반환 경로의 반복 성공률은 아직 검증하지 않았다. 모델 학습·집기 성공 자동 판정도 별도 작업이다.
- 현재 백업은 `outputs/studio_pose_integration/backup-move-duration-20261109-105051/`. 이미 패치된 Studio에 초기 설치기를 재실행하면 원본 해시 검사로 거부된다. 기존 설치본 갱신에는 현재 소스 대조와 별도 백업이 필요하다.

## 최초 준비 시점 검증 이력 · 2026-11-06

- 실제 Studio Python 의존성에서 backend 통합 테스트 **18개 통과**.
  같은 RuntimeSession으로 3회 녹화 저장, 동일 장치 객체 유지, policy→hold 그리퍼 유지,
  복귀 프레임 제외, 저장 중 이동 차단, 통신 단절·관측 노후·추종 오차·정지·도착 검사 포함.
- 새 UI·흐름 테스트 7개 및 기존 모델 화면 12개, 합계 **19개 통과**.
- TypeScript 전체 타입 검사, 전체 ESLint, 전체 Prettier, 순환 의존성 검사, production build 통과.
- 팀 저장소 `python -m unittest discover -s tests`는 **304개 실행, 303 통과·1 skip**.
- 전체 UI 테스트 최초 실행은 551개 중 544 통과·1 skip·6 실패.
  실패한 기존 6개 파일을 별도로 재실행해 그 안의 **49개 전부 통과**했다. 동시 실행 시 시간 초과가 있었으며
  전체 일괄 실행이 한 번에 모두 통과했다고 기록하지 않는다.
- 묶음의 SHA256 읽기 전용 preflight 통과. 장치 미연결을 정확히 보고했다.
- 최초에는 설치 준비까지만 수행했으며, 후속 요청으로 설치를 완료했다. **실물 runtime 연결·이동·녹화 화면 검증은 미실시**.
- 최초 실물 검증은 빈 집게, 작은 자세 차이부터 수행하고, 정지·도착·텔레 정렬을 확인한다.
  이후 물건을 든 복귀와 실제 저장 에피소드의 마지막 프레임을 확인해야 한다.

## 운영 연결 계약

기존 `/api/projects/{project_id}/runtime/ws`의 같은 연결에서 사용한다.

```json
{"event":"move_saved_pose","data":{"pose":"pose_1","follower_id":"bc50f050-d0a5-4430-af97-0486cdaec3a2","token":"unique-move-id","approved":true,"return_to_approach":false,"include_gripper":true,"duration_seconds":3}}
```

동일 token으로 200ms마다 `saved_pose_heartbeat`를 보낸다. 상태의 `saved_pose_status=arrived`가 실제 팔 도착 확인이다.
`moving`은 수락일 뿐 도착이 아니다. 제어권을 다른 클라이언트로 넘겨 heartbeat를 대신 보내면 안 된다.
복귀는 먼저 `set_follower_source: hold` 확인 후 `return_to_approach: true`로 요청한다.
`stop_saved_pose`는 이동을 취소하고 그리퍼 명령을 유지한 HOLD로 전환한다.
학습 모델의 자동 완료 신호가 아직 없으므로 타이머만으로 성공을 추정해 연결하지 않는다.
