import os
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

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
)
