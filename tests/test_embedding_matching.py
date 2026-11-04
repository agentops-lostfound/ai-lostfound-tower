import unittest
from unittest import mock
import tempfile
import numpy as np
from matching.embedding import MiniLMRanker, feature_text, read_candidates, normalized


class MatchingTests(unittest.TestCase):
    def test_failed_and_empty_features_not_ranked(self):
        report = {"objects": [
            {"id":0,"class_name":"cell phone","qwen":{"status":"failed","features":None}},
            {"id":1,"qwen":{"status":"ok","features":{"category":"unknown"}}},
            {"id":2,"qwen":{"status":"ok","features":{"colors":["blue"]}}}]}
        candidates, skipped = read_candidates(report)
        self.assertEqual([c["id"] for c in candidates], [2])
        self.assertEqual(len(skipped), 2)
        self.assertNotIn("cell phone", candidates[0]["text"])
        self.assertEqual(feature_text({"sticker_status":"unknown"}), "")
        self.assertIn("no stickers", feature_text({"sticker_status":"absent"}))

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            read_candidates({"objects":[{"id":1},{"id":1}]})

    def test_cosine_normalization_and_invalid_vector(self):
        np.testing.assert_allclose(normalized([[3,4]]), [[.6,.8]])
        with self.assertRaises(ValueError):
            normalized([[0,0]])

    def test_candidate_cache_invalidates_when_text_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ranker=MiniLMRanker.__new__(MiniLMRanker)
            from pathlib import Path
            ranker.cache=Path(tmp)
            ranker.revision="test"
            ranker.model=mock.Mock()
            vector=np.zeros(384,dtype=np.float32)
            vector[0]=1
            ranker.model.embed.side_effect=lambda texts: [vector for _ in texts]
            objects=[{"id":5,"text":"blue phone"}]
            self.assertEqual(ranker.prepare(objects)["new_embeddings"],1)
            self.assertEqual(ranker.prepare(objects)["cache_hits"],1)
            self.assertEqual(ranker.prepare([{"id":5,"text":"white phone"}])["new_embeddings"],1)
            ranking, _=ranker.rank("white mobile device")
            self.assertEqual(ranking[0]["id"],5)
            self.assertAlmostEqual(ranking[0]["cosine_similarity"],1)
            with self.assertRaises(ValueError):
                ranker.rank("\uac80\uc815 USB")
            with self.assertRaises(ValueError):
                ranker.rank(" ")
