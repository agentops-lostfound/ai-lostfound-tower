from types import SimpleNamespace
import unittest

from tools.qwen_generation_trial import install_no_repeat


class GenerationTrialTests(unittest.TestCase):
    def test_only_repeat_option_added(self):
        calls = []
        result = object()

        def generate(*args, **kwargs):
            calls.append((args, kwargs))
            return result

        model = SimpleNamespace(generate=generate)
        install_no_repeat(model, 12)
        self.assertIs(model.generate('image', max_new_tokens=512, do_sample=False), result)
        self.assertEqual(calls, [(('image',), {'no_repeat_ngram_size': 12,
                                             'max_new_tokens': 512, 'do_sample': False})])
        with self.assertRaises(ValueError):
            model.generate(no_repeat_ngram_size=8)

    def test_invalid_size_rejected(self):
        for size in (0, 1, -1):
            with self.assertRaises(ValueError):
                install_no_repeat(SimpleNamespace(), size)
