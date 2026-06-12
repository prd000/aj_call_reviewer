"""Tests for reviewer._parse_criterion_json — the tolerant JSON parser added
in the 2026-06-12 fix to handle DeepSeek's frequent malformed-JSON responses."""
import pytest
from modules.reviewer import _parse_criterion_json


def test_parse_valid_json():
    result = _parse_criterion_json('{"score": 7, "feedback": "Good job"}')
    assert result["score"] == 7
    assert result["feedback"] == "Good job"


def test_parse_fenced_json():
    content = '```json\n{"score": 8, "feedback": "Solid performance"}\n```'
    result = _parse_criterion_json(content)
    assert result["score"] == 8
    assert result["feedback"] == "Solid performance"


def test_parse_fenced_no_language():
    content = '```\n{"score": 5, "feedback": "Needs work"}\n```'
    result = _parse_criterion_json(content)
    assert result["score"] == 5


def test_parse_json_with_trailing_prose():
    """Handles LLM responses where JSON is followed by an explanation."""
    content = '{"score": 6, "feedback": "Could improve"}\n\nHere is my reasoning...'
    result = _parse_criterion_json(content)
    assert result["score"] == 6
    assert result["feedback"] == "Could improve"


def test_parse_json_with_leading_prose():
    """Handles LLM responses where JSON is preceded by an intro sentence."""
    content = 'Here is the evaluation:\n{"score": 9, "feedback": "Excellent"}'
    result = _parse_criterion_json(content)
    assert result["score"] == 9


def test_parse_unrecoverable_no_braces():
    with pytest.raises(ValueError, match="No JSON object found"):
        _parse_criterion_json("This is not JSON at all.")


def test_parse_unrecoverable_unbalanced_braces():
    with pytest.raises((ValueError, Exception)):
        _parse_criterion_json('{"score": 7, "feedback": "ok"')


def test_parse_missing_score_key():
    with pytest.raises(ValueError, match="missing score/feedback"):
        _parse_criterion_json('{"feedback": "Good"}')


def test_parse_missing_feedback_key():
    with pytest.raises(ValueError, match="missing score/feedback"):
        _parse_criterion_json('{"score": 7}')


def test_parse_extra_keys_are_allowed():
    result = _parse_criterion_json('{"score": 4, "feedback": "ok", "extra": "ignored"}')
    assert result["score"] == 4
    assert result["feedback"] == "ok"
