"""Regression coverage without loading OPUS/Qwen/MiniLM."""
import unittest
from matching.korean_query import extract_korean, detail_translation_phrases, KoreanFirstParser


class FakeTranslator:
    model_id = 'fake'
    init_seconds = 0

    def __init__(self):
        self.received = None

    def parse(self, text, on_event=None):
        self.received = text
        return {'translation': 'A cartoon sticker on the back.',
                'timing': {'output_tokens': 8, 'parse_seconds': 0.0}}


class DetailPhraseFixTests(unittest.TestCase):
    def test_navy_phone_lead_in_removed(self):
        raw = '남색 휴대폰인데 뒷면에 캐릭터 스티커가 있어요.'
        parsed = extract_korean(raw)
        self.assertEqual(parsed['features']['category'], 'phone')
        self.assertEqual(parsed['features']['colors'], ['navy'])
        self.assertEqual(parsed['features']['sticker_status'], 'present')
        self.assertEqual(detail_translation_phrases(parsed), ['뒷면에 캐릭터 스티커가 있어요'])
        fake = FakeTranslator()
        result = KoreanFirstParser(translator=fake).parse(raw)
        self.assertEqual(fake.received, '뒷면에 캐릭터 스티커가 있어요')
        self.assertEqual(result['features']['free_text'], 'A cartoon sticker on the back.')

    def test_preserve_damage_and_location(self):
        text = '흰색 아이폰인데 뒷면이 많이 깨졌어요.'
        self.assertEqual(detail_translation_phrases(extract_korean(text)), ['뒷면이 많이 깨졌어요'])

    def test_preserve_detail_in_prefix(self):
        text = '캐릭터 스티커인데 뒷면에 붙어 있어요.'
        self.assertEqual(detail_translation_phrases(extract_korean(text)), [text[:-1]])

    def test_do_not_change_source_evidence(self):
        text = '남색 휴대폰인데 뒷면에 캐릭터 스티커가 있어요.'
        parsed = extract_korean(text)
        self.assertEqual(parsed['evidence']['free_phrases'][0]['text'], text[:-1])


if __name__ == '__main__':
    unittest.main()
