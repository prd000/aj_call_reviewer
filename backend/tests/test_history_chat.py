"""
Unit tests for modules/history_chat.py: the agentic loop and triage table builder.

Uses a scripted fake LLM — no real API calls. Tests cover the happy path,
MAX_ITERATIONS cap, MAX_TRANSCRIPT_READS cap, invalid tool handles, and
_build_triage_table truncation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.history_chat import (
    MAX_ITERATIONS,
    MAX_TRANSCRIPT_READS,
    TRIAGE_SUMMARY_BUDGET_CHARS,
    _build_triage_table,
    chat_over_reviews,
)


# ---------------------------------------------------------------------------
# Fake LLM infrastructure
# ---------------------------------------------------------------------------

class FakeAIMessage:
    """Mimics a LangChain AIMessage enough for the loop logic."""
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeBoundLLM:
    def __init__(self, responses):
        self._it = iter(responses)

    def invoke(self, messages):
        try:
            return next(self._it)
        except StopIteration:
            return FakeAIMessage(content="Default fallback")


class FakeLLM:
    """Fake LLM: bind_tools → returns scripted loop responses; invoke → final answer."""
    def __init__(self, loop_responses, final="Forced final answer"):
        self._loop = loop_responses
        self._final = FakeAIMessage(content=final)

    def bind_tools(self, tools):
        return FakeBoundLLM(iter(self._loop))

    def invoke(self, messages):
        return self._final


def _tool_call(name="get_feedback", call="C1", call_id="tc1"):
    return FakeAIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"call": call}, "id": call_id}],
    )


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

def _make_review(
    review_id="r1",
    advisor="Alice",
    prospect="Bob",
    score=8,
    summary="Strong opening.",
    firm_id="firm-a",
):
    return {
        "id": review_id,
        "created_at": "2026-01-01T00:00:00Z",
        "status": "complete",
        "firm_id": firm_id,
        "uploader_role": "financial_advisor",
        "metadata": {"advisor_name": advisor, "prospect_name": prospect, "firm": "ACME"},
        "framework": {"template_name": "Basic"},
        "review": {
            "categories": [{"name": "Opening", "score": score, "max_score": 10, "feedback": "Good."}],
            "summary": summary,
        },
        "transcript": [{"timestamp": "00:00:01", "text": "Hi Bob.", "speaker": 0}],
        "speaker_map": {"0": "Alice", "1": "Bob"},
    }


_MESSAGES = [{"role": "user", "content": "How did Alice do?"}]


# ---------------------------------------------------------------------------
# chat_over_reviews — loop behavior
# ---------------------------------------------------------------------------

def test_happy_path_tool_call_then_final_answer(monkeypatch):
    """One get_feedback tool call followed by a final answer."""
    responses = [
        _tool_call("get_feedback", "C1"),
        FakeAIMessage(content="Alice performed well overall."),
    ]
    fake_llm = FakeLLM(responses)
    monkeypatch.setattr("modules.history_chat.get_llm", lambda **kw: fake_llm)
    monkeypatch.setattr("modules.history_chat.get_llm_api_key", lambda: "fake-key")

    result = chat_over_reviews([_make_review()], _MESSAGES)
    assert result == "Alice performed well overall."


def test_max_iterations_cap_forces_final_answer(monkeypatch):
    """Tool calls every iteration → hits MAX_ITERATIONS → forced plain-text answer."""
    tool_responses = [_tool_call("get_feedback", "C1")] * MAX_ITERATIONS
    fake_llm = FakeLLM(tool_responses, final="Best I can do.")
    monkeypatch.setattr("modules.history_chat.get_llm", lambda **kw: fake_llm)
    monkeypatch.setattr("modules.history_chat.get_llm_api_key", lambda: "fake-key")

    result = chat_over_reviews([_make_review()], _MESSAGES)
    assert result == "Best I can do."


def test_invalid_tool_handle_returns_error_message(monkeypatch):
    """A tool call with a non-existent handle returns an error string, not a crash."""
    responses = [
        _tool_call("get_feedback", "C99"),  # C99 doesn't exist
        FakeAIMessage(content="Sorry, I couldn't find that call."),
    ]
    fake_llm = FakeLLM(responses)
    monkeypatch.setattr("modules.history_chat.get_llm", lambda **kw: fake_llm)
    monkeypatch.setattr("modules.history_chat.get_llm_api_key", lambda: "fake-key")

    result = chat_over_reviews([_make_review()], _MESSAGES)
    assert "Sorry" in result or "couldn't" in result


def test_max_transcript_reads_cap(monkeypatch):
    """After MAX_TRANSCRIPT_READS read_transcript calls, subsequent reads are blocked."""
    # One tool call per iteration, all requesting transcript reads.
    # After the cap, the loop still continues (just gets error messages as results).
    # At MAX_ITERATIONS the forced final answer fires.
    too_many = MAX_TRANSCRIPT_READS + 2
    responses = [_tool_call("read_transcript", "C1", call_id=f"tc{i}") for i in range(too_many)]
    fake_llm = FakeLLM(responses, final="Ran out of transcript reads.")
    monkeypatch.setattr("modules.history_chat.get_llm", lambda **kw: fake_llm)
    monkeypatch.setattr("modules.history_chat.get_llm_api_key", lambda: "fake-key")

    result = chat_over_reviews([_make_review()], _MESSAGES)
    # Should not crash and should return the forced final answer.
    assert result == "Ran out of transcript reads."


def test_no_api_key_raises_llm_unavailable(monkeypatch):
    from modules.reviewer import LLMUnavailableError
    monkeypatch.setattr("modules.history_chat.get_llm_api_key", lambda: "")
    with pytest.raises(LLMUnavailableError):
        chat_over_reviews([_make_review()], _MESSAGES)


# ---------------------------------------------------------------------------
# _build_triage_table
# ---------------------------------------------------------------------------

def test_build_triage_table_includes_summary_within_budget():
    review = _make_review(summary="Short summary.")
    from modules.history_chat import _build_handle_map
    handle_map = _build_handle_map([review])
    table = _build_triage_table(handle_map)
    assert "Short summary." in table


def test_build_triage_table_omits_summary_over_budget(monkeypatch):
    """When the cumulative summary size exceeds the budget, older rows get scores-only."""
    # Patch the budget to a small value so we can trigger truncation with few reviews.
    monkeypatch.setattr("modules.history_chat.TRIAGE_SUMMARY_BUDGET_CHARS", 10)
    long_summary = "X" * 50  # Exceeds the patched budget.
    review = _make_review(summary=long_summary)
    from modules.history_chat import _build_handle_map
    handle_map = _build_handle_map([review])
    table = _build_triage_table(handle_map)
    # Summary was omitted; scores-only placeholder appears.
    assert "omitted" in table
    assert long_summary not in table


def test_build_triage_table_header_when_some_omitted(monkeypatch):
    """When at least one summary is omitted, a header note appears."""
    monkeypatch.setattr("modules.history_chat.TRIAGE_SUMMARY_BUDGET_CHARS", 5)
    r1 = _make_review("r1", summary="A" * 20)
    r2 = _make_review("r2", summary="B" * 20)
    from modules.history_chat import _build_handle_map
    handle_map = _build_handle_map([r1, r2])
    table = _build_triage_table(handle_map)
    assert "Showing summaries" in table or "omitted" in table


def test_build_triage_table_empty_reviews():
    from modules.history_chat import _build_handle_map
    handle_map = _build_handle_map([])
    table = _build_triage_table(handle_map)
    assert table == ""
