"""
Tests for POST /api/upload: role branching, validation rejections, storage
rollback, and enqueue-failure handling.

Uses TestClient + dependency override for get_current_user.
Supabase/storage/task calls are patched via routers.upload.* namespace.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from modules.auth import get_current_user

# ---------------------------------------------------------------------------
# Fake identities
# ---------------------------------------------------------------------------
BDS_USER = {"user_id": "bds-1", "role": "bds_rep", "name": "BDS Rep", "firm_id": None}
FA_USER = {"user_id": "fa-1", "role": "financial_advisor", "name": "FA User", "firm_id": "firm-a"}

FAKE_FIRM = {"id": "firm-a", "name": "Acme Wealth", "template_id": "t1"}
FAKE_ADVISOR = {"id": "a1", "name": "Test Advisor", "role": "financial_advisor", "firm_id": "firm-a"}
FAKE_TEMPLATE = {
    "id": "t1",
    "name": "Basic Template",
    "criteria": [
        {"id": "c1", "description": "Opening", "success_condition": "Did it", "max_score": 10}
    ],
}

_MP3 = ("test.mp3", b"audio-bytes", "audio/mpeg")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bds_client():
    app.dependency_overrides[get_current_user] = lambda: BDS_USER
    with patch("main.migrate_default_template", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fa_client():
    app.dependency_overrides[get_current_user] = lambda: FA_USER
    with patch("main.migrate_default_template", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Validation rejections
# ---------------------------------------------------------------------------

def test_invalid_file_type_returns_400(bds_client):
    resp = bds_client.post(
        "/api/upload",
        data={"prospect_name": "Test", "firm_id": "f1", "advisor_user_id": "a1", "template_id": "t1"},
        files={"file": ("notes.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


def test_invalid_outcome_returns_400(bds_client):
    resp = bds_client.post(
        "/api/upload",
        data={
            "prospect_name": "Test",
            "firm_id": "f1",
            "advisor_user_id": "a1",
            "template_id": "t1",
            "call_outcome": "NotARealOutcome",
        },
        files={"file": _MP3},
    )
    assert resp.status_code == 400
    assert "Invalid call outcome" in resp.json()["detail"]


def test_bds_missing_firm_id_returns_400(bds_client):
    resp = bds_client.post(
        "/api/upload",
        data={"prospect_name": "Test", "advisor_user_id": "a1", "template_id": "t1"},
        files={"file": _MP3},
    )
    assert resp.status_code == 400
    assert "firm_id" in resp.json()["detail"]


def test_bds_missing_advisor_user_id_returns_400(bds_client):
    resp = bds_client.post(
        "/api/upload",
        data={"prospect_name": "Test", "firm_id": "f1", "template_id": "t1"},
        files={"file": _MP3},
    )
    assert resp.status_code == 400
    assert "advisor_user_id" in resp.json()["detail"]


def test_bds_missing_template_id_returns_400(bds_client):
    resp = bds_client.post(
        "/api/upload",
        data={"prospect_name": "Test", "firm_id": "f1", "advisor_user_id": "a1"},
        files={"file": _MP3},
    )
    assert resp.status_code == 400
    assert "template_id" in resp.json()["detail"]


def test_template_id_null_string_rejected_before_task(bds_client):
    """
    template_id='null' (the string) passes the 'not template_id' guard but is
    rejected when get_template returns None — the task must never be enqueued.
    """
    task_mock = MagicMock()
    with (
        patch("routers.upload.get_firm", AsyncMock(return_value=FAKE_FIRM)),
        patch("routers.upload.get_profile", AsyncMock(return_value=FAKE_ADVISOR)),
        patch("routers.upload.get_template", AsyncMock(return_value=None)),
        patch("routers.upload.process_review_task", task_mock),
    ):
        resp = bds_client.post(
            "/api/upload",
            data={"prospect_name": "Test", "firm_id": "firm-a", "advisor_user_id": "a1", "template_id": "null"},
            files={"file": _MP3},
        )
    assert resp.status_code == 400
    assert "template" in resp.json()["detail"].lower()
    task_mock.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_bds_happy_path_enqueues_task(bds_client):
    task_mock = MagicMock()
    task_mock.delay.return_value = MagicMock(id="task-xyz")
    with (
        patch("routers.upload.get_firm", AsyncMock(return_value=FAKE_FIRM)),
        patch("routers.upload.get_profile", AsyncMock(return_value=FAKE_ADVISOR)),
        patch("routers.upload.get_template", AsyncMock(return_value=FAKE_TEMPLATE)),
        patch("routers.upload.upload_recording_to_storage", AsyncMock(return_value="path/rec.mp3")),
        patch("routers.upload.save_review", AsyncMock()),
        patch("routers.upload.update_review_status", AsyncMock()),
        patch("routers.upload.process_review_task", task_mock),
    ):
        resp = bds_client.post(
            "/api/upload",
            data={"prospect_name": "Bob", "firm_id": "firm-a", "advisor_user_id": "a1", "template_id": "t1"},
            files={"file": _MP3},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body
    assert body["status"] == "pending"
    task_mock.delay.assert_called_once()


def test_fa_happy_path_auto_fills_firm(fa_client):
    task_mock = MagicMock()
    task_mock.delay.return_value = MagicMock(id="task-abc")
    with (
        patch("routers.upload.get_firm", AsyncMock(return_value=FAKE_FIRM)),
        patch("routers.upload.get_template", AsyncMock(return_value=FAKE_TEMPLATE)),
        patch("routers.upload.upload_recording_to_storage", AsyncMock(return_value="path/rec.mp3")),
        patch("routers.upload.save_review", AsyncMock()),
        patch("routers.upload.update_review_status", AsyncMock()),
        patch("routers.upload.process_review_task", task_mock),
    ):
        resp = fa_client.post(
            "/api/upload",
            data={"prospect_name": "Alice"},
            files={"file": _MP3},
        )
    assert resp.status_code == 200
    # FA path never requires firm_id / advisor_user_id in form data
    task_mock.delay.assert_called_once()


# ---------------------------------------------------------------------------
# Storage and DB failure paths
# ---------------------------------------------------------------------------

def test_storage_upload_failure_returns_500(bds_client):
    """When upload_recording_to_storage raises, return 500; no orphan delete."""
    delete_mock = AsyncMock()
    with (
        patch("routers.upload.get_firm", AsyncMock(return_value=FAKE_FIRM)),
        patch("routers.upload.get_profile", AsyncMock(return_value=FAKE_ADVISOR)),
        patch("routers.upload.get_template", AsyncMock(return_value=FAKE_TEMPLATE)),
        patch("routers.upload.upload_recording_to_storage", AsyncMock(side_effect=RuntimeError("S3 down"))),
        patch("routers.upload.delete_recording_from_storage", delete_mock),
    ):
        resp = bds_client.post(
            "/api/upload",
            data={"prospect_name": "Test", "firm_id": "firm-a", "advisor_user_id": "a1", "template_id": "t1"},
            files={"file": _MP3},
        )
    assert resp.status_code == 500
    delete_mock.assert_not_called()


def test_save_review_failure_deletes_orphan_recording(bds_client):
    """When save_review raises after a successful upload, the recording is deleted."""
    delete_mock = AsyncMock()
    with (
        patch("routers.upload.get_firm", AsyncMock(return_value=FAKE_FIRM)),
        patch("routers.upload.get_profile", AsyncMock(return_value=FAKE_ADVISOR)),
        patch("routers.upload.get_template", AsyncMock(return_value=FAKE_TEMPLATE)),
        patch("routers.upload.upload_recording_to_storage", AsyncMock(return_value="path/rec.mp3")),
        patch("routers.upload.save_review", AsyncMock(side_effect=RuntimeError("DB error"))),
        patch("routers.upload.delete_recording_from_storage", delete_mock),
    ):
        resp = bds_client.post(
            "/api/upload",
            data={"prospect_name": "Test", "firm_id": "firm-a", "advisor_user_id": "a1", "template_id": "t1"},
            files={"file": _MP3},
        )
    assert resp.status_code == 500
    delete_mock.assert_awaited_once_with("path/rec.mp3")


def test_enqueue_failure_marks_review_failed(bds_client):
    """When process_review_task.delay raises, update_review_status is called with 'failed'."""
    status_mock = AsyncMock()
    task_mock = MagicMock()
    task_mock.delay.side_effect = RuntimeError("Redis down")
    with (
        patch("routers.upload.get_firm", AsyncMock(return_value=FAKE_FIRM)),
        patch("routers.upload.get_profile", AsyncMock(return_value=FAKE_ADVISOR)),
        patch("routers.upload.get_template", AsyncMock(return_value=FAKE_TEMPLATE)),
        patch("routers.upload.upload_recording_to_storage", AsyncMock(return_value="path/rec.mp3")),
        patch("routers.upload.save_review", AsyncMock()),
        patch("routers.upload.update_review_status", status_mock),
        patch("routers.upload.process_review_task", task_mock),
    ):
        resp = bds_client.post(
            "/api/upload",
            data={"prospect_name": "Test", "firm_id": "firm-a", "advisor_user_id": "a1", "template_id": "t1"},
            files={"file": _MP3},
        )
    # The router doesn't raise on enqueue failure; it marks the review failed and returns.
    assert resp.status_code == 200
    # Verify the second update_review_status call used "failed"
    failed_calls = [
        call for call in status_mock.await_args_list
        if call.args[1] == "failed"
    ]
    assert failed_calls, "update_review_status was never called with 'failed'"
