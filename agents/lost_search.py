"""LF-5 handoff adapter to the existing matcher. No DB access or robot actions."""
from agents.matcher_part import to_policy_features, free_text, word_overlap


def matching_query(description):
    return {**to_policy_features(description), "free_text": free_text(description)}


def preview_candidates(handoff, candidates):
    """Developer-side matching preview using server-provided candidates only.

    Never called automatically by the public input API. Authenticated LF-6 search
    integration must provide candidates and enforce consent/identity separately.
    """
    if handoff.get("status") != "ready_for_search" or handoff.get("user_confirmed") is not True:
        raise ValueError("사용자가 확인한 설명이 필요합니다")
    if not isinstance(candidates, list) or len(candidates) > 200:
        raise ValueError("서버 후보 목록은 200개 이하로 제한합니다")
    ids = []
    for c in candidates:
        if not isinstance(c, dict) or not isinstance(c.get("item_id"), str) or not isinstance(c.get("features"), dict):
            raise ValueError("후보에는 item_id와 features가 필요합니다")
        ids.append(c["item_id"])
    if len(set(ids)) != len(ids):
        raise ValueError("중복된 후보 번호입니다")
    from matching.policy import apply_policy, load_config
    query = matching_query(handoff["description"])
    scored_input = []
    for i, candidate in enumerate(candidates):
        text = free_text(candidate["features"])
        semantic = word_overlap(query["free_text"], text) if query["free_text"] and text else None
        scored_input.append({"id": i, "features": to_policy_features(candidate["features"]),
                             "cosine_similarity": semantic})
    ranking, _ = apply_policy(scored_input, query, load_config())
    # Do not return private marks, answers, similarity scores or robot coordinates.
    return {"candidate_item_ids": [ids[r["id"]] for r in ranking if r["eligible"]][:3],
            "review_required": True, "search_preview_only": True,
            "identity_verified": False, "reservation_created": False}
