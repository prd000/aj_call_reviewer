import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded

from celery_app import app
from modules import storage, transcriber, reviewer
from modules.templates import get_template
import modules.supabase_client as _supabase_client

logger = logging.getLogger(__name__)


def _get_stuck_threshold_seconds() -> int:
    raw = os.environ.get("STUCK_REVIEW_THRESHOLD_SECONDS", "").strip()
    try:
        val = int(raw) if raw else 5400
    except ValueError:
        val = 5400
    return max(1, val)


async def _mark_failed_and_cleanup(review_id: str, error_message: str, *, guard_terminal: bool = False) -> None:
    await storage.update_review_status(review_id, "failed", error_message=error_message, guard_terminal=guard_terminal)
    try:
        r = await storage.get_review(review_id)
        if r and r.get("storage_path"):
            await storage.delete_recording_from_storage(r["storage_path"])
    except Exception:
        pass


def _fail_in_new_loop(review_id: str, error_message: str, *, guard_terminal: bool = False) -> None:
    _supabase_client._client = None
    try:
        asyncio.run(_mark_failed_and_cleanup(review_id, error_message, guard_terminal=guard_terminal))
    except Exception:
        pass


@app.task(bind=True, max_retries=2, default_retry_delay=10)
def process_review_task(self, review_id: str, template_id: str):
    async def _run():
        # Reset the singleton so this task's event loop gets a fresh client.
        # Each asyncio.run() creates a new loop; reusing a client from a prior
        # closed loop raises "Event loop is closed" errors in httpx.
        _supabase_client._client = None

        template = await get_template(template_id)
        criteria = template["criteria"]

        # Fetch the review BEFORE any status write so the idempotency guard and
        # the checkpoint/resume decision can run without first regressing status.
        review = await storage.get_review(review_id)
        if not review:
            logger.error("Review %s not found in database — marking failed, no retry", review_id)
            await storage.update_review_status(review_id, "failed", error_message="Review record not found in database")
            return

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

        await storage.update_review_status(review_id, "reviewing", guard_terminal=True)

        logger.info("Starting review generation for review %s", review_id)
        review_data = reviewer.review_call(transcript, criteria)
        logger.info("Review generation complete for review %s", review_id)

        review["transcript"] = transcript
        review["speaker_map"] = speaker_map
        review["review"] = review_data
        review["framework"] = {
            "template_name": template.get("name", ""),
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
        await storage.delete_recording_from_storage(review["storage_path"])

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
        try:
            if self.request.retries < self.max_retries:
                logger.warning(
                    "Retrying review %s (attempt %s of %s) in %ss — resumes from checkpoint",
                    review_id, self.request.retries + 1, self.max_retries, self.default_retry_delay,
                )
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for review %s, marking as failed.", review_id)
            _fail_in_new_loop(review_id, str(exc))


@app.task(bind=True)
def reap_stuck_reviews(self):
    threshold = _get_stuck_threshold_seconds()

    async def _run():
        _supabase_client._client = None
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=threshold)).isoformat()
        stuck = await storage.list_stuck_reviews(cutoff)
        logger.warning("Stuck-review reaper: found %d candidate(s) older than %ds", len(stuck), threshold)
        reaped = 0
        for row in stuck:
            rid = row["id"]
            old_status = row.get("status", "unknown")
            try:
                await _mark_failed_and_cleanup(
                    rid,
                    f"Auto-failed by stuck-review reaper: no progress for >{threshold}s (was '{old_status}')",
                    guard_terminal=True,
                )
                reaped += 1
                logger.warning("Reaper: marked review %s failed (was '%s')", rid, old_status)
            except Exception as exc:
                logger.error("Reaper: failed to mark review %s: %s", rid, exc, exc_info=True)
        logger.warning("Stuck-review reaper: reaped %d/%d", reaped, len(stuck))

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("Stuck-review reaper crashed: %s", exc, exc_info=True)
