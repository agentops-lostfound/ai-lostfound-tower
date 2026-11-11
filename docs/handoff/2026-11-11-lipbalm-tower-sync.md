# 7·8번 립밤 시퀀스 관제탑 동기화 — LF-21

## 현재 적용본

[PR #221](https://github.com/agentops-lostfound/ai-lostfound-tower/pull/221)의 `LF-21-geontae-tower-robot-part` 브랜치를 두 PC에 반영한다. PR 번호가 더 큰 변경을 받았다고 #221도 포함된 것은 아니다. 최신 main을 이 작업 브랜치에 병합했고, 7·8번 티칭·고정 명령 보정·도착 마진은 유지했다.

- 로봇 PC: `10.10.21.30:8767`, 기존 인증 키와 허용 관제탑 IP `10.10.21.21` 유지.
- Studio: 기존 팔로워·리더·카메라 세션, 원본 36개 + 파생 운반 7개 = 43개 자세.
- `pose_7_target`·`pose_8_close`의 팔 5축 고정 명령 보정 유지. 8번 close는 최초 보정량의 1.155배. 그리퍼는 보정하지 않는다.
- 두 자세 도착 마진은 원본 기준 ±5 normalized. 기존 운반 어깨 ±8과 추종 한도 10은 유지.
- 관제탑 원격 실행의 단계별 보간 시간은 **3초**다(기존 5초에서 변경). 로봇 PC의 실행 서버를 시작할 때 `TOWER_ROBOT_MOVE_SECONDS=3`을 설정한다. 현재 로봇 PC는 실행부 재시작 후 이 값이 실제 프로세스 환경에 적용된 것을 확인했다. 관제탑 PC의 이동 시간 설정은 바꿀 필요가 없다. 도착 확인·안정 유지 시간은 보간 시간과 별도다.
- 원격 실행부는 현재 코드로 다시 준비하되 **DISARMED**를 유지한다. 관제탑 코드 반영·재시작 후 현장에서 다시 허용한다. 이전 작업은 자동 재개하지 않는다.

## 이번 중단에서 확인한 사실

반환 사례 `R-C-20261111-0006`은 8번의 1~5단계 도착까지 관제탑에 기록됐다. `pose_8_close` 이후 `Remote operation failed: ValueError; stop state confirmed`로 중단됐고, Studio 자체 자세 오류는 없었다.

당시 main에는 #221이 없고 6단계가 `pose_8_return`이었다. 로봇의 6단계는 `pose_8`이다. 진행 응답 이름이 처음 달라지는 지점과 중단 지점이 일치하므로 버전 불일치가 가장 유력하다. 기존 클라이언트가 예외 내용을 숨겨 당시 세부 예외를 확정한 것은 아니다.

이제 `/v1/health`의 `sequence_plans`에 실행부가 시작할 때 읽은 칸별 11단계 경로를 제공한다. 관제탑 클라이언트는 실제 작업 POST 전에 자기 경로와 비교한다. 경로가 다르거나 실행부가 이 필드를 제공하지 않으면 **이동 요청 없이 실패**한다. 이 필드는 허용 칸을 확대하거나 실제 이동을 시작하지 않는다.

후속 실패 응답에는 기존 정지 확인과 함께 인증 키를 가린 예외 설명·작업 ID를 남긴다. 진행 콜백이 거절한 경우 `failed_progress`에 해당 단계 정보도 보존한다.

## 재원님 PC에서 할 일

1. 기존 작업을 보존하고 #221을 main에 병합한 뒤 현재 작업 브랜치에 그 main을 반영한다. #221 병합 전이라면 이 PR 브랜치를 현재 브랜치에 병합해도 된다. `reset --hard`, 강제 push, 기존 작업 삭제는 하지 않는다.
2. 아래 읽기 전용 검사를 **실제 관제탑을 실행할 저장소 폴더**에서 실행한다. Python이 잘못된 다른 checkout을 읽지 않도록 파일 위치도 확인한다.

```powershell
git fetch origin
# #221 병합 전, 기존 작업을 보존한 현재 브랜치에서:
git merge origin/LF-21-geontae-tower-robot-part
if ($LASTEXITCODE -ne 0) { throw '병합을 확인한 뒤 진행하세요.' }

@'
import robot.db_pose_sequence as module
from robot.db_pose_sequence import sequence_for_target
print('실행 모듈:', module.__file__)
for number, slot in ((7, 'R4-1'), (8, 'R4-2')):
    plan = sequence_for_target({'ok': True, 'slot_id': slot,
                                'number': number, 'pose_name': f'pose_{number}'})
    assert len(plan) == 11 and plan[5] == f'pose_{number}'
    assert not any(name.endswith('_return') or name.endswith('_78') for name in plan)
    print(slot, '→'.join(plan))
'@ | .\.venv\Scripts\python.exe -X utf8 -
if ($LASTEXITCODE -ne 0) { throw '시퀀스가 맞지 않아 서버를 실행하지 않습니다.' }
```

3. 기존 관제탑 프로세스를 정상 종료하고 **위 검사에 사용한 저장소**에서 기존 정상 실행 방법으로 재시작한다. 웹 페이지 새로고침·시연 초기화만으로 실행 중인 Python 코드가 갱신되지는 않는다.
4. 기존 원격 설정과 비밀 키를 재사용한다. `.env`나 토큰 값을 대화·출력·Git에 노출하지 않는다. 관제탑은 `taught_remote` 모드여야 한다. 기존 인증 키로 조회한 로봇 `/v1/health`에는 7·8번 모두 6단계가 `pose_7`·`pose_8`인 `sequence_plans`가 있어야 한다.
5. 반영·프로세스 재시작 완료를 로봇 담당자에게 알린다. 정지된 사례를 자동 재전송하거나 성공 처리하지 않는다. 실제 팔·물건 위치를 확인한 뒤 기존 직원 복구 절차를 적용하고, 로봇 PC가 실행을 허용한 다음 명시적으로 새 시험을 시작한다.

재원님 PC에는 Studio를 설치하거나 티칭을 다시 할 필요가 없다. 로봇 PC의 현재 Studio 설정은 유지한다. 두 PC 코드 동기화와 관제탑 프로세스 재시작이 남은 작업이다.
