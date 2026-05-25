import asyncio
import logging

from celery.exceptions import MaxRetriesExceededError

from celery_app import app
from modules import storage, transcriber, reviewer
from modules.templates import get_template
import modules.supabase_client as _supabase_client

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=2, default_retry_delay=10)
def process_review_task(self, review_id: str, template_id: str):
    async def _run():
        # Reset the singleton so this task's event loop gets a fresh client.
        # Each asyncio.run() creates a new loop; reusing a client from a prior
        # closed loop raises "Event loop is closed" errors in httpx.
        _supabase_client._client = None

        template = await get_template(template_id)
        criteria = template["criteria"]

        await storage.update_review_status(review_id, "transcribing")
        review = await storage.get_review(review_id)
        if not review:
            logger.error("Review %s not found in database — marking failed, no retry", review_id)
            await storage.update_review_status(review_id, "failed", error_message="Review record not found in database")
            return
        if not review.get("storage_path"):
            logger.error("Review %s has no storage_path — marking failed, no retry", review_id)
            await storage.update_review_status(review_id, "failed", error_message="No storage path for recording")
            return
        signed_url = await storage.get_recording_signed_url(review["storage_path"])

        logger.info("Starting transcription for review %s", review_id)
        transcript = transcriber.transcribe(signed_url)
        speaker_map = reviewer.identify_speakers(transcript)
        logger.info("Transcription complete for review %s (%d segments)", review_id, len(transcript))

        await storage.update_review_status(review_id, "reviewing")

        logger.info("Starting review generation for review %s", review_id)
        review_data = reviewer.review_call(transcript, criteria)
        logger.info("Review generation complete for review %s", review_id)

        review["transcript"] = transcript
        review["speaker_map"] = {str(k): v for k, v in speaker_map.items()}
        review["review"] = review_data
        review["framework"] = {
            "template_name": template.get("name", ""),
            "template_id": template_id,
            "criteria": criteria,
        }
        review["status"] = "complete"
        await storage.save_review(review)
        await storage.delete_recording_from_storage(review["storage_path"])

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("Task failed for review %s: %s", review_id, exc, exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for review %s, marking as failed.", review_id)

            async def _cleanup():
                _supabase_client._client = None
                await storage.update_review_status(review_id, "failed", error_message=str(exc))
                try:
                    r = await storage.get_review(review_id)
                    if r and r.get("storage_path"):
                        await storage.delete_recording_from_storage(r["storage_path"])
                except Exception:
                    pass

            try:
                asyncio.run(_cleanup())
            except Exception:
                pass
