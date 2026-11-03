"""Attribute filter first; embed only free observations of eligible candidates."""
import re
from .embedding import MiniLMRanker, feature_text
from .policy import attributes, apply_policy


def free_feature_text(features):
    return feature_text({k: v for k, v in features.items()
                         if k in ("shape", "materials", "logos_or_text", "distinctive_features", "stickers")}
                        | {"sticker_status": "present" if features.get("stickers") else "unknown"})


class HybridMatcher:
    def __init__(self, config, threads=2, offline=False, ranker=None):
        self.config = config
        self.threads, self.offline = threads, offline
        self.ranker = ranker

    def match(self, candidates, conditions):
        attributes(conditions)
        if set(conditions) - {"category", "colors", "sticker_status", "free_text"}:
            raise ValueError("Unsupported query feature key")
        text = conditions.get("free_text", "")
        if not isinstance(text, str) or re.search(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]", text):
            raise ValueError("free_text must be English text; translation is not implemented")
        text = text.strip()
        preliminary, _ = apply_policy([{**c, "cosine_similarity": None} for c in candidates], conditions, self.config)
        eligible = [c for c in preliminary if c["eligible"]]
        embeddable = [{**c, "text": free_feature_text(c["features"])} for c in eligible]
        embeddable = [c for c in embeddable if c["text"]]
        semantic, timing = [], {}
        if text and embeddable:
            if self.ranker is None:
                self.ranker = MiniLMRanker(threads=self.threads, offline=self.offline)
            timing.update(self.ranker.prepare(embeddable))
            semantic, measured = self.ranker.rank(text)
            timing.update(measured)
        by_id = {c["id"]: c["cosine_similarity"] for c in semantic}
        inputs = [{**c, "cosine_similarity": by_id.get(c["id"]),
                   "semantic_missing": bool(text and c["eligible"] and c["id"] not in by_id)} for c in preliminary]
        ranking, decision = apply_policy(inputs, conditions, self.config)
        return ranking, decision, {"filtered_candidates": len(candidates)-len(eligible),
                                  "embedded_candidates": len(semantic), **timing}
