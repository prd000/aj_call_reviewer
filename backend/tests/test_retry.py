"""Tests for the POST /reviews/{id}/retry endpoint handler (retry feature).

Calls the handler directly with an explicit `user` dict (bypassing Depends) and
monkeypatches its module-level dependencies — get_review, update_review_status,
and the Celery task — in the routers.reviews namespace.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import routers.reviews as reviews_module
from routers.reviews import retry_review_by_id


BDS = {"role": "bds_rep", "user_id": "u-bds", "firm_id": "firm-x"}
FA = {"role": "financial_advisor", "user_id": "u-fa", "firm_id": "firm-a"}


def _review(**over):
    r = {
        "id": "rev-1",
        "status": "failed",
        "firm_id": "firm-a",
        "uploader_role": "financial_advisor",
        "template_id": "tpl-1",
        "framework": None,
        "error_message": "boom",
        "storage_path": "rev-1/call.wav",
    }
    r.update(over)
    return r


def _wire(monkeypatch, review, *, delay_id="task-123"):
    monkeypatch.setattr(reviews_module, "get_review", AsyncMock(return_value=review))
    status_mock = AsyncMock()
    monkeypatch.setattr(reviews_module, "update_review_status", status_mock)
    task_mock = MagicMock()
    task_mock.delay.return_value = MagicMock(id=delay_id)
    monkeypatch.setattr(reviews_module, "process_review_task", task_mock)
    return status_mock, task_mock


def test_retry_failed_review_enqueues_and_resets(monkeypatch):
    review = _review(status="failed", template_id="tpl-1")
    status_mock, task_mock = _wire(monkeypatch, review)

    result = asyncio.run(retry_review_by_id("rev-1", user=BDS))

    task_mock.delay.assert_called_once_with("rev-1", "tpl-1")
    # Fix 3.9: update_review_status is now called twice.
    # First: write "pending" + clear_error BEFORE enqueueing.
    # Second: write celery_task_id AFTER enqueueing (guard_pending=True).
    assert status_mock.await_count == 2
    first_args, first_kwargs = status_mock.await_args_list[0]
    assert first_args[0] == "rev-1" and first_args[1] == "pending"
    assert first_kwargs.get("clear_error_message") is True
    assert "celery_task_id" not in first_kwargs
    second_args, second_kwargs = status_mock.await_args_list[1]
    assert second_args[0] == "rev-1" and second_args[1] == "pending"
    assert second_kwargs.get("celery_task_id") == "task-123"
    assert second_kwargs.get("guard_pending") is True
    assert result is review  # returns the re-fetched review


def test_retry_non_failed_returns_400(monkeypatch):
    _wire(monkeypatch, _review(status="complete"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(retry_review_by_id("rev-1", user=BDS))
    assert exc.value.status_code == 400


def test_retry_without_template_returns_400(monkeypatch):
    _wire(monkeypatch, _review(status="failed", template_id=None, framework=None))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(retry_review_by_id("rev-1", user=BDS))
    assert exc.value.status_code == 400


def test_retry_falls_back_to_framework_template(monkeypatch):
    review = _review(status="failed", template_id=None, framework={"template_id": "tpl-fw"})
    status_mock, task_mock = _wire(monkeypatch, review)
    asyncio.run(retry_review_by_id("rev-1", user=BDS))
    task_mock.delay.assert_called_once_with("rev-1", "tpl-fw")


def test_retry_fa_cannot_access_other_firm_returns_404(monkeypatch):
    _wire(monkeypatch, _review(status="failed", firm_id="firm-other"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(retry_review_by_id("rev-1", user=FA))
    assert exc.value.status_code == 404


def test_retry_not_found_returns_404(monkeypatch):
    monkeypatch.setattr(reviews_module, "get_review", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(retry_review_by_id("missing", user=BDS))
    assert exc.value.status_code == 404


def test_retry_enqueue_failure_returns_503(monkeypatch):
    review = _review(status="failed", template_id="tpl-1")
    monkeypatch.setattr(reviews_module, "get_review", AsyncMock(return_value=review))
    monkeypatch.setattr(reviews_module, "update_review_status", AsyncMock())
    task_mock = MagicMock()
    task_mock.delay.side_effect = RuntimeError("redis down")
    monkeypatch.setattr(reviews_module, "process_review_task", task_mock)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(retry_review_by_id("rev-1", user=BDS))
    assert exc.value.status_code == 503
