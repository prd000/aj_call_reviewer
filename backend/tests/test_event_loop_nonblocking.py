"""
Behavioral test: async endpoints must not block the event loop during LLM calls.

Pre-fix: chat_about_transcript called synchronously on the event loop → GET /health
blocks for the full LLM duration (~1s in this test).

Post-fix: wrapped in run_in_threadpool → /health returns immediately while the
slow "LLM" sleeps in a worker thread.
"""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from httpx import ASGITransport

from main import app
from modules.auth import get_current_user

FAKE_USER = {
    "user_id": "user-uuid-test",
    "role": "bds_rep",
    "name": "Test Rep",
    "firm_id": None,
}

FAKE_REVIEW = {
    "id": "review-uuid-test",
    "status": "complete",
    "transcript": [{"timestamp": "00:00:01", "text": "Hello", "speaker": 0}],
    "speaker_map": {},
    "framework": None,
    "review": None,
    "metadata": {},
}


def _slow_chat(*args, **kwargs):
    """Simulates a blocking LLM call taking 1 second."""
    time.sleep(1.0)
    return "test answer"


@pytest.mark.asyncio
async def test_health_not_blocked_during_chat():
    """
    Fire POST /reviews/{id}/chat and GET /health concurrently.
    /health must complete well before the slow 'LLM' finishes (< 0.3s),
    proving the event loop stays free while the blocking work runs in a thread.
    """
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER

    try:
        with (
            patch("routers.reviews.get_review", new_callable=AsyncMock, return_value=FAKE_REVIEW),
            patch("routers.reviews.chat_about_transcript", side_effect=_slow_chat),
        ):
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

                async def do_chat():
                    return await client.post(
                        "/api/reviews/review-uuid-test/chat",
                        json={"messages": [{"role": "user", "content": "hello"}]},
                        timeout=10.0,
                    )

                async def do_health():
                    # Small yield to let the chat request start first
                    await asyncio.sleep(0.05)
                    t0 = time.perf_counter()
                    resp = await client.get("/health", timeout=5.0)
                    elapsed = time.perf_counter() - t0
                    return resp, elapsed

                chat_task = asyncio.create_task(do_chat())
                health_task = asyncio.create_task(do_health())

                chat_resp, (health_resp, health_elapsed) = await asyncio.gather(
                    chat_task, health_task
                )

    finally:
        app.dependency_overrides.clear()

    assert health_resp.status_code == 200, f"Health check failed: {health_resp.status_code}"
    assert chat_resp.status_code == 200, f"Chat failed: {chat_resp.status_code}"
    assert health_elapsed < 0.3, (
        f"/health took {health_elapsed:.3f}s — event loop was blocked. "
        "Ensure chat_about_transcript is wrapped in run_in_threadpool."
    )
