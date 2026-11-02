# discord_ops — 디스코드 관제 화면 (LF-17)

`reporter.py`: 단계별 진행·오류·점수를 채널별 웹후크로 보내고, 보내기 전에 개인정보 모양(전화번호·주민번호·카드번호·이메일)을 검사해 막는다.

| 채널 | .env 이름 |
| --- | --- |
| #📊관제-진행 | `DISCORD_WEBHOOK_PROGRESS` |
| #🚨관제-알림 | `DISCORD_WEBHOOK_ALERT` |
| #📈평가-점수 | `DISCORD_WEBHOOK_SCORE` |

- 채널별 값이 비어 있으면 `DISCORD_WEBHOOK_URL`(시험 채널) 하나로 보내고 제목 앞에 채널 이름을 붙인다
- 메시지는 물건 번호·사례 번호로만 만든다. 이름은 글자 모양으로 찾을 수 없으므로 애초에 넣지 않는다
- #💬관제-질문(Claude 연결)은 로컬 Claude Code 디스코드 채널 기능으로 운영(시연 PC에서 세션이 켜져 있어야 함)
