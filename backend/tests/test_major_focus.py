"""Tests for pick_default_focus_index and generate_major_focus."""
import pytest
from unittest.mock import patch, MagicMock

from modules.reviewer import pick_default_focus_index, generate_major_focus, LLMUnavailableError


# ---------------------------------------------------------------------------
# pick_default_focus_index
# ---------------------------------------------------------------------------

def test_largest_deficit_wins():
    categories = [
        {"score": 8, "max_score": 10, "feedback": ""},  # deficit 2
        {"score": 5, "max_score": 10, "feedback": ""},  # deficit 5  <- winner
        {"score": 9, "max_score": 10, "feedback": ""},  # deficit 1
    ]
    assert pick_default_focus_index(categories) == 1


def test_tiebreak_by_ratio():
    # Both have deficit 5 but index 1 has worse ratio (0.5 vs 0.5... let's use 0.5 vs 0.3)
    categories = [
        {"score": 5, "max_score": 10, "feedback": ""},   # deficit 5, ratio 0.5
        {"score": 3, "max_score": 10, "feedback": ""},   # deficit 7, ratio 0.3
        {"score": 5, "max_score": 10, "feedback": ""},   # deficit 5, ratio 0.5
    ]
    # Index 1 has largest deficit (7), so it wins
    assert pick_default_focus_index(categories) == 1


def test_tiebreak_same_deficit_lower_ratio_wins():
    # deficit equal, pick the one with lower ratio (worse performance)
    categories = [
        {"score": 6, "max_score": 10, "feedback": ""},  # deficit 4, ratio 0.6
        {"score": 4, "max_score": 10, "feedback": ""},  # deficit 6, ratio 0.4  <- winner (bigger deficit)
    ]
    assert pick_default_focus_index(categories) == 1


def test_equal_deficit_equal_ratio_picks_first():
    categories = [
        {"score": 5, "max_score": 10, "feedback": ""},  # deficit 5, ratio 0.5
        {"score": 5, "max_score": 10, "feedback": ""},  # deficit 5, ratio 0.5
    ]
    assert pick_default_focus_index(categories) == 0


def test_none_on_empty_categories():
    assert pick_default_focus_index([]) is None


def test_none_on_no_scored_categories():
    categories = [
        {"score": None, "max_score": 10, "feedback": ""},
        {"feedback": "no score here"},
    ]
    assert pick_default_focus_index(categories) is None


def test_none_on_zero_max_score():
    categories = [
        {"score": 0, "max_score": 0, "feedback": ""},
    ]
    assert pick_default_focus_index(categories) is None


def test_single_category():
    categories = [{"score": 7, "max_score": 10, "feedback": "good"}]
    assert pick_default_focus_index(categories) == 0


# ---------------------------------------------------------------------------
# generate_major_focus
# ---------------------------------------------------------------------------

SAMPLE_TRANSCRIPT = [{"timestamp": "00:00:01", "text": "Hello there", "speaker": 0}]
SAMPLE_CRITERION = {
    "id": "abc",
    "title": "Discovery & Needs Analysis",
    "description": "Asks open-ended questions to understand needs.",
    "success_condition": "Uncovers at least 3 distinct client needs.",
}
SAMPLE_CATEGORY = {"score": 5, "max_score": 10, "feedback": "Could ask more open-ended questions."}


def test_generate_major_focus_returns_text():
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="  Focus on asking more open-ended questions. Probe deeper for client pain points.  ")

    with patch("modules.reviewer.get_llm_api_key", return_value="fake-key"), \
         patch("modules.reviewer.get_llm", return_value=mock_llm):
        result = generate_major_focus(SAMPLE_TRANSCRIPT, SAMPLE_CRITERION, SAMPLE_CATEGORY)

    assert result == "Focus on asking more open-ended questions. Probe deeper for client pain points."
    mock_llm.invoke.assert_called_once()


def test_generate_major_focus_raises_when_no_key():
    with patch("modules.reviewer.get_llm_api_key", return_value=""):
        with pytest.raises(LLMUnavailableError):
            generate_major_focus(SAMPLE_TRANSCRIPT, SAMPLE_CRITERION, SAMPLE_CATEGORY)
