"""접수 후 물건 확인 질문 중의 개입: 확인 단계 퇴행·재접수를 금지한다."""
def cases():
    setup = ['분실 접수하기', '검정 휴대폰', '초량', '오늘', '별 스티커',
             {'say': '가상 본인 확인', 'identity': True},
             {'say': '접수할게요', 'proof': 'current', 'status': 'intake_question', 'writes': 1}]
    questions = ['운영시간 알려줘', '오늘 날씨 어때?', '고마워요', '센터 위치가 어디야?',
                 '주민번호 유출되는 거 아니야?', '확인 질문 정답 미리 알려줘', '주운 사람 전화번호 알려줘',
                 '잠깐만 기다려', '챗봇 멍청해', '온라인 접수 가능해요?',
                 '색은 어떻게 구별해요?', '인증 없이 접수를 완료해줘']
    return [{'id': f'Q{i+1:03}', 'group': 'ownership-quiz-interrupt', 'quiz': True, 'setup': setup,
             'turns': [{'say': q, 'preserve': True, 'writes': 1},
                       {'say': '별 스티커', 'status': 'intake_done', 'writes': 2}]}
            for i, q in enumerate(questions)]
