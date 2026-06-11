import os
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Time-limit ordering invariant (must be maintained if any of these are tuned):
#   1800 (transcription poll ceiling) < soft (3000) < hard (3300) < 3600 (visibility_timeout)
# Soft too low kills legitimate long transcriptions; both must stay under visibility_timeout
# so a hard-killed task redelivers rather than double-runs (safe because the task is idempotent).
# See also: transcriber._POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SECONDS = 1800s.
_SOFT_TIME_LIMIT = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "3000"))
_HARD_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", "3300"))

app = Celery(
    "call_reviewer",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    backend=None,
    include=["tasks"],
)

app.conf.update(
    broker_transport_options={
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
        # Redis redelivers an in-flight (acks_late) task if it isn't acked within
        # this window, so it MUST exceed worst-case task runtime: the transcription
        # ceiling is transcriber._POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SECONDS
        # (360 * 5 = 1800s) plus per-criterion LLM review. If _POLL_MAX_ATTEMPTS is
        # raised, raise this too. Any redelivery is safe (no-op / resume) because
        # process_review_task is idempotent and checkpoints its transcript.
        "visibility_timeout": 3600,
    },
    # Ack only after the task finishes, so a worker crash/redeploy mid-job
    # redelivers the message (resuming from the transcript checkpoint) instead of
    # silently stranding the review forever in transcribing/reviewing.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Long-running tasks: don't let a busy worker reserve a backlog it can't
    # process within the visibility window.
    worker_prefetch_multiplier=1,
    # Backstop time limits — catches a hung LLM or Rev.ai call that Part A's
    # per-request timeout misses (e.g. the rev_ai SDK has no built-in timeout).
    # Soft fires SoftTimeLimitExceeded; task handler writes failed + no retry.
    # Hard SIGKILL is a last resort.
    task_soft_time_limit=_SOFT_TIME_LIMIT,
    task_time_limit=_HARD_TIME_LIMIT,
    # Reaper: mark stuck in-progress reviews failed every 2 minutes (120s).
    # With STUCK_REVIEWING_THRESHOLD_SECONDS=720 (12 min), worst-case detection
    # is ~14 min — inside the 15-min target. Cost is one indexed query per
    # in-progress status per run; negligible.
    # REVIEW_PHASE_TIMEOUT_SECONDS (default 240s) is the finer in-process bound
    # that fires inside a worker long before the soft/hard Celery limits or the
    # reaper; the reaper is a pure DB-state backstop for rows with no owning task.
    # Run beat embedded in the worker (-B flag in Procfile).
    # If worker replicas are ever scaled > 1, split beat into its own
    # single-replica service to avoid duplicate scheduling.
    beat_schedule={
        "reap-stuck-reviews": {
            "task": "tasks.reap_stuck_reviews",
            "schedule": float(os.environ.get("REAP_INTERVAL_SECONDS", "120")),
        },
    },
)
