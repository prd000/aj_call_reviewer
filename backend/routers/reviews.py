import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from modules.storage import RECORDINGS_DIR, delete_recording, delete_review, get_review, list_reviews, save_review
from modules.transcriber import transcribe
from modules.reviewer import identify_speakers, review_call

logger = logging.getLogger(__name__)

router = APIRouter()


class ProcessRequestBody(BaseModel):
    criteria: list[dict]
    template_name: str = ""
    template_id: str | None = None


def _review_summary(review: dict) -> dict:
    overall_score = None
    categories = review.get("review", {}).get("categories", [])
    if categories:
        scores = [c["score"] for c in categories if isinstance(c.get("score"), (int, float))]
        if scores:
            overall_score = round(sum(scores) / len(scores), 1)

    return {
        "id": review["id"],
        "created_at": review["created_at"],
        "status": review.get("status", "pending"),
        "metadata": review.get("metadata", {}),
        "overall_score": overall_score,
    }


@router.get("/reviews")
def get_reviews():
    all_reviews = list_reviews()
    return [_review_summary(r) for r in all_reviews]


@router.get("/reviews/{review_id}")
def get_review_by_id(review_id: str):
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    return review


@router.delete("/reviews/{review_id}", status_code=204)
def delete_review_by_id(review_id: str):
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    delete_review(review_id)
    return Response(status_code=204)


@router.post("/reviews/{review_id}/process")
def process_review(review_id: str, body: ProcessRequestBody):
    """
    Trigger synchronous transcription and review generation for a review.

    Accepts a process body with criteria (from the selected template) and
    records a framework snapshot alongside the review result.
    """
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")

    if review.get("status") == "complete":
        logger.info("Review %s is already complete, skipping processing.", review_id)
        return review

    review["status"] = "transcribing"
    save_review(review)

    original_filename = review.get("metadata", {}).get("original_filename", "recording")
    recording_path = RECORDINGS_DIR / f"{review_id}_{original_filename}"

    try:
        logger.info("Starting transcription for review %s", review_id)
        transcript = transcribe(recording_path)
        review["transcript"] = transcript
        logger.info(
            "Transcription complete for review %s (%d segments)",
            review_id,
            len(transcript),
        )
        speaker_map = identify_speakers(transcript)
        review["speaker_map"] = {str(k): v for k, v in speaker_map.items()}
        logger.info("Speaker map for review %s: %s", review_id, review["speaker_map"])

        deleted = delete_recording(review_id, original_filename)
        if deleted:
            logger.info("Recording file deleted for review %s after transcription.", review_id)
        else:
            logger.warning("Recording file not found for review %s; skipping deletion.", review_id)
    except Exception as exc:
        logger.error("Transcription failed for review %s: %s", review_id, exc, exc_info=True)
        review["status"] = "error"
        review["error"] = f"Transcription failed: {str(exc)}"
        save_review(review)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(exc)}")

    review["status"] = "reviewing"
    save_review(review)

    try:
        logger.info("Starting review generation for review %s", review_id)
        review_data = review_call(review["transcript"], body.criteria)
        review["review"] = review_data
        review["framework"] = {
            "template_name": body.template_name,
            "template_id": body.template_id,
            "criteria": body.criteria,
        }
        review["status"] = "complete"
        logger.info("Review generation complete for review %s", review_id)
    except Exception as exc:
        logger.error(
            "Review generation failed for review %s: %s", review_id, exc, exc_info=True
        )
        review["status"] = "error"
        review["error"] = f"Review generation failed: {str(exc)}"
        save_review(review)
        raise HTTPException(
            status_code=500, detail=f"Review generation failed: {str(exc)}"
        )

    save_review(review)
    return review
