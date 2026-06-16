def score_tier(ratio: float) -> str:
    """Return 'high' | 'mid' | 'low' for a score ratio.

    Thresholds: >= 0.7 is high, >= 0.4 is mid, else low.
    Mirrors SCORE_HIGH / SCORE_MID in frontend/src/lib/scoreColor.js.
    """
    return "high" if ratio >= 0.7 else "mid" if ratio >= 0.4 else "low"


def overall_score(review_results: dict | None) -> tuple[float | None, float | None]:
    """Return (normalized_score, 10.0) for a review result dict.

    Computes sum(scored.score) / sum(scored.max_score) * 10, rounded to one
    decimal. Returns (None, None) when no scored categories are present.

    This is the single canonical implementation; callers in reviewer.py,
    history_chat.py, and _review_summary previously duplicated this math.
    """
    if not review_results:
        return None, None
    categories = review_results.get("categories") or []
    scored = [c for c in categories if isinstance(c.get("score"), (int, float))]
    if not scored:
        return None, None
    total_score = sum(c["score"] for c in scored)
    total_max = sum(c.get("max_score", 10) for c in scored)
    if not total_max:
        return None, None
    return round((total_score / total_max) * 10, 1), 10.0
