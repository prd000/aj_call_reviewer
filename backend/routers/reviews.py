import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from modules.auth import get_current_user
from modules.storage import delete_recording_from_storage, delete_review, get_review, list_reviews

logger = logging.getLogger(__name__)

router = APIRouter()


def _review_summary(review: dict) -> dict:
    overall_score = None
    overall_max_score = None
    categories = review.get("review", {}).get("categories", [])
    if categories:
        scored = [c for c in categories if isinstance(c.get("score"), (int, float))]
        if scored:
            overall_score = sum(c["score"] for c in scored)
            overall_max_score = sum(c.get("max_score", 10) for c in scored)

    return {
        "id": review["id"],
        "created_at": review["created_at"],
        "status": review.get("status", "pending"),
        "metadata": review.get("metadata", {}),
        "overall_score": overall_score,
        "overall_max_score": overall_max_score,
    }


def _fa_can_access(review: dict, user: dict) -> bool:
    """Return True if an FA user is permitted to see this review."""
    return (
        review.get("firm_id") == user["firm_id"]
        and review.get("uploader_role") == "financial_advisor"
    )


@router.get("/reviews")
async def get_reviews(user: dict = Depends(get_current_user)):
    if user["role"] == "financial_advisor":
        all_reviews = await list_reviews(
            firm_id=user["firm_id"],
            uploader_role="financial_advisor",
        )
    else:
        all_reviews = await list_reviews()
    return [_review_summary(r) for r in all_reviews]


@router.get("/reviews/{review_id}")
async def get_review_by_id(review_id: str, user: dict = Depends(get_current_user)):
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    if user["role"] == "financial_advisor" and not _fa_can_access(review, user):
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    return review


@router.delete("/reviews/{review_id}", status_code=204)
async def delete_review_by_id(review_id: str, user: dict = Depends(get_current_user)):
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    if user["role"] == "financial_advisor" and not _fa_can_access(review, user):
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    await delete_review(review_id)
    if review.get("storage_path"):
        await delete_recording_from_storage(review["storage_path"])
    return Response(status_code=204)
