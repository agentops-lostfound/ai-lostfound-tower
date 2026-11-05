import unittest
from matching.korean_query import extract_korean, KoreanFirstParser


class KoreanEvidenceTests(unittest.TestCase):
    def test_unsupported_item_preserves_source_and_blocks_color_only_match(self):
        text='빨간색 우산을 잃어버렸어요'
        r=extract_korean(text)
        self.assertEqual(r['features']['category'],'unknown')
        e=r['evidence']['unsupported_categories'][0]
        self.assertEqual(text[e['start']:e['end']],'우산')
        self.assertIn('unsupported_category_mention',r['match_block_reasons'])

    def test_unknown_item_blocks_even_with_known_color(self):
        r=extract_korean('검정색 물건인데 정확히 모르겠어요')
        self.assertIn('unresolved_item_category',r['match_block_reasons'])

    def test_category_resemblance_is_not_identity(self):
        r=extract_korean('휴대폰처럼 생긴 검정색 물건이에요')
        self.assertEqual(r['features']['category'],'unknown')
        self.assertIn('uncertain_category_mention',r['match_block_reasons'])

    def test_missing_logo_does_not_invalidate_known_item(self):
        r=extract_korean('검은색 보조배터리인데 글자는 잘 기억나지 않아요')
        self.assertEqual(r['match_block_reasons'],[])
        self.assertEqual(r['features']['category'],'power_bank')

    def test_negated_unsupported_item_does_not_override_phone(self):
        r=extract_korean('우산이 아니고 검정 휴대폰이에요')
        self.assertEqual(r['match_block_reasons'],[])

    def test_input_guard_survives_removing_blanket_review_flag(self):
        from matching.query_parser import guard_decision
        parsed={'needs_clarification':False,'requires_review':False,
                'match_block_reasons':['unresolved_item_category']}
        for status in ['matched','no_match']:
            decision=guard_decision({'status':status,'selected_id':9},parsed)
            self.assertEqual(decision['status'],'needs_confirmation')
            self.assertIsNone(decision['selected_id'])
            self.assertIn('unresolved_item_category',decision['reasons'])

    def test_negation_and_components(self):
        r=extract_korean('검정색 아니고 흰색 아이폰이에요. 뒷면이 심하게 깨져 있어요.')
        self.assertEqual(r['features']['colors'],['white'])
        r=extract_korean('검은 폰이고 검정 화면과 케이스가 있고 스티커는 없어요.')
        self.assertEqual(r['features']['colors'],['black'])
        self.assertEqual(r['features']['sticker_status'],'absent')

    def test_uncertainty_has_local_scope(self):
        self.assertEqual(extract_korean('남색인지 검정인지 모르는 지갑')['features']['colors'],[])
        r=extract_korean('잃어버린 곳은 기억 안 나는데 흰색 아이폰 뒷면이 많이 깨졌어요.')
        self.assertEqual(r['features']['colors'],['white'])

    def test_evidence_is_exact_source_and_preserves_damage(self):
        text='제 폰 하얀색 아이폰인데 뒤가 많이 깨졌어요.'
        r=extract_korean(text)
        for spans in r['evidence'].values():
            for s in spans:
                self.assertEqual(text[s['start']:s['end']],s['text'])
        self.assertIn('뒤가 많이 깨졌어요',r['evidence']['free_phrases'][0]['text'])

    def test_scoped_absence_and_missing_information(self):
        self.assertEqual(extract_korean('지갑 뒷면에는 스티커가 없어요')['features']['sticker_status'],'unknown')
        r=extract_korean('지갑 잃어버렸어요')
        self.assertEqual(r['features'],{'category':'wallet','colors':[],'sticker_status':'unknown'})

    def test_latin_brand_has_source_evidence(self):
        r=extract_korean('SanDisk USB를 찾고 있어요. 색은 기억나지 않아요.')
        self.assertEqual(r['evidence']['logos_or_text'][0]['text'],'SanDisk')
