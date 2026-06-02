import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from modules.auth import get_current_user
from modules.ingestion import CallOutcome
from modules.reviewer import LLMUnavailableError, chat_about_transcript
from modules.storage import (
    delete_recording_from_storage,
    delete_review,
    get_review,
    list_reviews,
    update_review_outcome,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _review_summary(review: dict) -> dict:
    overall_score = None
    overall_max_score = None
    categories = review.get("review", {}).get("categories", [])
    if categories:
        scored = [c for c in categories if isinstance(c.get("score"), (int, float))]
        if scored:
            total_score = sum(c["score"] for c in scored)
            total_max = sum(c.get("max_score", 10) for c in scored)
            overall_score = round((total_score / total_max) * 10, 1)
            overall_max_score = 10

    return {
        "id": review["id"],
        "created_at": review["created_at"],
        "status": review.get("status", "pending"),
        "metadata": review.get("metadata", {}),
        "overall_score": overall_score,
        "overall_max_score": overall_max_score,
    }


class OutcomeBody(BaseModel):
    # None clears the outcome; any non-canonical string is rejected with 422.
    call_outcome: CallOutcome | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatBody(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    answer: str


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


@router.patch("/reviews/{review_id}/outcome")
async def update_review_outcome_by_id(
    review_id: str,
    body: OutcomeBody,
    user: dict = Depends(get_current_user),
):
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    if user["role"] == "financial_advisor" and not _fa_can_access(review, user):
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    # Outcome is metadata, editable regardless of review status.
    await update_review_outcome(review_id, body.call_outcome)
    return await get_review(review_id)


@router.post("/reviews/{review_id}/chat", response_model=ChatResponse)
async def chat_about_review(
    review_id: str,
    body: ChatBody,
    user: dict = Depends(get_current_user),
):
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    if user["role"] == "financial_advisor" and not _fa_can_access(review, user):
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")

    transcript = review.get("transcript") or []
    if not transcript:
        raise HTTPException(status_code=400, detail="This review has no transcript to chat about.")
    if not body.messages or body.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="Last message must be from the user.")

    try:
        answer = chat_about_transcript(
            transcript,
            review.get("speaker_map", {}),
            [m.model_dump() for m in body.messages],
            framework=review.get("framework"),
        )
        return ChatResponse(answer=answer)
    except LLMUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Chat is unavailable: no AI provider is configured.",
        )
    except Exception as exc:
        logger.error("chat_about_review failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Couldn't get an answer. Please try again later.",
        )


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
