"""Tests for process_review_task (Bug #2 fix).

Covers: idempotency no-op on a complete review, transcript checkpoint + resume so
a review-phase retry never re-transcribes, the inverse (a transcription-phase
failure DOES re-transcribe), the guarded status write, and the Celery
delivery-hardening config.

Retries are simulated deterministically (independent of Celery eager-retry
semantics): `process_review_task.retry` is patched to abort the current attempt,
and the task is re-invoked against the same in-memory fake DB — exactly what a
real retry does. The fake DB persists the transcript checkpoint between attempts.
"""
import asyncio
import logging
from unittest.mock import patch, MagicMock, AsyncMock

import tasks as tasks_module
from tasks import process_review_task
from modules import storage
from celery_app import app


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

class _RetryAbort(Exception):
    """Stand-in for Celery's Retry exception: aborts the current attempt so the
    test can re-invoke the task to simulate the scheduled retry."""


class FakeReviewDB:
    """In-memory single-review store mimicking the storage helpers the task uses,
    so a transcript checkpoint survives across simulated retries."""

    def __init__(self, **row):
        self.row = {
            "id": "rev-1",
            "status": "pending",
            "storage_path": "rev-1/call.mp3",
            "transcript": None,
            "speaker_map": None,
            "metadata": {"advisor_name": "Jag"},
        }
        self.row.update(row)
        self.events = []          # ordered (kind, value) side-effect log
        self.status_writes = []   # ordered status strings written

    async def get_review(self, review_id):
        return dict(self.row)

    async def update_review_status(self, review_id, status, *, error_message=None,
                                   celery_task_id=None, guard_terminal=False):
        self.status_writes.append(status)
        self.events.append(("status", status))
        if guard_terminal and self.row.get("status") == "complete":
            return  # honor the no-regress guard
        self.row["status"] = status
        if error_message is not None:
            self.row["error_message"] = error_message

    async def update_review_transcript(self, review_id, transcript, speaker_map):
        self.events.append(("checkpoint", None))
        self.row["transcript"] = transcript
        self.row["speaker_map"] = speaker_map

    async def save_review(self, review):
        self.events.append(("save", None))
        self.row.update(review)
        return review["id"]

    async def get_recording_signed_url(self, storage_path):
        self.events.append(("signed_url", None))
        return "https://signed.example/recording"

    async def delete_recording_from_storage(self, storage_path):
        self.events.append(("delete", None))


TEMPLATE = {
    "name": "Test Template",
    "criteria": [
        {"id": "c1", "title": "Rapport", "description": "d", "success_condition": "s", "max_score": 10},
    ],
}

GOOD_TRANSCRIPT = [
    {"timestamp": "00:00:01", "text": "Hi", "speaker": 0},
    {"timestamp": "00:00:02", "text": "Hello", "speaker": 1},
]

GOOD_REVIEW = {"summary": "ok", "categories": [{"score": 5, "max_score": 10}]}


def _install(monkeypatch, fake, *, transcribe, review_call):
    """Wire the fake DB + sync pipeline mocks into the tasks module namespace."""
    for name in ("get_review", "update_review_status", "update_review_transcript",
                 "save_review", "get_recording_signed_url", "delete_recording_from_storage"):
        monkeypatch.setattr(tasks_module.storage, name, getattr(fake, name))
    monkeypatch.setattr(tasks_module, "get_template", AsyncMock(return_value=TEMPLATE))
    monkeypatch.setattr(tasks_module.transcriber, "transcribe", transcribe)
    monkeypatch.setattr(tasks_module.reviewer, "identify_speakers",
                        MagicMock(return_value={0: "Advisor", 1: "Prospect"}))
    monkeypatch.setattr(tasks_module.reviewer, "review_call", review_call)
    # Keep the (non-fatal) major-focus step a no-op.
    monkeypatch.setattr(tasks_module.reviewer, "pick_default_focus_index", MagicMock(return_value=None))


def _attempt():
    """Run one task attempt. Returns 'done' if it completed, or 'retried' if it
    aborted into the (patched) retry."""
    try:
        process_review_task("rev-1", "tpl-1")
        return "done"
    except _RetryAbort:
        return "retried"


def _count(events, kind):
    return sum(1 for k, _ in events if k == kind)


# ---------------------------------------------------------------------------
# (a) Review-phase failure -> transcribe called exactly ONCE across the retry
# ---------------------------------------------------------------------------

def test_review_failure_resumes_without_retranscribing(monkeypatch):
    fake = FakeReviewDB()
    transcribe = MagicMock(return_value=GOOD_TRANSCRIPT)
    review_call = MagicMock(side_effect=[RuntimeError("flaky LLM"), GOOD_REVIEW])
    _install(monkeypatch, fake, transcribe=transcribe, review_call=review_call)

    with patch.object(process_review_task, "retry", MagicMock(side_effect=_RetryAbort())) as retry:
        assert _attempt() == "retried"   # attempt 1: succeeds transcribing, fails in review
        assert _attempt() == "done"      # attempt 2: resumes from checkpoint

    assert transcribe.call_count == 1                       # CORE: no re-transcribe / no 2nd Rev.ai job
    assert review_call.call_count == 2                      # failed then resumed
    assert _count(fake.events, "checkpoint") == 1           # checkpoint written once
    assert _count(fake.events, "signed_url") == 1           # recording URL fetched only on the transcribe pass
    assert fake.status_writes.count("transcribing") == 1    # status never regressed after checkpoint
    assert fake.row["status"] == "complete"
    assert retry.call_count == 1


