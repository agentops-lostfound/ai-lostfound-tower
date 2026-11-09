# DB 칸 → Studio 사전 접근 연결부 · LF-21

`docs/contracts/robot_db_target.md` 0·9·10장을 기준으로 `robot.tower_part:TowerRobot`을 구현했다.
현재 기본 지원 범위는 **저장 자세 사전 접근과 그 자리 정지**다. VLA 실행 어댑터는 연결되지 않았다. 외부에서 집기 정책을 주입하는 경우의 **집기 종료 → 같은 어프로치 복귀** 연결부를 추가했으며, 파지 검증·전달·원복은 계속 `{ok: false, reason}`으로 답한다.

## 최신 학습 범위 변경: VLA는 아래에서 집기까지만

사용자는 현재 에피소드를 타겟에서 집게를 닫은 상태로 끝낸다. VLA에 들기·어프로치 복귀를 학습시키지 않는다. 따라서 목표 순서는 아래처럼 변경됐다.

```text
DB 칸 → pose_N 도착 → VLA 접근·집기 → VLA 종료·HOLD
→ 그리퍼 파지 명령 유지하며 같은 pose_N 복귀·도착
→ 파지 검증 → outlet_return_1 → close → open → outlet_return_1 → home
```

- `TowerRobot(..., grasp_policy=callable)`의 선택 어댑터 연결부를 준비했다. 기본값은 None이며, 학습 모델을 자동으로 찾거나 실행하지 않는다. 미연결 상태의 `robot_grasp()`는 계속 실패한다.
- `robot_go_pose`는 DB 칸 번호와 pose 번호를 대조하고 실제 도착 후에만 복귀 대상을 기억한다. `robot_grasp`는 그 도착 대상이 있어야 정책을 시작한다. 두 명령은 같은 부품 인스턴스를 사용해야 한다.
- 시작 연결점은 `grasp_policy(approach_pose=pose_name, slot_id=slot_id, cancelled=Event)` 호출이다. 정책 어댑터는 집기 실행을 끝내고 기존 Studio에서 HOLD로 전환한 후 `{ok: True, control_released: True}`를 반환해야 한다. 타이머 경과나 에피소드 저장만으로 이 결과를 만들지 않는다. 이는 내부 주입 인터페이스이며 실제 VLA/Studio 어댑터는 아직 구현하지 않았다.
- `robot_grasp`는 이 완료 응답 뒤에만 같은 pose로 복귀한다. `include_gripper=False`로 팔 5축을 저장 자세로 보내고 **직전 그리퍼 명령**을 유지한다. 물건 때문에 벌어진 실제 그리퍼 측정값을 목표로 사용하지 않는다. 전송부는 HOLD·녹화 꺼짐·관측을 다시 확인하고, 복귀 도착까지 기다린다.
- 정책 실패·제어 미반납·복귀 실패·정지 요청은 HOLD 요청과 실패 응답으로 이어지며 배출구 이동을 시작하지 않는다. 복귀 대상은 한 번 소비하므로 중복 집기를 자동 실행하지 않는다.
- 이 이동은 관절 보간을 통한 저장 자세 복귀다. TCP 수직 상승, 장애물 회피, 물건을 든 상태의 안전 경로를 보장하지 않는다. 실제 타겟에서 어프로치까지의 경로와 파지는 별도 검증해야 한다.
- 반환되는 `ok`는 집기 동작 종료와 복귀 도착을 뜻한다. 실제 물건 파지 검증은 `robot_verify_grasp`에 별도로 필요하며 아직 미구현이다. 기존 8766 시험 화면의 VLA 생략 6단계는 그대로 유지한다.
- 이번 변경 검증: 전체 unittest 1,238개 실행·1,215개 통과·23개 skip·실패 0개. 기존 Studio 임시 overlay의 모의 runtime 시험 26개도 통과했다. 새 시험은 정책 종료·제어 반납 전 복귀 차단, 원래 DB 칸으로 복귀, 도착 대기, 동시 명령·중복 집기 차단, 정지·실패 처리, 측정 벌림 42에도 그리퍼 목표 3.7 유지 등을 확인했다. 실물 동작·Studio 재시작·정책 연결은 하지 않았다.

