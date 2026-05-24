import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from modules.storage import delete_recording_from_storage, delete_review, get_review, list_reviews

logger = logging.getLogger(__name__)

router = APIRouter()


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
    if review.get("storage_path"):
        delete_recording_from_storage(review["storage_path"])
    return Response(status_code=204)
