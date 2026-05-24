import logging

from celery.exceptions import MaxRetriesExceededError

from celery_app import app
from modules import storage, transcriber, reviewer
from modules.templates import get_template

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=2, default_retry_delay=10)
def process_review_task(self, review_id: str, template_id: str):
    try:
        storage.update_review_status(review_id, "pending", celery_task_id=self.request.id)

        template = get_template(template_id)
        criteria = template["criteria"]

        storage.update_review_status(review_id, "transcribing")
        review = storage.get_review(review_id)
        signed_url = storage.get_recording_signed_url(review["storage_path"])

        logger.info("Starting transcription for review %s", review_id)
        transcript = transcriber.transcribe(signed_url)
        speaker_map = reviewer.identify_speakers(transcript)
        logger.info("Transcription complete for review %s (%d segments)", review_id, len(transcript))

        storage.update_review_status(review_id, "reviewing")

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
        storage.save_review(review)
        storage.delete_recording_from_storage(review["storage_path"])

    except Exception as exc:
        logger.error("Task failed for review %s: %s", review_id, exc, exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for review %s, marking as failed.", review_id)
            storage.update_review_status(review_id, "failed", error_message=str(exc))
            try:
                r = storage.get_review(review_id)
                if r and r.get("storage_path"):
                    storage.delete_recording_from_storage(r["storage_path"])
            except Exception:
                pass