## 현재 상태 우선 확인 · 사용자 조작 시험 화면 추가

- 팀 공유 브랜치 `LF-21-geontae-tower-robot-part`에 최신 main과 PR #157의 공유 파일을 함께 통합했다. [시퀀스 실행법](../../robot/README-sequence.md)과 [설치·기존 설치 갱신](studio-shared-install.md)을 따른다. 도착 마진 5 소스·자세 12개·갱신한 설치 압축본이 같은 브랜치에 포함된다.
- 공유 정리 후 검증: 전체 unittest 1,226개 실행·1,203개 통과·23개 skip·실패 0개. `update_arrival`의 기존 마진 호환성·장비 자세 불일치 거부·활성 세션 거부·읽기 전용·단일 모듈 백업 교체·점검 후 세션 출현 취소를 모의 시험 6개로 확인했다. 갱신 도구를 실제 설치본에 적용하거나 Studio를 재연결하지 않았다.
- 후속 사용자 요청(같은 `pose_1` 재요청 시 도착 대기)에 따라 소스 도착 기준을 3 → 5 normalized로 조정했다. 팔 5개 관절 모두 ±5 안에서 0.3초 유지해야 하며, 추종 한도 10·보간 시간·그리퍼 목표는 유지한다. 이 변경은 설치·세션 재연결 대기이며, 아래 설치본 기준 3과 구분해야 한다. 변경 후 실물 시험은 하지 않았다.
- 마진 5 변경 검증(공유 정리 전): 전체 unittest 1,198개 실행·1,175개 통과·23개 skip·실패 0개. Studio 임시 overlay의 모의 runtime 시험 25개와 패널 JavaScript 문법 검사도 통과했다. 공유 정리 시 `bundle.tar.xz`도 마진 5로 갱신했고 Windows tar 해제 및 내부 해시·소스·자세 일치를 검증했다. 현재 설치본은 변경하지 않았다.
- 사용자가 직접 시험하도록 `robot/sequence_panel.py`와 브라우저 화면, `robot/sequence_experiment.py` 제어 모델을 추가했다. [실행·사용법](../../robot/README-sequence.md)을 따른다.
- 기본은 모의 모드이고 `--live`도 초기에는 미연결이다. 사용자가 연결 확인·경로 확인·실행 버튼을 눌러야 움직인다. 선택 단계 하나 또는 처음부터 6단계를 실행하고, 실측·명령·저장 목표·오차를 표시한다. DB 응답 JSON 적용도 지원하지만 DB 기록은 바꾸지 않는다.
- 사용자의 후속 승인으로 실물 `pose_1`을 시험했으나 도착 확인을 완료하지 못했다. 관측 생산자 소실을 확인해 로봇 세션만 재연결했고, 팔꿈치 잔여 오차 약 2.26 때문에 도착 기준을 사용자 승인으로 1.5 → 3 normalized로 변경·시험·설치했다. 서버 전체를 재시작하지 않았다.
- 재시험에서는 어깨 상하 잔여 오차 약 3.44가 남았다. 사용자가 위치 차이 또는 걸림·진동을 보고해 현재 위치 HOLD로 종료했다. 배출구 5단계는 실제 실행하지 않았다. 더 큰 도착 오차로 우회하지 않았으며, 새 도구 작성 중에는 실제 이동 명령을 보내지 않았다.
- 당시 실물 기록은 `outputs/robot_db_check/live-pose1*/`에 보관했다. 현재 설치본과 이전에 풀어 둔 로컬 `bundle/`의 도착 기준은 3이다. 새 공유 압축본은 5이므로 이전 압축 해제 폴더와 혼동하지 않는다.
- 새 화면의 모의·HTTP 시험 11개 통과. 최신 전체 시험은 1,197개 실행·1,182개 통과·15개 skip·실패 0개다. JavaScript 문법 검사도 통과했다. UI를 만들거나 모의 시험을 통과한 것은 실물 경로 검증 완료를 뜻하지 않는다.

## 후속 요청: VLA를 제외한 DB 트리거 시퀀스 시험

