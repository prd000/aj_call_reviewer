"""
TestClient tests for:
  - POST /api/reviews/{id}/chat       (single-call chat)
  - POST /api/reviews/history-chat    (cross-call history chat)

Auth is overridden via app.dependency_overrides. LLM calls are patched.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from modules.auth import get_current_user
from modules.reviewer import LLMUnavailableError

BDS = {"user_id": "bds-1", "role": "bds_rep", "firm_id": None, "name": "Rep"}
FA = {"user_id": "fa-1", "role": "financial_advisor", "firm_id": "firm-a", "name": "FA"}


def _review(rid="r1", firm="firm-a", uploader="financial_advisor", status="complete", transcript=None):
    return {
        "id": rid,
        "status": status,
        "firm_id": firm,
        "uploader_role": uploader,
        "transcript": transcript if transcript is not None else [{"timestamp": "00:00:01", "text": "Hi", "speaker": 0}],
        "speaker_map": {},
        "framework": None,
        "review": {
            "categories": [{"name": "Opening", "score": 8, "max_score": 10, "feedback": "Good."}],
            "summary": "Summary text.",
        },
        "metadata": {},
    }


@pytest.fixture
def bds_client():
    app.dependency_overrides[get_current_user] = lambda: BDS
    with patch("main.migrate_default_template", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fa_client():
    app.dependency_overrides[get_current_user] = lambda: FA
    with patch("main.migrate_default_template", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/reviews/{id}/chat
# ---------------------------------------------------------------------------

def test_chat_happy_path_200(bds_client):
    with (
        patch("routers.reviews.get_review", AsyncMock(return_value=_review())),
        patch("routers.reviews.chat_about_transcript", return_value="Good call overall."),
    ):
        resp = bds_client.post(
            "/api/reviews/r1/chat",
            json={"messages": [{"role": "user", "content": "How did it go?"}]},
        )
    assert resp.status_code == 200
    assert resp.json()["answer"] == "Good call overall."


def test_chat_unknown_review_returns_404(bds_client):
    with patch("routers.reviews.get_review", AsyncMock(return_value=None)):
        resp = bds_client.post(
            "/api/reviews/nonexistent/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert resp.status_code == 404


def test_chat_fa_cross_firm_returns_404(fa_client):
    other_firm_review = _review(firm="firm-other")
    with patch("routers.reviews.get_review", AsyncMock(return_value=other_firm_review)):
        resp = fa_client.post(
            "/api/reviews/r1/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert resp.status_code == 404


def test_chat_no_transcript_returns_400(bds_client):
    with patch("routers.reviews.get_review", AsyncMock(return_value=_review(transcript=[]))):
        resp = bds_client.post(
            "/api/reviews/r1/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert resp.status_code == 400


def test_chat_llm_unavailable_returns_503(bds_client):
    with (
        patch("routers.reviews.get_review", AsyncMock(return_value=_review())),
        patch("routers.reviews.chat_about_transcript", side_effect=LLMUnavailableError("no key")),
    ):
        resp = bds_client.post(
            "/api/reviews/r1/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert resp.status_code == 503


def test_chat_unexpected_error_returns_502(bds_client):
    with (
        patch("routers.reviews.get_review", AsyncMock(return_value=_review())),
        patch("routers.reviews.chat_about_transcript", side_effect=RuntimeError("LLM timeout")),
    ):
        resp = bds_client.post(
            "/api/reviews/r1/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /api/reviews/history-chat
# ---------------------------------------------------------------------------

def _hc_body(review_ids, content="Any trends?"):
    return {"review_ids": review_ids, "messages": [{"role": "user", "content": content}]}


def test_history_chat_happy_path_200(bds_client):
    with (
        patch("routers.reviews.get_reviews_by_ids", AsyncMock(return_value=[_review()])),
        patch("routers.reviews.chat_over_reviews", return_value="Here are the trends."),
    ):
        resp = bds_client.post("/api/reviews/history-chat", json=_hc_body(["r1"]))
    assert resp.status_code == 200
    assert "trends" in resp.json()["answer"]


def test_history_chat_empty_scope_returns_no_calls_message(bds_client):
    """When all provided IDs resolve to nothing, return the empty-scope answer."""
    with patch("routers.reviews.get_reviews_by_ids", AsyncMock(return_value=[])):
        resp = bds_client.post("/api/reviews/history-chat", json=_hc_body(["ghost-id"]))
    assert resp.status_code == 200
    assert "No completed calls" in resp.json()["answer"]


def test_history_chat_fa_only_sees_own_firm(fa_client):
    """FA-visible review (own firm) is included; cross-firm review is dropped."""
    own = _review("own", firm="firm-a", uploader="financial_advisor")
    other = _review("other", firm="firm-b", uploader="financial_advisor")
    captured = {}

    def mock_chat(scoped_reviews, messages):
        captured["ids"] = [r["id"] for r in scoped_reviews]
        return "ok"

    with (
        patch("routers.reviews.get_reviews_by_ids", AsyncMock(return_value=[own, other])),
        patch("routers.reviews.chat_over_reviews", side_effect=mock_chat),
    ):
        resp = fa_client.post("/api/reviews/history-chat", json=_hc_body(["own", "other"]))

    assert resp.status_code == 200
    assert captured["ids"] == ["own"], "Cross-firm review should have been excluded"


def test_history_chat_drops_non_complete_reviews(bds_client):
    """Reviews with status != 'complete' are excluded from the chat scope."""
    pending = _review("p1", status="pending")
    captured = {}

    def mock_chat(scoped_reviews, messages):
        captured["count"] = len(scoped_reviews)
        return "ok"

    with (
        patch("routers.reviews.get_reviews_by_ids", AsyncMock(return_value=[pending])),
        patch("routers.reviews.chat_over_reviews", side_effect=mock_chat),
    ):
        resp = bds_client.post("/api/reviews/history-chat", json=_hc_body(["p1"]))

    # Pending review filtered out → empty scope → no call to chat_over_reviews.
    assert resp.status_code == 200
    assert "No completed calls" in resp.json()["answer"]
    assert captured.get("count") is None


def test_history_chat_llm_unavailable_returns_503(bds_client):
    with (
        patch("routers.reviews.get_reviews_by_ids", AsyncMock(return_value=[_review()])),
        patch("routers.reviews.chat_over_reviews", side_effect=LLMUnavailableError("no key")),
    ):
        resp = bds_client.post("/api/reviews/history-chat", json=_hc_body(["r1"]))
    assert resp.status_code == 503


def test_history_chat_unexpected_error_returns_502(bds_client):
    with (
        patch("routers.reviews.get_reviews_by_ids", AsyncMock(return_value=[_review()])),
        patch("routers.reviews.chat_over_reviews", side_effect=RuntimeError("boom")),
    ):
        resp = bds_client.post("/api/reviews/history-chat", json=_hc_body(["r1"]))
    assert resp.status_code == 502
