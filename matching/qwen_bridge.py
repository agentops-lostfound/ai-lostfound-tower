"""LF-20 bridge: compare a claimant query with ORIGINAL Qwen features.

The team's vision_topview contract is preserved. Inspection mode deliberately
returns 'uncertain', never 'matched', so the supervisor cannot move a robot.
No PII-bearing Qwen text is echoed into the public result.
"""
from __future__ import annotations

import math

from agents.contracts import validate_detection


def _hold(reason: str) -> dict:
    return {"status": "uncertain", "index": None, "score": 0.0,
            "margin": 0.0, "ranking": [], "reason": reason}


class QwenMatchingPart:
    """Inject existing HybridMatcher and a real result_with_qwen.json dict.

    Pass the same report to VisionPart and this part. Query follows LF-20's
    structured schema: category, colors, sticker_status, free_text (English).
    This adapter is intentionally an inspection-only integration.
    """

    def __init__(self, report: dict, matcher):
        self.report = report
        self.matcher = matcher
        self.last_diagnostics = None

    def match_item(self, query: dict, detections: list[dict]) -> dict:
        self.last_diagnostics = None
        if not isinstance(query, dict) or not isinstance(detections, list):
            return _hold("invalid_input")
        if not isinstance(self.report, dict):
            return _hold("invalid_report")
        if not isinstance(self.report.get("sequence"), dict) or self.report["sequence"].get("status") != "complete":
            return _hold("sequence_incomplete")
        if not detections:
            return _hold("no_contract_detections")
        if any(not isinstance(d, dict) or validate_detection(d) for d in detections):
            return _hold("invalid_contract_detection")
        objects = self.report.get("objects")
        if not isinstance(objects, list) or len(objects) != len(detections):
            return _hold("incomplete_scene")
        # Canonical adapter uses vision_id; retain the older object_id contract.
        if any("vision_id" in d and "object_id" in d and
               (type(d["object_id"]) is not int or d["vision_id"] != d["object_id"])
               for d in detections):
            return _hold("conflicting_ids")
        ids = [d.get("vision_id", d.get("object_id")) for d in detections]
        if any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
            return _hold("invalid_ids")
        by_id = {o["id"]: o for o in objects if isinstance(o, dict) and type(o.get("id")) is int}
        if len(by_id) != len(objects) or set(by_id) != set(ids):
            return _hold("id_mismatch")
        for det, object_id in zip(detections, ids):
            original = by_id[object_id]
            qwen = original.get("qwen")
            if not isinstance(qwen, dict) or qwen.get("status") != "ok":
                return _hold("qwen_not_ok")
            def same_geometry(actual, raw):
                if (not isinstance(raw, (list, tuple)) or len(raw) != len(actual)
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in raw)
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in actual)):
                    return False
                expected = [round(float(v), 1) for v in raw] if "vision_id" in det else list(raw)
                return list(actual) == expected
            if not same_geometry(det["box"], original.get("bbox")) or not same_geometry(det["center"], original.get("center_px")):
                return _hold("geometry_mismatch")

        # The existing reader preserves the original Qwen fields, including
        # stickers, distinctive_features, and original English color names.
        from matching.embedding import read_candidates
        try:
            candidates, skipped = read_candidates(self.report)
            if skipped or len(candidates) != len(detections):
                return _hold("candidates_skipped")
            ranking, decision, _timing = self.matcher.match(candidates, query)
        except (ValueError, TypeError, RuntimeError, OSError, ImportError):
            return _hold("matcher_error")

        id_to_index = {id_: i for i, id_ in enumerate(ids)}
        if not isinstance(ranking, list) or not isinstance(decision, dict):
            return _hold("invalid_match_result")
        if any(not isinstance(row, dict) or row.get("id") not in id_to_index for row in ranking):
            return _hold("unrecognized_ranked_id")
        try:
            public_ranking = [{"object_id": row["id"], "index": id_to_index[row["id"]],
                               "score": round(float(row["final_score"]), 4),
                               "eligible": bool(row["eligible"]),
                               "rejection_reasons": row.get("rejection_reasons", []),
                               "attribute_scores": row.get("attribute_scores", {}),
                               "cosine_similarity": row.get("cosine_similarity")}
                              for row in ranking]
            if any(not math.isfinite(r["score"]) for r in public_ranking):
                return _hold("invalid_score")
            margin = decision.get("margin")
            margin = float(margin) if margin is not None else 0.0
            if not math.isfinite(margin):
                return _hold("invalid_margin")
        except (KeyError, TypeError, ValueError):
            return _hold("invalid_match_result")
        best_id = decision.get("top_candidate_id")
        top = next((r for r in public_ranking if r["object_id"] == best_id), None)
        self.last_diagnostics = {
            "raw_qwen_features_used": True,
            "scene_object_count": len(objects),
            "engine_status": decision.get("status"),
            "engine_top_candidate_id": best_id,
            "engine_decision": decision,
            "ranking": public_ranking,
            "robot_authorized": False,
        }
        # Never return MATCH_OK while real robot calibration, claimant identity,
        # staff verification, and return authorization are not integrated.
        return {"status": "uncertain", "index": top["index"] if top else None,
                "score": top["score"] if top else 0.0,
                "margin": round(margin, 4),
                "ranking": [r["index"] for r in public_ranking],
                "reason": "inspection_only_staff_review_required"}