당시 사용자가 확정한 전체 순서는 `pose_N → VLA → outlet_return_1 → close → open → outlet_return_1 → home`이었다. 최신 집기 전용 VLA의 순서는 위 변경 사항을 따른다.
VLA가 없는 현재는 그 단계만 제외한 **6단계 저장 자세 시험 시퀀스**를 추가했다.

```text
DB에서 선택된 물건 ID로 칸·자세 조회
→ pose_N → outlet_return_1 → close → open → outlet_return_1 → home
```

- `robot/db_pose_sequence.py`의 `trigger_db_sequence(item_id, target_lookup, robot)`가 DB 조회 함수의 결과를 받아 `TowerRobot.run_pose_sequence_test(target)`로 연결한다. 실제 관제탑에 연결할 때 lookup은 `svc.robot_target` 같은 서버의 DB 조회 함수다.
- 시퀀스는 전체 자세 유무를 먼저 검사하고, 앞 단계의 도착이 확인돼 이동 함수가 반환한 뒤 다음 단계를 호출한다. 반복된 `outlet_return_1`을 생략하지 않는다.
- 중간 실패·정지 시 남은 단계를 실행하지 않는다. 실패 뒤 자동으로 home으로 복귀하지 않는다.
- 이 경로는 명시적인 시험용이다. 운영 반환의 집기·파지 검증을 성공으로 바꾸거나 DB를 인계 완료로 기록하지 않는다.
- CLI는 `--simulate` 전용이다. 메모리 DB와 기존 `PoseMove` 보간·도착 로직을 사용하는 이상적인 모터 피드백으로 시험한다. 실제 DB·Studio·serial·로봇에는 연결하지 않는다.
- 새 시험 9개로 8칸 모두의 매핑·정확한 6단계 순서·3/4/5초 설정·도착 대기·중간 실패·취소·자세 누락·다른 물건 응답을 검증했다. 실물 시퀀스는 아직 시험하지 않았다.

