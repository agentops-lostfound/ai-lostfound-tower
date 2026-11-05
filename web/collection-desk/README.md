# LF-9 회수·도착 관리 시연

프로젝트 루트에서 의존성을 설치한 Python으로 실행한다.

```powershell
python -m tools.run_collection_demo
```

브라우저 주소: http://127.0.0.1:8110/collection-desk

1. 등록기계 A에서 지갑·USB를 선택하고 **선택한 물건 회수 기록**을 누른다.
2. 오른쪽에서 지갑만 체크하고 **도착 1개 추가 기록**을 누른다.
3. USB가 회수 중으로 남고 아래 알림 미리보기에 표시되는지 확인한다.
4. 나중에 USB도 체크해 저장하면 회수가 완료되고 미도착 미리보기가 사라진다.
5. 처음부터 다시 보려면 **시연 처음부터 → 가상 데이터 초기화**를 누른다.

가상 물건 6개는 `.cache/center-collection-demo.sqlite3`에 저장된다. 브라우저 새로고침과 서버 재시작 후에도 유지된다. 초기화는 이 파일의 `demo_*` 표만 변경한다. 사진·연락처·본인인증 정보가 없으며 팀 DB·환경 변수의 DB 접속 정보·디스코드 연결을 사용하지 않는다.

실제 `agents.center_api`의 `/collections`, `/collections/{id}`, `/collections/{id}/arrivals` 경로와 앱 팩터리를 재사용하지만 저장소는 별도의 SQLite 시연 구현이다. 실제 PostgreSQL 거래·직원 인증 연결이 끝난 화면이라는 뜻은 아니다. 실제 API의 직원 키 검증을 우회하지 않으며, 시연 모드는 고정된 `DemoCollections` 저장소에만 허용한다. 실제 API에는 초기화·시연 대시보드 경로가 없다.

회수 요청 실패 시 동일한 요청 번호로 재확인하고, 도착 체크 재시도는 이미 기록한 물건을 다시 변경하지 않는다. 도착 0개는 버튼을 한 번 더 눌러 확인한다. 저장 완료된 도착 체크는 해제할 수 없다. 자동 지연 판정 시각은 정하지 않으며 미도착 알림은 외부로 보내지 않는다.

이 화면에는 통계 질문·장소 관리·예약·반환·로봇 동작을 연결하지 않았다. 이들은 기존 API 또는 후속 작업이다.

검사:

```powershell
python -m unittest discover -s tests
node --test tests/test_collection_desk.cjs
```
