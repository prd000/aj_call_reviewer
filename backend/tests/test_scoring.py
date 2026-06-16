"""Unit tests for backend/modules/scoring.py (Section 5 refactor)."""
import pytest
from modules.scoring import overall_score, score_tier


# ---------------------------------------------------------------------------
# score_tier boundaries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ratio,expected", [
    (1.0, "high"),
    (0.7, "high"),
    (0.699, "mid"),
    (0.4, "mid"),
    (0.399, "low"),
    (0.0, "low"),
])
def test_score_tier_boundaries(ratio, expected):
    assert score_tier(ratio) == expected


# ---------------------------------------------------------------------------
# overall_score
# ---------------------------------------------------------------------------

def test_overall_score_none_input():
    assert overall_score(None) == (None, None)


def test_overall_score_empty_dict():
    assert overall_score({}) == (None, None)


def test_overall_score_no_categories():
    assert overall_score({"categories": []}) == (None, None)


def test_overall_score_no_scored_categories():
    cats = [{"name": "A", "feedback": "ok"}]  # missing score
    assert overall_score({"categories": cats}) == (None, None)


def test_overall_score_basic():
    cats = [{"score": 7, "max_score": 10}]
    score, max_s = overall_score({"categories": cats})
    assert score == 7.0
    assert max_s == 10.0


def test_overall_score_sum_of_sum():
    cats = [
        {"score": 5, "max_score": 10},
        {"score": 3, "max_score": 5},
    ]
    # (5+3)/(10+5) * 10 = 80/15 = 5.333... → 5.3
    score, _ = overall_score({"categories": cats})
    assert score == 5.3


def test_overall_score_mixed_scored_unscored():
    cats = [
        {"score": 8, "max_score": 10},
        {"name": "unscored"},  # no score key
    ]
    score, _ = overall_score({"categories": cats})
    assert score == 8.0


def test_overall_score_default_max():
    cats = [{"score": 5}]  # no max_score defaults to 10
    score, _ = overall_score({"categories": cats})
    assert score == 5.0
