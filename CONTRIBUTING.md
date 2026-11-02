# 함께 일하는 규칙

## 1. 브랜치
- `main`: 항상 실행되는 상태. 직접 push 하지 않는다.
- 업무 브랜치: `LF-번호-짧은-영문-설명` (예: `LF-3-vision-json`, `LF-8-db-schema`)
- 업무 하나 = 브랜치 하나. 끝나면 Pull Request로 합치고 브랜치는 지운다.

## 2. 커밋 메시지
- 형식: `LF-번호 무엇을 했는지 (한국어)` + 필요하면 빈 줄 뒤에 왜 바꿨는지
- 예: `LF-3 비전 결과를 고정 항목 JSON으로 출력`
- 기록을 지우는 명령(`git push --force`, `git reset --hard` 후 push)은 쓰지 않는다.

## 3. Pull Request
1. 브랜치를 push 하고 GitHub에서 Pull Request를 만든다.
2. 제목은 커밋 메시지와 같은 형식, 본문에 Jira 번호·바꾼 내용·확인 방법을 적는다.
3. 팀원 1명 이상이 확인(Approve)하면 합친다.
4. Jira 업무 상태: 시작하면 '진행 중', PR을 올리면 '검토 중', 합치고 완료 기준을 채우면 '완료'.

## 4. 올리면 안 되는 것
- `.env`(디스코드 봇 토큰, API 키 등 비밀값) → `.env.example`에 이름만 적는다
- 실제 개인정보, 가상 신분증 원본 사진, 물건 사진 원본
- `.venv/`, `node_modules/`, 모델 가중치처럼 큰 파일

## 5. 개발 환경
- 폴더와 파일 이름은 영문으로 쓴다.
- 파이썬은 가상환경(`.venv`)에서 개발한다. 쓰는 패키지는 `requirements.txt`에 적는다.

## 6. 처음 한 번 하는 일 (팀원)
1. 초대 메일 또는 GitHub 알림에서 조직 초대를 수락한다.
2. 저장소를 내 PC에 clone 한다(README의 "시작하기").
3. `git config user.name "내 이름"` / `git config user.email "GitHub에 등록한 메일"`을 설정한다.
