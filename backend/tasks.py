import asyncio
import concurrent.futures
import logging
import os
from datetime import datetime, timezone, timedelta

from celery.exceptions import SoftTimeLimitExceeded

from celery_app import app
from modules import storage, transcriber, reviewer
from modules.templates import get_template
import modules.supabase_client as _supabase_client

logger = logging.getLogger(__name__)


def _get_stuck_threshold_seconds(status: str) -> int:
    """Return the stuck-detection threshold (seconds) for a given in-progress status.

    STUCK_REVIEW_THRESHOLD_SECONDS (old single-threshold env var) is intentionally
    NOT read here; honoring it would re-introduce the single-threshold bug where the
    conservative transcription ceiling inflates the reviewing threshold.
    """
    defaults = {
        "pending": ("STUCK_PENDING_THRESHOLD_SECONDS", 300),
        "transcribing": ("STUCK_TRANSCRIBING_THRESHOLD_SECONDS", 2100),
        "reviewing": ("STUCK_REVIEWING_THRESHOLD_SECONDS", 720),
    }
    env_var, default = defaults.get(status, ("", 720))
    if not env_var:
        return default
    raw = os.environ.get(env_var, "").strip()
    try:
        val = int(raw) if raw else default
    except ValueError:
        val = default
    return max(1, val)


def _get_review_phase_timeout_seconds() -> int:
    raw = os.environ.get("REVIEW_PHASE_TIMEOUT_SECONDS", "").strip()
    try:
        val = int(raw) if raw else 240
    except ValueError:
        val = 240
    return max(1, val)


def _review_call_with_timeout(transcript, criteria, timeout_s: int):
    """Run reviewer.review_call in a thread with a hard wall-clock timeout.

    Uses ThreadPoolExecutor so the timeout is cross-platform (Windows dev +
    Linux/Railway prod). Trade-off: on TimeoutError the worker thread is orphaned
    and keeps running until the LLM's own 120s timeout (+1 internal retry ≈ 240s)
    fires. The Celery task slot is freed immediately because the task raises and acks.

    We avoid the 'with' context manager because its __exit__ calls shutdown(wait=True),
    which joins the orphaned thread and silently waits for the hung LLM call —
    defeating the purpose of the timeout entirely.
    """
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(reviewer.review_call, transcript, criteria)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(
                f"review_call exceeded the {timeout_s}s per-attempt timeout"
            )
    finally:
        ex.shutdown(wait=False)


async def _mark_review_failed(review_id: str, error_message: str, *, guard_terminal: bool = False) -> None:
    # Mark the review failed but KEEP its recording so it stays retryable. The
    # recording is deleted only once transcription succeeds and the transcript is
    # checkpointed (see _run): a transcription-phase failure therefore still has
    # its audio for a re-transcribe, and a review-phase failure already has its
    # transcript and never needs the audio again.
    await storage.update_review_status(review_id, "failed", error_message=error_message, guard_terminal=guard_terminal)


def _fail_in_new_loop(review_id: str, error_message: str, *, guard_terminal: bool = False) -> None:
    _supabase_client._client = None
    try:
        asyncio.run(_mark_review_failed(review_id, error_message, guard_terminal=guard_terminal))
    except Exception:
        logger.exception("_fail_in_new_loop: could not write failed status for review %s", review_id)


