"""Wire-format regression checks independent of GPU/model downloads."""
import json
from types import SimpleNamespace
import unittest

from tools.qwen_compact import convert, install


class CompactTrialTests(unittest.TestCase):
    def test_observations_and_sticker_positions_preserved(self):
        row = ['phone', ['blue'], 'rectangle', [], ['ABC'], 'present',
               [['star', 'bottom right']], ['three lenses']]
        result = convert(json.dumps(row))
        self.assertEqual(result['stickers'], [{'shape': 'star', 'position': 'bottom right'}])
        self.assertEqual(result['logos_or_text'], ['ABC'])
        self.assertEqual(result['distinctive_features'], ['three lenses'])

    def test_truncation_and_missing_positions_rejected(self):
        for raw in ('[]', '["phone"', '{}', '[null,[],null,[],[],"unknown",[],[],0]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                convert(raw)

    def test_malformed_sticker_and_nonfinite_rejected(self):
        for sticker in ('star', ['star'], [[1, 'right']], [['star', 'right', 'extra']]):
            row = ['phone', [], None, [], [], 'present', sticker, []]
            with self.subTest(sticker=sticker), self.assertRaises(ValueError):
                convert(json.dumps(row))
        with self.assertRaises(ValueError):
            convert('["phone",[],NaN,[],[],"unknown",[],[]]')

    def test_upstream_validation_is_still_required(self):
        calls = []

        def reject(raw):
            calls.append(json.loads(raw))
            raise ValueError('upstream rejects category or type')

        module = SimpleNamespace(validate_response=reject, PROMPT='', OUTPUT_TEMPLATE={})
        install(module)
        with self.assertRaisesRegex(ValueError, 'upstream rejects'):
            module.validate_response('["invalid",[],null,[],[],"unknown",[],[]]')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
