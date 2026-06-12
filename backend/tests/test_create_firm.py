"""
Tests for POST /firms: BDS rep auto-assignment on firm creation.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from modules.auth import get_current_user, require_bds_rep

FAKE_USER = {"user_id": "bds-rep-uuid-123", "role": "bds_rep", "name": "Test Rep"}


def _override_bds_rep():
    return FAKE_USER


@pytest.fixture
def client():
    # Override both the router-level baseline dep and the endpoint-level BDS dep.
    app.dependency_overrides[get_current_user] = _override_bds_rep
    app.dependency_overrides[require_bds_rep] = _override_bds_rep
    with patch("main.migrate_default_template", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


def test_create_firm_defaults_bds_rep_to_creator(client):
    """POST /firms with no bds_rep_id stores the caller's user_id."""
    saved = {}

    async def mock_save_firm(data):
        saved.update(data)
        return {"id": "new-firm-id", **data}

    with patch("routers.management.save_firm", side_effect=mock_save_firm):
        response = client.post("/api/firms", json={"name": "Acme Wealth"})

    assert response.status_code == 200
    assert saved["bds_rep_id"] == FAKE_USER["user_id"]


def test_create_firm_explicit_bds_rep_not_overwritten(client):
    """POST /firms with an explicit bds_rep_id stores that value verbatim."""
    explicit_rep_id = "other-bds-rep-uuid-456"
    saved = {}

    async def mock_save_firm(data):
        saved.update(data)
        return {"id": "new-firm-id", **data}

    with patch("routers.management.save_firm", side_effect=mock_save_firm):
        response = client.post(
            "/api/firms",
            json={"name": "Acme Wealth", "bds_rep_id": explicit_rep_id},
        )

    assert response.status_code == 200
    assert saved["bds_rep_id"] == explicit_rep_id
