"""
FA visibility enforcement tests.

Covers:
  - GET /api/reviews: FA list is scoped to own firm + FA-uploaded rows only
  - GET /api/reviews/{id}: FA cross-firm → 404; FA own-firm → 200
  - BDS-only PATCH endpoints → 403 for an FA
  - NULL-firm FA case (finding 3.3): documents whether a NULL firm_id leaks
    cross-tenant data through list_reviews
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from modules.auth import get_current_user

FA = {"user_id": "fa-1", "role": "financial_advisor", "firm_id": "firm-a", "name": "FA User"}
FA_NULL_FIRM = {"user_id": "fa-2", "role": "financial_advisor", "firm_id": None, "name": "Orphan FA"}


def _review(rid="r1", firm="firm-a", uploader="financial_advisor", status="complete"):
    return {
        "id": rid,
        "status": status,
        "firm_id": firm,
        "uploader_role": uploader,
        "transcript": [],
        "speaker_map": {},
        "framework": None,
        "review": {},
        "metadata": {"advisor_name": "Test", "firm": "Acme", "prospect_name": "Bob"},
        "created_at": "2026-01-01T00:00:00Z",
        "tag_ids": [],
    }


@pytest.fixture
def fa_client():
    app.dependency_overrides[get_current_user] = lambda: FA
    with patch("main.migrate_default_template", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fa_null_firm_client():
    app.dependency_overrides[get_current_user] = lambda: FA_NULL_FIRM
    with patch("main.migrate_default_template", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/reviews — list scoping
# ---------------------------------------------------------------------------

def test_fa_get_reviews_calls_list_reviews_with_own_firm_and_role(fa_client):
    """list_review_summaries must be called with the FA's firm_id and uploader_role filter."""
    captured = {}

    async def mock_list_summaries(**kwargs):
        captured.update(kwargs)
        return ([], None)

    with patch("routers.reviews.list_review_summaries", side_effect=mock_list_summaries):
        resp = fa_client.get("/api/reviews")

    assert resp.status_code == 200
    assert captured.get("firm_id") == "firm-a"
    assert captured.get("uploader_role") == "financial_advisor"
    assert resp.json()["items"] == []
    assert resp.json()["next_cursor"] is None


def test_fa_get_reviews_null_firm_scoped_with_none(fa_null_firm_client):
    """
    Finding 3.3 (fixed): FA with no firm_id is short-circuited at the top of
    GET /reviews before any DB call. Returns an empty items list without querying
    the database — no cross-tenant leakage possible.
    """
    summary_mock = AsyncMock()

    with patch("routers.reviews.list_review_summaries", side_effect=summary_mock):
        resp = fa_null_firm_client.get("/api/reviews")

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}
    # No DB call should be made for a NULL-firm FA
    summary_mock.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/reviews/{id} — individual review access
# ---------------------------------------------------------------------------

def test_fa_own_firm_review_returns_200(fa_client):
    with patch("routers.reviews.get_review", AsyncMock(return_value=_review())):
        resp = fa_client.get("/api/reviews/r1")
    assert resp.status_code == 200


def test_fa_cross_firm_review_returns_404(fa_client):
    cross = _review(firm="firm-other")
    with patch("routers.reviews.get_review", AsyncMock(return_value=cross)):
        resp = fa_client.get("/api/reviews/r1")
    assert resp.status_code == 404


def test_fa_bds_uploaded_review_returns_404(fa_client):
    """FA cannot see BDS-rep-uploaded reviews even from their own firm."""
    bds_upload = _review(firm="firm-a", uploader="bds_rep")
    with patch("routers.reviews.get_review", AsyncMock(return_value=bds_upload)):
        resp = fa_client.get("/api/reviews/r1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# BDS-only PATCH endpoints → 403 for FA
# ---------------------------------------------------------------------------

def test_fa_patch_major_focus_returns_403(fa_client):
    with patch("routers.reviews.get_review", AsyncMock(return_value=_review())):
        resp = fa_client.patch(
            "/api/reviews/r1/major-focus",
            json={"criterion_id": "c1"},
        )
    assert resp.status_code == 403


def test_fa_patch_tags_returns_403(fa_client):
    with patch("routers.reviews.get_review", AsyncMock(return_value=_review())):
        resp = fa_client.patch("/api/reviews/r1/tags", json={"tag_ids": []})
    assert resp.status_code == 403


def test_fa_patch_notes_returns_403(fa_client):
    with patch("routers.reviews.get_review", AsyncMock(return_value=_review())):
        resp = fa_client.patch("/api/reviews/r1/notes", json={"notes": "test"})
    assert resp.status_code == 403
