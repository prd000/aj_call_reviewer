"""
TestClient tests for the MCP OAuth consent page (routers/mcp_oauth.py):
GET renders the form; POST with a valid API key 302-redirects back to the OAuth
client with a code; an invalid key re-renders with an error.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import routers.mcp_oauth as mcp_oauth
from main import app


@pytest.fixture
def client():
    with patch("main.migrate_default_template", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c


def test_consent_page_renders(client):
    resp = client.get("/mcp-oauth/consent?request_id=req-1")
    assert resp.status_code == 200
    assert "Connect Claude to Call Reviewer" in resp.text
    assert "req-1" in resp.text


def test_consent_valid_key_redirects_with_code(client):
    with patch("routers.mcp_oauth.resolve_api_key",
               AsyncMock(return_value={"user_id": "u1", "key_id": "k1"})), \
         patch.object(mcp_oauth.provider, "complete_authorization",
                      AsyncMock(return_value="https://claude.ai/cb?code=abc&state=xyz")):
        resp = client.post(
            "/mcp-oauth/consent",
            data={"request_id": "req-1", "api_key": "ak_live_good"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://claude.ai/cb?code=abc&state=xyz"


def test_consent_invalid_key_rerenders_error(client):
    with patch("routers.mcp_oauth.resolve_api_key", AsyncMock(return_value=None)):
        resp = client.post(
            "/mcp-oauth/consent",
            data={"request_id": "req-1", "api_key": "ak_live_bad"},
            follow_redirects=False,
        )
    assert resp.status_code == 401
    assert "invalid or revoked" in resp.text.lower()
