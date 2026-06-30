"""
Unit tests for the MCP server tools + API-key auth helper (mcp_server.py).

The live MCP transport/connector still needs verification on a real deploy, but
the tool *logic* and the header-based auth are exercised here by faking the
request context and patching the reused REST handlers.
"""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_server
from mcp_server import (
    _auth,
    analyze_calls,
    resolve_upload_targets,
    search_reviews,
    tag_review,
)

BDS = {"user_id": "u1", "role": "bds_rep", "firm_id": None, "name": "Coach"}
FA = {"user_id": "u2", "role": "financial_advisor", "firm_id": "f1", "name": "Advisor"}


def _access(token):
    """Fake AccessToken (the SDK validates it before the tool runs)."""
    return types.SimpleNamespace(token=token)


def _review(rid, advisor="John", firm="Acme", outcome=None, template="Disco", score=6.0, tags=None, status="complete"):
    return {
        "id": rid,
        "status": status,
        "overall_score": score,
        "overall_max_score": 10.0,
        "metadata": {
            "advisor_name": advisor, "firm": firm, "prospect_name": "P",
            "call_outcome": outcome, "template_name": template,
            "tags": [{"id": t, "name": t} for t in (tags or [])],
        },
    }


# ── _auth (maps the SDK-validated bearer token → user context) ──────────────────


def test_auth_maps_token_to_context():
    with patch("mcp_server.get_access_token", lambda: _access("cr_at_x")), \
         patch.object(mcp_server.oauth_provider, "resolve_token_user_id", AsyncMock(return_value="u1")), \
         patch("mcp_server._user_context_from_profile", AsyncMock(return_value=BDS)):
        user = asyncio.run(_auth(None))
    assert user == BDS


def test_auth_no_token_raises():
    with patch("mcp_server.get_access_token", lambda: None):
        with pytest.raises(RuntimeError, match="Not authenticated"):
            asyncio.run(_auth(None))


def test_auth_unresolvable_token_raises():
    with patch("mcp_server.get_access_token", lambda: _access("cr_at_x")), \
         patch.object(mcp_server.oauth_provider, "resolve_token_user_id", AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError, match="resolve the authenticated user"):
            asyncio.run(_auth(None))


# ── search_reviews ─────────────────────────────────────────────────────────────


def test_search_reviews_filters_by_advisor_and_firm():
    page = {"items": [
        _review("r1", advisor="John Advisor", firm="Acme Wealth"),
        _review("r2", advisor="Jane Other", firm="Acme Wealth"),
        _review("r3", advisor="John Advisor", firm="Beta Capital"),
    ], "next_cursor": None}
    with patch("mcp_server._auth", AsyncMock(return_value=BDS)), \
         patch("mcp_server.get_reviews", AsyncMock(return_value=page)):
        out = asyncio.run(search_reviews(ctx=None, advisor="john", firm="acme"))
    assert out["count"] == 1
    assert out["reviews"][0]["id"] == "r1"


# ── tag_review role gate ───────────────────────────────────────────────────────


def test_tag_review_rejects_fa():
    with patch("mcp_server._auth", AsyncMock(return_value=FA)):
        with pytest.raises(RuntimeError, match="403"):
            asyncio.run(tag_review("r1", ["Objection"], ctx=None))


def test_tag_review_merges_and_assigns():
    created = {"objection": {"id": "objection", "name": "Objection"}}
    with patch("mcp_server._auth", AsyncMock(return_value=BDS)), \
         patch("mcp_server._create_tag", AsyncMock(side_effect=lambda n: created.get(n.lower(), {"id": n.lower(), "name": n}))), \
         patch("mcp_server.get_review_by_id", AsyncMock(return_value={"tag_ids": ["existing"], "metadata": {"tags": []}})), \
         patch("mcp_server.update_review_tags_by_id", AsyncMock(return_value={"metadata": {"tags": [{"name": "Objection"}, {"name": "existing"}]}})) as upd:
        out = asyncio.run(tag_review("r1", ["Objection"], ctx=None, replace=False))
    # merged: the new tag + the pre-existing one
    sent_ids = upd.await_args.args[1].tag_ids
    assert "objection" in sent_ids and "existing" in sent_ids
    assert "Objection" in out["tags"]


# ── analyze_calls ──────────────────────────────────────────────────────────────


def test_analyze_calls_with_explicit_ids():
    with patch("mcp_server._auth", AsyncMock(return_value=BDS)), \
         patch("mcp_server.chat_over_history", AsyncMock(return_value={"answer": "Lowest on Discovery."})):
        out = asyncio.run(analyze_calls("where low?", ctx=None, review_ids=["r1", "r2"]))
    assert out["analyzed_count"] == 2
    assert "Discovery" in out["answer"]


def test_analyze_calls_no_matches():
    with patch("mcp_server._auth", AsyncMock(return_value=BDS)), \
         patch("mcp_server.get_reviews", AsyncMock(return_value={"items": [], "next_cursor": None})):
        out = asyncio.run(analyze_calls("q", ctx=None, advisor="nobody"))
    assert out["analyzed_count"] == 0


# ── resolve_upload_targets ─────────────────────────────────────────────────────


def test_resolve_upload_targets_happy_path():
    with patch("mcp_server._auth", AsyncMock(return_value=BDS)), \
         patch("mcp_server._list_firms", AsyncMock(return_value=[{"id": "f1", "name": "Acme Wealth"}])), \
         patch("mcp_server.get_firm_users", AsyncMock(return_value=[{"id": "a1", "name": "John Advisor"}])), \
         patch("mcp_server._list_templates", AsyncMock(return_value=[{"id": "t1", "name": "Discovery"}])), \
         patch("mcp_server.get_profile", AsyncMock(return_value={"default_template_id": "t1"})):
        out = asyncio.run(resolve_upload_targets("Acme", "John", ctx=None))
    assert out == {"firm_id": "f1", "advisor_user_id": "a1", "template_id": "t1"}


def test_resolve_upload_targets_ambiguous_firm():
    with patch("mcp_server._auth", AsyncMock(return_value=BDS)), \
         patch("mcp_server._list_firms", AsyncMock(return_value=[{"id": "f1", "name": "Acme Wealth"}, {"id": "f2", "name": "Acme Capital"}])):
        with pytest.raises(RuntimeError, match="ambiguous"):
            asyncio.run(resolve_upload_targets("Acme", "John", ctx=None))
