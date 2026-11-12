"""필수 단어 존재뿐 아니라 질문 결론·최종 사용자 행동을 검사한다."""
import unittest
from agents.guidance import Guidance
from agents.chat_rag import GroundedRag, answer_gap


class ColloquialGoalTest(unittest.TestCase):
    def test_location_is_answered_before_unrequested_pickup_steps(self):
        rag = GroundedRag(Guidance())
        for q in ('센터가 어디야?', '본센터 위치 좀', '본센터가 어디에 있나요?', '센터 어디?', '본센터 키오스크 위치 알려줘'):
            with self.subTest(q=q):
                r = rag.ask(q)
                self.assertIn('부산역', r['answer'].split('.')[0])
                self.assertNotIn('제출보관함', r['answer'])
                self.assertEqual(answer_gap(q, '물건 확인을 한 뒤 로봇을 기다리세요. 본센터는 부산역에 있어요.'), 'intent')

    def test_short_pickup_question_includes_final_user_action(self):
        rag = GroundedRag(Guidance())
        for q in ('물건 받으려면 어떻게 해?', '물건 어떻게 받아?', '물건 받는 방법 알려줘', '수령 방법이 뭐예요?'):
            with self.subTest(q=q):
                a = rag.ask(q)['answer']
                for required in ('찾기 번호', '신분 확인', '제출보관함', '물건 받았어요'):
                    self.assertIn(required, a)
                self.assertEqual(answer_gap(q, '신분 확인 후 로봇이 꺼내 줘요.'), 'intent')

    def test_special_policy_is_not_replaced_by_normal_pickup_steps(self):
        from agents.chat_answer_goal import question_goal
        for q in ('택배로 물건 받는 방법은?', '신분증이 없는데 물건 받으려면 어떻게 해?',
                  '대리 수령 방법 알려줘', '주운 물건 맡기는 방법', '찾기 번호 받는 방법'):
            self.assertNotEqual(question_goal(q), 'pickup_steps', q)

    def test_compound_search_and_time_questions_keep_existing_routes(self):
        from agents.chat_answer_goal import question_goal
        for q in ('흰 휴대폰 있는지랑 본센터 위치 알려줘',
                  '립밤을 잃어버렸는데 빨간색이고 어제 초량역이었어요. 이게 있으면 어떻게 받는지도 같이 알려주세요',
                  '받으려면 언제 가야 해요?'):
            self.assertIsNone(question_goal(q), q)