# ---------------------------------------------------------------------------
# (b) Already-complete review -> idempotent no-op
# ---------------------------------------------------------------------------

def test_complete_review_is_noop(monkeypatch, caplog):
    fake = FakeReviewDB(status="complete", transcript=GOOD_TRANSCRIPT)
    transcribe = MagicMock(return_value=GOOD_TRANSCRIPT)
    review_call = MagicMock(return_value=GOOD_REVIEW)
    _install(monkeypatch, fake, transcribe=transcribe, review_call=review_call)

    with patch.object(process_review_task, "retry", MagicMock(side_effect=_RetryAbort())):
        with caplog.at_level(logging.INFO, logger="tasks"):
            assert _attempt() == "done"

    transcribe.assert_not_called()
    review_call.assert_not_called()
    assert ("save", None) not in fake.events
    assert "transcribing" not in fake.status_writes
    assert "reviewing" not in fake.status_writes
    assert "idempotent no-op" in caplog.text


# ---------------------------------------------------------------------------
# (c) Guarded status write
# ---------------------------------------------------------------------------

def _make_query_recorder():
    calls = []

    class _Query:
        def update(self, patch_dict):
            calls.append(("update", patch_dict)); return self

        def eq(self, col, val):
            calls.append(("eq", col, val)); return self

        def neq(self, col, val):
            calls.append(("neq", col, val)); return self

        async def execute(self):
            calls.append(("execute",)); return MagicMock(data=[])

    class _Client:
        def table(self, name):
            calls.append(("table", name)); return _Query()

    return calls, _Client()


def test_update_review_status_guard_terminal_adds_neq(monkeypatch):
    calls, client = _make_query_recorder()
    monkeypatch.setattr(storage, "get_client", AsyncMock(return_value=client))
    asyncio.run(storage.update_review_status("r1", "transcribing", guard_terminal=True))
    assert ("neq", "status", "complete") in calls


def test_update_review_status_default_is_unconditional(monkeypatch):
    calls, client = _make_query_recorder()
    monkeypatch.setattr(storage, "get_client", AsyncMock(return_value=client))
    asyncio.run(storage.update_review_status("r1", "failed", error_message="x"))
    assert not any(c[0] == "neq" for c in calls)


# ---------------------------------------------------------------------------
# (d) Transcription-phase failure DOES re-transcribe (guard against over-fixing)
# ---------------------------------------------------------------------------

def test_transcription_failure_retranscribes(monkeypatch):
    fake = FakeReviewDB()
    transcribe = MagicMock(side_effect=[TimeoutError("revai timeout"), GOOD_TRANSCRIPT])
    review_call = MagicMock(return_value=GOOD_REVIEW)
    _install(monkeypatch, fake, transcribe=transcribe, review_call=review_call)

    with patch.object(process_review_task, "retry", MagicMock(side_effect=_RetryAbort())):
        assert _attempt() == "retried"   # attempt 1: transcription fails, nothing checkpointed
        assert _attempt() == "done"      # attempt 2: re-transcribes, succeeds

    assert transcribe.call_count == 2                   # correctly re-transcribed (no valid checkpoint)
    assert _count(fake.events, "checkpoint") == 1       # only the successful pass checkpoints
    assert fake.row["status"] == "complete"


# ---------------------------------------------------------------------------
# (e) Ordering invariant: checkpoint persisted BEFORE flipping to "reviewing"
# ---------------------------------------------------------------------------

def test_checkpoint_persisted_before_reviewing(monkeypatch):
    fake = FakeReviewDB()
    transcribe = MagicMock(return_value=GOOD_TRANSCRIPT)
    review_call = MagicMock(return_value=GOOD_REVIEW)
    _install(monkeypatch, fake, transcribe=transcribe, review_call=review_call)

    with patch.object(process_review_task, "retry", MagicMock(side_effect=_RetryAbort())):
        assert _attempt() == "done"

    cp_index = fake.events.index(("checkpoint", None))
    reviewing_index = next(i for i, (k, v) in enumerate(fake.events)
                           if k == "status" and v == "reviewing")
    assert cp_index < reviewing_index


# ---------------------------------------------------------------------------
# (f) Celery delivery-hardening config (Commit 2)
# ---------------------------------------------------------------------------

def test_celery_delivery_hardening_config():
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    # Must exceed the transcription poll ceiling (360 * 5 = 1800s) so an in-flight
    # task is never redelivered while still running.
    assert app.conf.broker_transport_options["visibility_timeout"] > 1800
