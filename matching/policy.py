"""Configurable attribute scoring and conservative decisions, without translation."""
import math
from pathlib import Path
import yaml

DEFAULT_CONFIG = Path(__file__).parent / "configs/matching.yaml"
ALIASES = {
    "phone": ("smartphone", "cell phone", "mobile phone", "handset"),
    "usb": ("usb drive", "flash drive", "usb flash drive"),
    "card_wallet": ("card wallet", "cardholder", "card holder"),
    "blue": ("파란", "파란색", "푸른색", "퍼런색", "파랑"),
    "navy": ("남색", "곤색", "네이비", "navy blue"),
    "red": ("빨간색", "빨강", "붉은색", "뻘건색"),
    "white": ("흰색", "하얀색"), "black": ("검정", "검은색"),
    "yellow": ("노란색", "노랑"),
}


def canonical(value):
    if not isinstance(value, str):
        raise ValueError("Attribute values must be strings")
    value = " ".join(value.lower().strip().split())
    if value in ("", "unknown", "other"):
        return None
    return next((key for key, names in ALIASES.items() if value in names), value)


def attributes(features):
    if not isinstance(features, dict):
        raise ValueError("Query features must be an object")
    colors = features.get("colors", [])
    if not isinstance(colors, list):
        raise ValueError("colors must be a list")
    status = features.get("sticker_status", "unknown")
    if status not in ("unknown", "present", "absent"):
        raise ValueError("sticker_status must be unknown, present or absent")
    return {"category": canonical(features.get("category", "unknown")),
            "color": [c for value in colors if (c := canonical(value))],
            "sticker": None if status == "unknown" else status}


def load_config(path=DEFAULT_CONFIG):
    try:
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML config: {error}") from error
    required = {"reject_category_mismatch", "reject_clear_color_mismatch", "weights", "decision", "color_similarity", "category_similarity"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("Config must contain exactly: " + ", ".join(sorted(required)))
    for key in ("reject_category_mismatch", "reject_clear_color_mismatch"):
        if type(config[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    def number(value):
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
    for section, keys in (("weights", {"category", "color", "sticker", "semantic"}),
                          ("decision", {"min_score", "min_margin", "min_attribute_coverage", "min_attribute_score"})):
        values = config[section]
        if not isinstance(values, dict) or set(values) != keys or not all(number(v) for v in values.values()):
            raise ValueError(f"Invalid {section}: use expected keys and finite numbers in 0..1")
    if config["weights"]["semantic"] <= 0 or sum(config["weights"].values()) <= 0:
        raise ValueError("semantic weight must be positive")
    for name in ("color_similarity", "category_similarity"):
        validate_pairs(config[name], number)
    return config


def validate_pairs(pairs, number):
    if not isinstance(pairs, dict):
        raise ValueError("color_similarity must be a mapping")
    for left, row in pairs.items():
        if canonical(left) != left or not isinstance(row, dict):
            raise ValueError("Use canonical color names in color_similarity")
        for right, score in row.items():
            if canonical(right) != right or not number(score):
                raise ValueError("Invalid color similarity")
            reverse = pairs.get(right, {}).get(left)
            if reverse is not None and reverse != score:
                raise ValueError("Conflicting symmetric color scores")


def pair_score(left, right, pairs):
    if left == right:
        return 1.0
    return pairs.get(left, {}).get(right, pairs.get(right, {}).get(left, 0.0))


def color_score(query, observed, config):
    pairs = config["color_similarity"]
    def pair(left, right):
        if left == right:
            return 1.0
        return pairs.get(left, {}).get(right, pairs.get(right, {}).get(left, 0.0))
    # Each explicitly requested color must have support; extra observed colors are allowed.
    return sum(max(pair(q, c) for c in observed) for q in query) / len(query)


def apply_policy(ranking, query_features, config):
    query = attributes(query_features)
    requested = [key for key, value in query.items() if value]
    scored = []
    for item in ranking:
        observed = attributes(item["features"])
        cosine = item.get("cosine_similarity")
        scores = {"semantic": max(0.0, cosine)} if cosine is not None else {}
        reasons, unknown = [], []
        for key in requested:
            if not observed[key]:
                unknown.append(key)
                continue
            score = (color_score(query[key], observed[key], config) if key == "color" else
                     pair_score(query[key], observed[key], config["category_similarity"]) if key == "category" else
                     float(query[key] == observed[key]))
            scores[key] = score
            if score == 0 and ((key == "category" and config["reject_category_mismatch"]) or
                               (key == "color" and config["reject_clear_color_mismatch"])):
                reasons.append(key + "_mismatch")
        weight = config["weights"]
        # Unknown requested attributes keep their weight but contribute zero; missing is not contradiction.
        active = (["semantic"] if cosine is not None else []) + requested
        total = sum(weight[k] for k in active)
        final = sum(weight[k] * scores.get(k, 0) for k in active) / total if total else 0.0
        scored.append({**item, "final_score": final, "attribute_scores": scores,
                       "unknown_attributes": unknown, "rejection_reasons": reasons,
                       "eligible": not reasons,
                       "attribute_coverage": (len(requested)-len(unknown))/len(requested) if requested else 0})
    scored.sort(key=lambda item: (not item["eligible"], -item["final_score"]))
    eligible = [item for item in scored if item["eligible"]]
    if not eligible:
        return scored, {"status": "no_match", "selected_id": None, "reason": "no_eligible_candidates"}
    top = eligible[0]
    margin = top["final_score"]-eligible[1]["final_score"] if len(eligible) > 1 else None
    thresholds = config["decision"]
    reasons = []
    if not requested:
        reasons.append("no_structured_constraints")
    if top["attribute_coverage"] < thresholds["min_attribute_coverage"]:
        reasons.append("unknown_requested_attributes")
    if any(top["attribute_scores"].get(k, 0) < thresholds["min_attribute_score"] for k in requested):
        reasons.append("weak_attribute_match")
    if top.get("semantic_missing"):
        reasons.append("missing_free_features")
    if top["final_score"] < thresholds["min_score"]:
        reasons.append("below_min_score")
    if margin is not None and margin < thresholds["min_margin"]:
        reasons.append("small_margin")
    return scored, {"status": "needs_confirmation" if reasons else "matched",
                    "selected_id": None if reasons else top["id"], "top_candidate_id": top["id"],
                    "margin": margin, "reasons": reasons}