@app.task(bind=True, max_retries=2, default_retry_delay=10)
def process_review_task(self, review_id: str, template_id: str):
    async def _run():
        # Reset the singleton so this task's event loop gets a fresh client.
        # Each asyncio.run() creates a new loop; reusing a client from a prior
        # closed loop raises "Event loop is closed" errors in httpx.
        _supabase_client._client = None

        # Fetch the review BEFORE any status write so the idempotency guard and
        # the checkpoint/resume decision can run without first regressing status.
        review = await storage.get_review(review_id)
        if not review:
            logger.error("Review %s not found in database — marking failed, no retry", review_id)
            await storage.update_review_status(review_id, "failed", error_message="Review record not found in database")
            return

        # Prefer the framework snapshot saved at upload (Bug #2 fix: framework is
        # now written at upload, not only on completion). Fall back to fetching the
        # template live for legacy rows that predate the upload-time framework save.
        framework = review.get("framework") or {}
        criteria = framework.get("criteria")
        template_name = framework.get("template_name", "")
        if not criteria:
            template = await get_template(template_id)
            if not template:
                logger.error("Review %s has no persisted framework and template %s not found", review_id, template_id)
                await storage.update_review_status(
                    review_id, "failed",
                    error_message="Template not found and no persisted framework"
                )
                return
            criteria = template["criteria"]
            template_name = template.get("name", "")

        # Idempotency guard: never reprocess a finished review. Protects against a
        # duplicate/late delivery or a retry that fires after a successful complete.
        if review.get("status") == "complete":
            logger.info("Review %s already complete — idempotent no-op (retry %s)", review_id, self.request.retries)
            return

        # Checkpoint/resume decision. Gate on transcript only — an empty speaker_map
        # ({}) is legitimate (e.g. <2 speakers) and must NOT force a re-transcribe.
        existing_transcript = review.get("transcript")
        if existing_transcript:
            transcript = existing_transcript
            speaker_map = review.get("speaker_map") or {}
            logger.info(
                "Review %s resuming from persisted transcript (%d segments) — skipping Rev.ai (retry %s)",
                review_id, len(transcript), self.request.retries,
            )
        else:
            await storage.update_review_status(review_id, "transcribing", guard_terminal=True)
            if not review.get("storage_path"):
                logger.error("Review %s has no storage_path — marking failed, no retry", review_id)
                await storage.update_review_status(review_id, "failed", error_message="No storage path for recording")
                return
            # Signed URL fetched lazily here so the resume path never references a
            # recording that a prior attempt may already have deleted.
            signed_url = await storage.get_recording_signed_url(review["storage_path"])
            logger.info("Starting transcription for review %s", review_id)
            transcript = transcriber.transcribe(signed_url)
            speaker_map = {str(k): v for k, v in reviewer.identify_speakers(transcript).items()}
            logger.info("Transcription complete for review %s (%d segments)", review_id, len(transcript))
            # CHECKPOINT — persist the transcript BEFORE flipping to "reviewing".
            # If status flipped first and this write failed, a retry would see
            # "reviewing" + no transcript and re-submit Rev.ai, defeating the fix.
            await storage.update_review_transcript(review_id, transcript, speaker_map)
            logger.info("Transcript checkpoint persisted for review %s", review_id)
            # Recording is disposable once the transcript is checkpointed — a retry
            # resumes from the transcript, never the audio. Delete it HERE (not on
            # complete/failed) so a transcription-phase failure keeps its recording
            # and stays retryable. Non-fatal: silent if already removed.
            await storage.delete_recording_from_storage(review["storage_path"])
            logger.info("Recording deleted post-transcription for review %s", review_id)

        await storage.update_review_status(review_id, "reviewing", guard_terminal=True)

        logger.info("Starting review generation for review %s", review_id)
        review_timeout = _get_review_phase_timeout_seconds()
        review_data = _review_call_with_timeout(transcript, criteria, review_timeout)
        logger.info("Review generation complete for review %s", review_id)

        review["transcript"] = transcript
        review["speaker_map"] = speaker_map
        review["review"] = review_data
        review["framework"] = {
            "template_name": template_name,
            "template_id": template_id,
            "criteria": criteria,
        }
        review["status"] = "complete"

        # Default major focus — non-fatal; never blocks pipeline completion.
        # Intentionally re-runs on a resumed attempt (one extra LLM call); cheap
        # relative to re-transcribing and never marks the review failed.
        try:
            categories = review_data.get("categories", [])
            idx = reviewer.pick_default_focus_index(categories)
            if idx is not None and idx < len(criteria):
                criterion = criteria[idx]
                category = categories[idx]
                advisor_name = (review.get("metadata") or {}).get("advisor_name") or ""
                focus_text = reviewer.generate_major_focus(transcript, criterion, category, advisor_name)
                review["major_focus"] = {
                    "criterion_id": criterion.get("id", ""),
                    "criterion_title": criterion.get("title", ""),
                    "text": focus_text,
                    "is_auto": True,
                }
                logger.info("Major focus auto-generated for review %s (criterion: %s)", review_id, criterion.get("title"))
        except Exception as exc:
            logger.warning("Major focus generation failed for review %s: %s", review_id, exc)

        await storage.save_review(review)
        # The recording was already deleted right after the transcript checkpoint
        # (or in a prior attempt on the resume path), so there's nothing to clean
        # up here on completion.

    try:
        asyncio.run(_run())
    except SoftTimeLimitExceeded:
        # Celery raised SoftTimeLimitExceeded: the task ran past task_soft_time_limit.
        # Write failed immediately — do NOT retry (retrying re-runs the same long work
        # and re-hangs). This breaks the silent redelivery loop for stuck reviews.
        logger.error(
            "Soft time limit exceeded for review %s — marking failed, no retry",
            review_id,
        )
        _fail_in_new_loop(
            review_id,
            f"Task exceeded soft time limit of {app.conf.task_soft_time_limit}s",
        )
    except Exception as exc:
        logger.error(
            "Task failed for review %s (attempt %s/%s): %s",
            review_id, self.request.retries, self.max_retries, exc, exc_info=True,
        )
        if self.request.retries >= self.max_retries:
            # Celery's retry(exc=...) re-raises the ORIGINAL exc on exhaustion, never
            # MaxRetriesExceededError — so the failed write must happen BEFORE retry().
            logger.error("Max retries exceeded for review %s, marking as failed.", review_id)
            _fail_in_new_loop(review_id, str(exc))
            raise  # keep the Celery task in FAILURE state
        logger.warning(
            "Retrying review %s (attempt %s of %s) in %ss — resumes from checkpoint",
            review_id, self.request.retries + 1, self.max_retries, self.default_retry_delay,
        )
        raise self.retry(exc=exc)


@app.task(bind=True)
def reap_stuck_reviews(self):
    async def _run():
        _supabase_client._client = None
        total_stuck = 0
        total_reaped = 0
        for status in storage.IN_PROGRESS_STATUSES:
            threshold = _get_stuck_threshold_seconds(status)
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=threshold)).isoformat()
            stuck = await storage.list_stuck_reviews(cutoff, statuses=(status,))
            if not stuck:
                continue
            logger.warning(
                "Stuck-review reaper: found %d '%s' candidate(s) older than %ds",
                len(stuck), status, threshold,
            )
            total_stuck += len(stuck)
            for row in stuck:
                rid = row["id"]
                try:
                    await _mark_review_failed(
                        rid,
                        f"Auto-failed by stuck-review reaper: no progress for >{threshold}s (was '{status}')",
                        guard_terminal=True,
                    )
                    total_reaped += 1
                    logger.warning("Reaper: marked review %s failed (was '%s')", rid, status)
                except Exception as exc:
                    logger.error("Reaper: failed to mark review %s: %s", rid, exc, exc_info=True)
        logger.warning("Stuck-review reaper: reaped %d/%d across all statuses", total_reaped, total_stuck)

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("Stuck-review reaper crashed: %s", exc, exc_info=True)