저장소 폴더에서 재실행:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m robot.db_pose_sequence --simulate --slot R3-2 --seconds 3 --output outputs/robot_db_check/sequence-r3-2.json
```

예시 결과는 `pose_6 → outlet_return_1 → close → open → outlet_return_1 → home` 완료이며,
출력의 `simulation=true`, `db_source=memory`, `vla_skipped=true`로 시험 범위를 표시한다.
모의 시간·도착 결과는 실물 모터 성능이나 파지·배출 성공을 뜻하지 않는다.

이번 시퀀스 추가 후 전체 시험은 1,185개 실행·1,162개 통과·23개 skip·실패 0개다.
현재 로컬 자세 JSON으로 8칸 모두의 모의 시퀀스도 완료했다. 결과는 `outputs/robot_db_check/all-slots-sequences.json`이다.

## 연결 방식

- 관제탑이 DB에서 물건의 칸·자세를 결정해 `robot_go_pose(pose_name, slot_id)`를 호출한다. 부품은 SQL이나 물건·개인 특징 API를 읽지 않는다.
- Windows 관제탑 → `wsl.exe` → 기존 Studio 컨테이너의 IPC 클라이언트 → 기존 `StudioActionSource` 순서다. 별도 serial·로봇 드라이버를 열지 않는다.
- IPC의 `RuntimeSessionClient.connect()`는 기존 runtime에만 붙는다. runtime/owner 생성·Studio 재시작·자동 텔레 전환은 하지 않는다.
- 생성·import는 자세 파일과 설정만 읽는다. `.env` 파일은 읽지 않고 관제탑이 전달한 프로세스 환경변수만 사용한다.
- Windows 부품은 표준 라이브러리와 기존 관제탑 코드만 import한다. `agents/requirements.txt` 추가는 없다. 사용자 요청으로 만든 통합 `.venv`의 YOLO용 torch 설치와 별개이며, 이 부품에서 torch·lerobot을 import하지 않는다.

## 동작과 실패

- `pose_1~8`, `R1-1~R4-2`만 접근 요청으로 허용한다. 알 수 없는 자세·보관 칸·손상된 자세 파일은 명령 전에 거부한다. DB가 지정한 허용 자세 이름을 사용하고 자체 물건 매칭은 하지 않는다.
- Studio에 같은 follower의 해당 자세가 있고, 녹화가 꺼져 있으며, 다른 저장 자세 이동이 진행되지 않고 HOLD·신선한 6축 관측이 있어야 요청한다.
- 이동 시간 3·4·5초(기본 3초), 그리퍼 포함 저장 6축 값 적용은 기존 Studio 명령을 그대로 쓴다.
- 자기 token의 이동 수락을 확인한 뒤 `arrived`가 될 때까지 동기로 기다린다. `moving`, `holding_target`, 명령 전송만으로 성공 처리하지 않는다. 선택 시간 초과로 실패하지 않는다.
- 명령 수락 확인 2초, 초기 연결 확인 10초, 관측 중단 0.5초는 별도 통신 조건이다. 이동 중 0.2초마다 heartbeat를 보낸다.
- 오류·관측 중단·다른 클라이언트 제어 감지 시 stop을 요청하고 실패를 돌려준다. 실패 후 자동 재시도하지 않도록 부품에 정지를 유지한다.
- `robot_stop()`은 이동 잠금을 기다리지 않는다. 이동 중에는 같은 수신 루프에서 정지를 처리하고, 대기 중에는 관절 관측 없이도 기존 세션에 정지를 요청한다. worker는 전송 뒤 같은 runtime generation의 metadata를 조회해 HOLD·stopped 상태를 확인하고 요청 ID를 붙여 돌려준다. 이것은 하드웨어 비상정지 ACK가 아니며, 수락 여부를 못 본 이동은 이전 stopped 값만으로 정지 성공 처리하지 않는다. 정지 확인 실패를 성공으로 바꾸지 않고 원점으로 이동하지 않는다.
- 정지 뒤 다시 쓰려면 직원 확인 후 관제탑 부품을 다시 준비한다. 부품 재생성 자체는 연결·이동하지 않는다.
- `robot_state()`는 아직 제공하지 않는다. Studio의 normalized 값을 로봇 API 계약의 도(°) 값으로 잘못 내보내지 않기 위해 보정 변환이 확정될 때 추가한다. Studio 자체 실시간 관절 표시는 그대로 사용할 수 있다.

## 준비와 설정

1. 저장 자세 확장이 설치된 Studio를 기존 절차로 켜고 해당 팔을 연결한다. Studio 화면을 유지하고 HOLD·녹화 꺼짐을 확인한다.
2. 같은 로봇·보정의 자세 JSON을 준비한다. PR #157의 자세·설치 묶음도 이 브랜치에 통합했으며 [설치 순서](studio-shared-install.md)를 따른다. 다른 장비의 모터값을 대체값으로 사용하지 않는다.
3. 관제탑 프로세스에 아래 이름을 설정한다. 실제 `.env`는 이 작업에서 읽거나 수정하지 않았다.

| 이름 | 값 |
|---|---|
| `TOWER_ROBOT_TARGET` | `db` |
| `TOWER_ROBOT_PART` | `robot.tower_part:TowerRobot` |
| `TOWER_STUDIO_FOLLOWER_ID` | 연결한 Studio 팔로워 UUID. 비우면 이동 실패 |
| `TOWER_STUDIO_CONTAINER` | 기본 `physical-ai-studio-cuda` |
| `TOWER_STUDIO_DISTRIBUTION` | 기본 `Ubuntu-24.04` |
| `TOWER_ROBOT_POSES` | 기본 저장소 `outputs/robot_panel_live/poses.json` |
| `TOWER_ROBOT_MOVE_SECONDS` | `3`, `4`, `5` 중 하나. 기본 `3` |

4. 부품의 로드만 점검한다. 이 명령은 장비에 연결하거나 이동하지 않는다.

```powershell
.\.venv\Scripts\python.exe -c "from agents.robot_part import load_robot_part; from agents.robot_api import check_robot_part; print(check_robot_part(load_robot_part('robot.tower_part:TowerRobot')))"
```

5. DB API 2개에서 칸·자세를 읽고 기록을 대조하는 것은 관제탑 연결 확인 단계다. 실제 API 주소·관리자 인증은 관제탑 담당 설정을 사용한다. 여기서 임의 DB 기록이나 실물 반환을 실행하지 않았다.

## 확인 사항과 남은 일

- 칸 번호는 문서의 확인 완료 내용을 따른다: 가까운 줄 1·3·5·7, 먼 줄 2·4·6·8, 왼쪽 R1부터 오른쪽 R4. 이번에 다시 실물을 확인한 것은 아니다.
- 학습 정책은 접근·집기까지만 담당하도록 변경했다. 들기는 정책 완료 후 같은 어프로치로 복귀하는 로봇 제어가 맡는다. 실제 정책 어댑터는 미연결이며 미학습 모델이나 임의 내리기 자세로 성공을 대신하지 않는다.
- 원본 JSON의 `pose_1`, `pose_2`에는 `wrist_roll.pos`가 각각 약 -3.00, -6.23 **normalized**로 들어 있다. 이 수치는 도(°)나 휴대폰의 45도 배치 각도가 아니다. 물건을 잡는 방향의 적합성은 별도 실물 확인이 필요하다.
- 모의 시험에서 수락·실제 도착 구분, 선택 시간 이후 대기, 정지 중단, 통신 오류, 외부 제어, 녹화/텔레 차단, 미구현 단계 실패를 확인한다.
- 기존 Studio IPC의 상태·6축 관측 읽기는 확인했다. 이동·정지 명령을 보내지 않았으며 실제 DB 반환·집기·전체 배출구 경로는 미검증이다.
- 2026-11-09 재검토 결과: 부품·전송·worker 모의 시험 25개 통과. Windows 저장소 `.venv`에서 전체 1,176개 실행·1,161개 통과·15개 skip·실패 0개(17.892초). 부품 로더는 `missing: []`, `has_state: False`; 문법 검사와 `git diff --check`도 통과했다. 이전 문서의 1,164개·23 skip은 이번 실행 결과가 아니다.
- 따라서 문서 10장 체크리스트 중 부품 구현·로드·모의 검증까지만 완료했다. 실물 설정 적용·DB 기록·반환 1회 시험은 남아 있다.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_tower_robot_part -v
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## 2026-11-09 후속 코드 검토

이번 검토에서 고친 내용:

- `robot/tower_part.py`: 저장 자세 JSON에 정확히 정해진 6축만 있는지 검사한다.
- `robot/studio_pose_transport.py`: 연결 준비 중 취소를 확인한다. move 전송·flush 오류도 이미 명령이 전달됐을 가능성을 고려해 정지 확인을 시도한다. 정지 확인 실패를 오류 이유에 남긴다. 이동 완료와 정지 요청을 같은 lock으로 정렬하고, 정지와 이동이 같은 pipe를 경쟁해서 읽지 않게 한다.
- `robot/studio_pose_worker.py`: 동일한 stopped 방송이 IPC에서 생략되는 경우를 처리하기 위해 전송 후 metadata를 조회한다. 다른 runtime generation·불명확한 pending 이동은 확인 실패로 유지한다. worker 상태 갱신은 lock으로 보호한다.
- `tests/test_tower_robot_part.py`: 12개 회귀 시험을 추가했다. 정확히 6축, 준비 중 취소, 부분 전송 실패, 관측 없는 정지, 오래된/다른 요청의 정지 응답, 정지 확인 실패, 이동 중 정지 단일 수신, metadata generation 및 미수락 이동을 다룬다.

### 현재 설치와 Git 상태

- 작업 폴더 `C:\Users\user\AI-LostFound\team-repo`, 브랜치 `LF-21-geontae-tower-robot-part`, HEAD `057988cbada90a6ac3f3df0fbab9008361638b91`.
- 기존 `.env.example`, `robot/README.md` 수정과 untracked 파일을 보존했다. 이번 검토에서 커밋·push·PR 생성·병합은 하지 않았다.
- `run_vision_adapter_full.py.pre_unify.bak`는 수정하지 않았다. SHA256: `a8885c7083c272017458868b9c5c32dd1832e02b19da5cbea947d12bbe621e7d`.
- PR #157은 확인 시 open·미병합이고 GitHub REST의 mergeable_state는 clean, head `556c84d1c7c2d7feeeb78ca7067b3e973eb39706`의 tests 체크는 success였다. 확인 시점 상태이므로 다음 작업 때 다시 조회한다.
- 기존 `physical-ai-studio-cuda` 컨테이너가 healthy 상태인 것을 확인했다. 로컬 bundle manifest의 파일 127개 해시가 일치했고 실제 설치 대상 backend/UI 126개도 모두 일치했다. `saved_pose.py`의 로컬 CRLF를 LF로 정규화하면 설치본과 같은 SHA256이다. IPC client/server 해시도 검토한 원본과 같다. 파일 일치 확인은 실행 중 메모리 코드나 실물 동작 검증을 뜻하지 않는다.
- 이번 검토는 Studio 설치·재시작·새 runtime·serial 연결·자동 텔레·실제 이동·실제 정지 명령을 실행하지 않았다. `.env`도 읽거나 수정하지 않았다.

### 실물 자동 반환 전 남은 위험과 작업

1. 사용자 목표는 분실인 정보와 DB의 물건 매칭 → 선택 물건의 칸 → 8개 사전 접근 중 하나 → 학습 정책으로 집기·들기 → 저장 자세 경로로 전달이다. 현재는 그중 DB가 결정한 칸의 사전 접근 연결만 구현됐다. DB 칸 모드는 반환 시 탑뷰 사진 재매칭을 생략한다. 앞단의 분실인 매칭·반환 승인을 대신하는 코드가 아니다.
2. `robot_grasp`, `robot_verify_grasp`, `robot_deliver`, `robot_home`는 의도적으로 실패한다. 학습 정책과 검증된 파지/안전 높이 신호를 연결하기 전에는 전체 반환 성공으로 볼 수 없다. 임의 내리기·집게 닫기나 가짜 성공으로 채우지 않는다.
3. 기존 Studio는 arrived에서 token을 지우고 stop은 특정 token에 한정되지 않는 전체 HOLD 명령이다. 방송도 best-effort이므로 동시에 다른 클라이언트가 같은 자세로 이동하면 최종 도착을 엄밀히 구별할 수 없다. 관제탑 실행 동안 다른 창의 이동·텔레·녹화를 동시에 실행하지 않는다. 다중 제어를 지원하려면 runtime의 terminal token 유지 및 token에 한정된 취소 계약을 별도 수정·검증해야 한다. 이 검토에서는 runtime을 바꾸거나 설치하지 않았다.
4. metadata 조회는 명령 처리 완료 barrier가 아니다. 자기 이동 수락을 못 본 채 정지를 요청한 경우 기존 stopped 상태만으로 성공하지 않도록 보수적으로 실패한다. 운영자는 이런 실패를 실제 정지 확인 완료로 해석하면 안 된다.
5. 기존 runtime은 보간 완료 후 `holding_target`에서는 heartbeat 만료로 정지를 보장하지 않는다. pipe 종료 자체도 정지 증명이 아니다. 하드웨어 비상정지·충돌 회피를 이 부품이 대신하지 않는다.
6. 8칸의 실제 위치, 휴대폰 손목 각도, 저장 자세 6축 값과 Studio 값의 일치, DB 기록, 학습 모델, 안전 높이 및 배출구 전체 경로는 실물 승인 후 별도 확인한다. 소프트웨어 시험 통과와 실물 검증은 별개다.

### 다음 Codex 작업의 시작점

먼저 AGENTS.md와 git status를 읽고 기존 미커밋 변경·백업을 보존한다. 이 문서와 `docs/contracts/robot_db_target.md`를 읽은 다음 위 세 코드 파일과 시험을 검토한다. 기존 Studio 연결만 사용한다. 별도 serial/새 runtime/재시작/자동 텔레를 만들지 않는다. 실물 이동·정지·설치·GitHub 게시와 병합은 별도 사용자 요청 전에는 하지 않는다. 현재 학습 집기·파지 확인·전달은 미연결임을 유지하고, 구현 전에 실제 모델과 완료/실패 판정 계약을 확인한다. 계약 변경이 필요하면 관제탑 담당 확인과 PR 이유 기록이 필요하다. 수정 후에는 위 `.venv`의 전체 unittest를 다시 실행하고 실제 확인한 것과 아직 확인하지 않은 것을 나눠 보고한다.
