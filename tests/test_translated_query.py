import unittest
from matching.translated_query import extract_english


class EnglishRuleTests(unittest.TestCase):
    def test_damage_translation_preserved_verbatim(self):
        text = 'My phone is a white iPhone and its back is badly cracked.'
        f = extract_english(text)['features']
        self.assertEqual((f['category'], f['colors'], f['sticker_status']), ('phone', ['white'], 'unknown'))
        self.assertEqual(f['free_text'], text)

    def test_compound_color_and_category(self):
        f = extract_english('A navy blue card wallet.')['features']
        self.assertEqual(f['colors'], ['navy'])
        self.assertEqual(f['category'], 'card_wallet')

    def test_negation_and_alternatives_are_reviewed(self):
        r = extract_english('My phone is not blue but black, without stickers.')
        self.assertEqual(r['features']['colors'], ['black'])
        self.assertEqual(r['features']['sticker_status'], 'absent')
        self.assertTrue(r['needs_clarification'])
        self.assertEqual(extract_english('My wallet is blue or black.')['features']['colors'], [])

    def test_scoped_sticker_absence(self):
        r = extract_english('There are no stickers on the back of my wallet.')
        self.assertEqual(r['features']['sticker_status'], 'unknown')
        self.assertTrue(r['needs_clarification'])
