import unittest
from matching.korean_query import extract_korean, KoreanFirstParser


class KoreanEvidenceTests(unittest.TestCase):
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
