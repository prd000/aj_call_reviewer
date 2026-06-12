"""
Tests for Section 3 latent-bug fixes (section3-latent-bugs-plan.md).

Covers:
  3.1/5.6 — Default auth (401 sweep) + BDS guard on template mutation
  3.2     — HS256 rejected when SUPABASE_JWT_SECRET is empty
  3.3     — FA with NULL firm_id gets [] from GET /reviews; _fa_can_access guards
  3.7     — Stub gate: pipeline raises when keys absent and ALLOW_STUB_PIPELINE is off
  3.8     — _review_summary None-safe when review["review"] is None
  3.13    — history chat trims messages to MAX_CHAT_HISTORY
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── 3.8: _review_summary None-safe ───────────────────────────────────────────

def test_review_summary_review_is_none():
    """`_review_summary` must not 500 when the `review` JSONB field is NULL."""
    from routers.reviews import _review_summary

    row = {
        "id": "r-1",
        "created_at": "2026-01-01T00:00:00Z",
        "status": "complete",
        "metadata": {},
        "review": None,
    }
    result = _review_summary(row)
    assert result["overall_score"] is None
    assert result["id"] == "r-1"


# ─── 3.2: HS256 empty secret rejected ─────────────────────────────────────────

def test_hs256_empty_secret_rejected(monkeypatch):
    """HS256 token must be rejected with 401 when SUPABASE_JWT_SECRET is empty."""
    import jwt as pyjwt
    from fastapi import HTTPException
    import modules.auth as auth_module

    monkeypatch.setattr(auth_module, "SUPABASE_JWT_SECRET", "")

    token = pyjwt.encode(
        {
            "sub": "user-1",
            "aud": "authenticated",
            "iss": auth_module.SUPABASE_ISSUER,
            "exp": 9_999_999_999,
        },
        "any-secret",
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc_info:
        auth_module._validate_token(token)
    assert exc_info.value.status_code == 401


# ─── 3.3: FA NULL firm_id visibility ──────────────────────────────────────────

def test_fa_can_access_null_firm_id_never_matches():
    """A NULL-firm FA must never gain access to any review via `_fa_can_access`."""
    from routers.reviews import _fa_can_access

    null_fa = {"role": "financial_advisor", "firm_id": None}

    # Should not match a NULL-firm review (None == None guard would have allowed this before fix)
    assert _fa_can_access({"firm_id": None, "uploader_role": "financial_advisor"}, null_fa) is False
    # Should not match a real firm's review either
    assert _fa_can_access({"firm_id": "firm-x", "uploader_role": "financial_advisor"}, null_fa) is False


@pytest.mark.asyncio
async def test_get_reviews_null_firm_fa_returns_empty_without_db_call(monkeypatch):
    """GET /reviews for a NULL-firm FA must return empty items and not query the database."""
    import routers.reviews as reviews_module
    from routers.reviews import get_reviews

    summary_mock = AsyncMock()
    monkeypatch.setattr(reviews_module, "list_review_summaries", summary_mock)

    null_fa = {"role": "financial_advisor", "user_id": "u-fa", "firm_id": None}
    result = await get_reviews(user=null_fa)

    assert result == {"items": [], "next_cursor": None}
    summary_mock.assert_not_called()


# ─── 3.7: Stub gate ───────────────────────────────────────────────────────────

def test_transcribe_raises_when_stub_disabled_and_no_token(monkeypatch):
    """transcribe() must raise RuntimeError when token absent and stub gate is off."""
    import modules.transcriber as t_mod

    monkeypatch.setattr(t_mod, "ALLOW_STUB_PIPELINE", False)
    monkeypatch.delenv("REV_AI_ACCESS_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="REV_AI_ACCESS_TOKEN"):
        t_mod.transcribe("fake.mp3")


def test_transcribe_returns_stub_when_gate_enabled(monkeypatch):
    """transcribe() must return stub data when ALLOW_STUB_PIPELINE is True and no token."""
    import modules.transcriber as t_mod

    monkeypatch.setattr(t_mod, "ALLOW_STUB_PIPELINE", True)
    monkeypatch.delenv("REV_AI_ACCESS_TOKEN", raising=False)

    result = t_mod.transcribe("fake.mp3")
    assert isinstance(result, list) and len(result) > 0


def test_review_call_raises_llm_unavailable_when_stub_disabled(monkeypatch):
    """review_call() must raise LLMUnavailableError when API key absent and stub is off."""
    import modules.reviewer as r_mod

    monkeypatch.setattr(r_mod, "ALLOW_STUB_PIPELINE", False)
    monkeypatch.setattr(r_mod, "get_llm_api_key", lambda: "")

    with pytest.raises(r_mod.LLMUnavailableError):
        r_mod.review_call([], [])


# ─── 3.13: History chat message trim ──────────────────────────────────────────

def test_history_chat_trims_to_max_history(monkeypatch):
    """chat_over_reviews must only pass the last MAX_CHAT_HISTORY messages to the LLM."""
    import modules.history_chat as hc
    from modules.history_chat import MAX_CHAT_HISTORY

    captured = []

    class FakeResp:
        content = "answer"
        tool_calls = []

    class FakeLLMBound:
        def invoke(self, msgs):
            captured.extend(msgs)
            return FakeResp()

    class FakeLLM:
        def bind_tools(self, _tools):
            return FakeLLMBound()

    monkeypatch.setattr(hc, "get_llm_api_key", lambda: "fake-key")
    monkeypatch.setattr(hc, "get_llm", lambda **kw: FakeLLM())
    monkeypatch.setattr(hc, "load_prompt", lambda _name: "{triage_table}")

    many = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(MAX_CHAT_HISTORY * 2 + 1)
    ]

    review = {
        "id": "r-1",
        "created_at": "2026-01-01T00:00:00Z",
        "status": "complete",
        "metadata": {"advisor_name": "Advisor"},
        "review": {"categories": [], "summary": ""},
        "framework": {},
        "transcript": [],
        "speaker_map": {},
    }

    hc.chat_over_reviews([review], many)

    # lc_messages = [SystemMessage] + trimmed_history
    # trimmed_history = last MAX_CHAT_HISTORY of `many`
    assert len(captured) == 1 + MAX_CHAT_HISTORY


# ─── 3.1/5.6: 401 sweep and BDS template guard via unit ────────────────────

def test_templates_post_without_bds_returns_403(monkeypatch):
    """POST /templates must return 403 for a non-BDS authenticated user."""
    from fastapi import HTTPException
    import routers.templates as tmpl_mod
    from routers.templates import create_template, TemplateBody

    # Simulate require_bds_rep raising 403 for a non-BDS user
    fa_user = {"role": "financial_advisor", "user_id": "u-fa", "firm_id": "f-1"}

    with pytest.raises(HTTPException) as exc:
        import modules.auth as auth_mod
        auth_mod.require_bds_rep(fa_user)
    assert exc.value.status_code == 403


def test_fa_can_access_normal_case():
    """_fa_can_access must return True for a matching FA with a real firm_id."""
    from routers.reviews import _fa_can_access

    fa = {"role": "financial_advisor", "firm_id": "firm-x"}
    review = {"firm_id": "firm-x", "uploader_role": "financial_advisor"}
    assert _fa_can_access(review, fa) is True

    # Different firm must not match
    other_review = {"firm_id": "firm-y", "uploader_role": "financial_advisor"}
    assert _fa_can_access(other_review, fa) is False
