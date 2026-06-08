import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from modules.auth import get_current_user, require_bds_rep
from modules.firms import list_firms
from modules.ingestion import CallOutcome
from modules.history_chat import chat_over_reviews
from modules.pdf_export import render_review_pdf, review_pdf_filename
from modules.reviewer import LLMUnavailableError, chat_about_transcript, generate_major_focus
from modules.storage import (
    delete_recording_from_storage,
    delete_review,
    get_review,
    list_reviews,
    update_review_major_focus,
    update_review_outcome,
)
from modules.user_profiles import list_bds_reps, list_profiles_by_ids

logger = logging.getLogger(__name__)

router = APIRouter()


def _review_summary(
    review: dict,
    firm_rep_map: dict | None = None,
    uploader_map: dict | None = None,
) -> dict:
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

    # Surface the review template (from the framework snapshot) and the firm's
    # assigned BDS rep alongside the existing advisor/firm/outcome metadata so the
    # history filters can read them the same way. bds_rep_name and uploaded_by_name
    # are only resolved for BDS-rep callers (maps provided); FA responses omit them.
    metadata = dict(review.get("metadata", {}))
    framework = review.get("framework") or {}
    metadata["template_name"] = framework.get("template_name")
    if firm_rep_map is not None:
        metadata["bds_rep_name"] = firm_rep_map.get(review.get("firm_id"))
    if uploader_map is not None:
        metadata["uploaded_by_name"] = uploader_map.get(review.get("uploaded_by"))

    return {
        "id": review["id"],
        "created_at": review["created_at"],
        "status": review.get("status", "pending"),
        "metadata": metadata,
        "overall_score": overall_score,
        "overall_max_score": overall_max_score,
    }


async def _build_firm_bds_rep_map() -> dict:
    """Map firm_id -> assigned BDS rep name, resolving firms.bds_rep_id via profiles.

    Used to annotate review summaries for BDS reps so history can filter by the
    BDS rep assigned to each review's firm.
    """
    firms = await list_firms()
    reps = await list_bds_reps()
    rep_name_by_id = {r["id"]: r.get("name") for r in reps}
    return {
        f["id"]: rep_name_by_id.get(f.get("bds_rep_id"))
        for f in firms
        if f.get("bds_rep_id")
    }


async def _build_uploader_name_map(reviews: list[dict]) -> dict:
    """Map uploaded_by (profile id) -> uploader name, for the loaded reviews."""
    ids = [r.get("uploaded_by") for r in reviews]
    profiles = await list_profiles_by_ids(ids)
    return {p["id"]: p.get("name") for p in profiles}


class OutcomeBody(BaseModel):
    # None clears the outcome; any non-canonical string is rejected with 422.
    call_outcome: CallOutcome | None = None


class MajorFocusBody(BaseModel):
    criterion_id: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatBody(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    answer: str


class HistoryChatBody(BaseModel):
    review_ids: list[str]
    messages: list[ChatMessage]


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
        return [_review_summary(r) for r in all_reviews]

    all_reviews = await list_reviews()
    firm_rep_map = await _build_firm_bds_rep_map()
    uploader_map = await _build_uploader_name_map(all_reviews)
    return [_review_summary(r, firm_rep_map, uploader_map) for r in all_reviews]


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


@router.patch("/reviews/{review_id}/major-focus")
async def update_review_major_focus_by_id(
    review_id: str,
    body: MajorFocusBody,
    user: dict = Depends(require_bds_rep),
):
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")

    if review.get("status") != "complete":
        raise HTTPException(status_code=400, detail="Review is not complete yet.")

    categories = (review.get("review") or {}).get("categories", [])
    if not categories:
        raise HTTPException(status_code=400, detail="Review has no scored categories.")

    framework_criteria = (review.get("framework") or {}).get("criteria", [])
    if not framework_criteria:
        raise HTTPException(status_code=400, detail="Review has no framework criteria.")

    criterion = next((c for c in framework_criteria if c.get("id") == body.criterion_id), None)
    if criterion is None:
        raise HTTPException(status_code=400, detail=f"Criterion '{body.criterion_id}' not found in this review's framework.")

    criterion_index = framework_criteria.index(criterion)
    if criterion_index >= len(categories):
        raise HTTPException(status_code=400, detail="Criterion index out of range for scored categories.")
    category = categories[criterion_index]

    transcript = review.get("transcript") or []

    try:
        text = generate_major_focus(transcript, criterion, category)
    except LLMUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Major focus generation is unavailable: no AI provider is configured.",
        )
    except Exception as exc:
        logger.error("update_review_major_focus_by_id failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Couldn't generate major focus. Please try again later.",
        )

    focus = {
        "criterion_id": body.criterion_id,
        "criterion_title": criterion.get("title", ""),
        "text": text,
        "is_auto": False,
    }
    await update_review_major_focus(review_id, focus)
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
            review_results=review.get("review"),
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


@router.post("/reviews/history-chat", response_model=ChatResponse)
async def chat_over_history(
    body: HistoryChatBody,
    user: dict = Depends(get_current_user),
):
    if not body.messages or body.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="Last message must be from the user.")

    # Resolve scope server-side: drop unknown, non-complete, and FA-invisible IDs.
    scoped: list[dict] = []
    for rid in body.review_ids:
        review = await get_review(rid)
        if review is None:
            continue
        if review.get("status") != "complete":
            continue
        if user["role"] == "financial_advisor" and not _fa_can_access(review, user):
            continue
        # Complete reviews must have scored categories to be useful.
        if not (review.get("review") or {}).get("categories"):
            continue
        scoped.append(review)

    if not scoped:
        return ChatResponse(
            answer="No completed calls match the current filters. Try broadening your search."
        )

    try:
        answer = chat_over_reviews(scoped, [m.model_dump() for m in body.messages])
        return ChatResponse(answer=answer)
    except LLMUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Chat is unavailable: no AI provider is configured.",
        )
    except Exception as exc:
        logger.error("chat_over_history failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Couldn't get an answer. Please try again later.",
        )


@router.get("/reviews/{review_id}/pdf")
async def download_review_pdf(review_id: str, user: dict = Depends(get_current_user)):
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    if user["role"] == "financial_advisor" and not _fa_can_access(review, user):
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    if review.get("status") != "complete" or not (review.get("review") or {}).get("categories"):
        raise HTTPException(status_code=400, detail="Review is not finished yet.")
    pdf_bytes = await run_in_threadpool(render_review_pdf, review)
    filename = review_pdf_filename(review)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
