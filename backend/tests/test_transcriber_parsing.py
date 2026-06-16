"""
Unit tests for transcriber._parse_monologues and _seconds_to_timestamp.

Uses fabricated monologue objects (SimpleNamespace) — no Rev.ai API calls.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.transcriber import _parse_monologues, _seconds_to_timestamp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _elem(type_="text", value="", timestamp=None):
    """Create a fake Rev.ai element."""
    return SimpleNamespace(type_=type_, value=value, timestamp=timestamp)


def _mono(speaker=0, elements=None):
    """Create a fake Rev.ai monologue."""
    return SimpleNamespace(speaker=speaker, elements=elements or [])


# ---------------------------------------------------------------------------
# _seconds_to_timestamp
# ---------------------------------------------------------------------------

def test_seconds_to_timestamp_basic():
    assert _seconds_to_timestamp(5.0) == "00:00:05"
    assert _seconds_to_timestamp(65.0) == "00:01:05"
    assert _seconds_to_timestamp(3661.0) == "01:01:01"


def test_seconds_to_timestamp_zero():
    assert _seconds_to_timestamp(0) == "00:00:00"


def test_seconds_to_timestamp_truncates_fractional():
    # Fractional seconds are truncated (int cast), not rounded.
    assert _seconds_to_timestamp(5.9) == "00:00:05"


# ---------------------------------------------------------------------------
# _parse_monologues
# ---------------------------------------------------------------------------

def test_happy_path_single_monologue():
    """Text elements with a timestamp → one segment, correctly formatted."""
    monologue = _mono(speaker=1, elements=[
        _elem(type_="text", value="Hello ", timestamp=5.0),
        _elem(type_="text", value="there.", timestamp=None),
    ])
    result = _parse_monologues([monologue])
    assert len(result) == 1
    seg = result[0]
    assert seg["timestamp"] == "00:00:05"
    assert seg["text"] == "Hello there."
    assert seg["speaker"] == 1


def test_skips_monologue_with_all_none_timestamps():
    """If no text element has a timestamp, the monologue is skipped."""
    monologue = _mono(speaker=0, elements=[
        _elem(type_="text", value="Hi", timestamp=None),
        _elem(type_="text", value=" there", timestamp=None),
    ])
    result = _parse_monologues([monologue])
    assert result == []


def test_skips_monologue_with_empty_text():
    """If joined text is empty or whitespace, the monologue is skipped."""
    monologue = _mono(speaker=0, elements=[
        _elem(type_="text", value="   ", timestamp=10.0),
    ])
    result = _parse_monologues([monologue])
    assert result == []


def test_skips_monologue_with_whitespace_only_text():
    monologue = _mono(speaker=0, elements=[
        _elem(type_="text", value="\n\t", timestamp=2.0),
    ])
    result = _parse_monologues([monologue])
    assert result == []


def test_non_text_elements_ignored_for_start_timestamp():
    """Non-'text' elements are excluded when choosing the start timestamp."""
    monologue = _mono(speaker=0, elements=[
        _elem(type_="punct", value=".", timestamp=1.0),   # punct — ignored for start_ts
        _elem(type_="text", value="Hello", timestamp=7.0),  # first text element
    ])
    result = _parse_monologues([monologue])
    assert len(result) == 1
    # Start timestamp comes from the first text element (7s), not the punct.
    assert result[0]["timestamp"] == "00:00:07"
    # Text is joined from ALL elements (punct value "." is included).
    assert "Hello" in result[0]["text"]


def test_multiple_monologues_ordered():
    """Multiple monologues produce an ordered segment list."""
    m1 = _mono(speaker=0, elements=[_elem(type_="text", value="First turn.", timestamp=1.0)])
    m2 = _mono(speaker=1, elements=[_elem(type_="text", value="Second turn.", timestamp=10.0)])
    result = _parse_monologues([m1, m2])
    assert len(result) == 2
    assert result[0]["speaker"] == 0
    assert result[0]["text"] == "First turn."
    assert result[0]["timestamp"] == "00:00:01"
    assert result[1]["speaker"] == 1
    assert result[1]["text"] == "Second turn."
    assert result[1]["timestamp"] == "00:00:10"


def test_mixed_valid_and_skipped_monologues():
    """A mix of valid and skip-worthy monologues → only valid ones in output."""
    valid = _mono(speaker=0, elements=[_elem(type_="text", value="Hi", timestamp=5.0)])
    no_ts = _mono(speaker=1, elements=[_elem(type_="text", value="Hmm", timestamp=None)])
    empty = _mono(speaker=2, elements=[_elem(type_="text", value=" ", timestamp=3.0)])
    result = _parse_monologues([valid, no_ts, empty])
    assert len(result) == 1
    assert result[0]["speaker"] == 0
