import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from modules.auth import get_current_user, require_bds_rep
from modules.firms import list_firms
from modules.ingestion import CallOutcome
from modules.history_chat import chat_over_reviews
from modules.pdf_export import render_review_pdf, review_pdf_filename
from modules.reviewer import (
    LLMUnavailableError,
    chat_about_transcript,
    generate_coaching_email,
    generate_major_focus,
)
from modules.scoring import overall_score as _compute_overall_score
from modules.storage import (
    delete_recording_from_storage,
    delete_review,
    get_review,
    get_reviews_by_ids,
    list_review_summaries,
    list_reviews,
    update_review_major_focus,
    update_review_notes,
    update_review_outcome,
    update_review_status,
    update_review_tags,
)
from modules.tags import list_tags
from modules.user_profiles import list_bds_reps, list_profiles_by_ids
from tasks import process_review_task

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_LIST_LIMIT = 200


def _review_summary(
    review: dict,
    firm_rep_map: dict | None = None,
    uploader_map: dict | None = None,
    tag_map: dict | None = None,
) -> dict:
    # Use precomputed scores from the DB summary column when available.
    # Fall back to computing from categories for pre-migration rows.
    overall_score = review.get("overall_score")
    overall_max_score = review.get("overall_max_score")
    if overall_score is None:
        overall_score, overall_max_score = _compute_overall_score(review.get("review"))

    # Surface the review template and the firm's assigned BDS rep alongside the
    # existing advisor/firm/outcome metadata so history filters can read them the
    # same way. bds_rep_name and uploaded_by_name are only resolved for BDS-rep
    # callers (maps provided); FA responses omit them.
    metadata = dict(review.get("metadata", {}))
    # Prefer precomputed template_name DB column; fall back to framework jsonb
    # (for full rows not yet backfilled or pre-migration records).
    template_name = review.get("template_name") or (review.get("framework") or {}).get(
        "template_name"
    )
    metadata["template_name"] = template_name
    if firm_rep_map is not None:
        metadata["bds_rep_name"] = firm_rep_map.get(review.get("firm_id"))
    if uploader_map is not None:
        metadata["uploaded_by_name"] = uploader_map.get(review.get("uploaded_by"))
    if tag_map is not None:
        tag_ids = review.get("tag_ids") or []
        metadata["tags"] = [tag_map[tid] for tid in tag_ids if tid in tag_map]

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


class TagIdsBody(BaseModel):
    tag_ids: list[str]


class NotesBody(BaseModel):
    notes: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatBody(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    answer: str


class HistoryChatBody(BaseModel):
    review_ids: list[str] = Field(max_length=200)
    messages: list[ChatMessage]


def _fa_can_access(review: dict, user: dict) -> bool:
    """Return True if an FA user is permitted to see this review."""
    return (
        bool(user["firm_id"])  # NULL-firm FA can never match any review
        and review.get("firm_id") == user["firm_id"]
        and review.get("uploader_role") == "financial_advisor"
    )


async def get_visible_review_or_404(review_id: str, user: dict) -> dict:
    """Fetch a review and enforce FA visibility, raising 404 for missing or inaccessible rows."""
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    if user["role"] == "financial_advisor" and not _fa_can_access(review, user):
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    return review


@router.get("/reviews")
async def get_reviews(
    user: dict = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=_MAX_LIST_LIMIT),
    cursor: str | None = Query(default=None),
):
    if user["role"] == "financial_advisor":
        if not user["firm_id"]:
            return {"items": [], "next_cursor": None}
        summaries, next_cursor = await list_review_summaries(
            firm_id=user["firm_id"],
            uploader_role="financial_advisor",
            limit=limit,
            before_cursor=cursor,
        )
        return {"items": [_review_summary(r) for r in summaries], "next_cursor": next_cursor}

    summaries, next_cursor = await list_review_summaries(limit=limit, before_cursor=cursor)
    firm_rep_map = await _build_firm_bds_rep_map()
    uploader_map = await _build_uploader_name_map(summaries)
    tags = await list_tags()
    tag_map = {t["id"]: {"id": t["id"], "name": t["name"]} for t in tags}
    items = [_review_summary(r, firm_rep_map, uploader_map, tag_map) for r in summaries]
    return {"items": items, "next_cursor": next_cursor}


@router.get("/reviews/{review_id}")
async def get_review_by_id(review_id: str, user: dict = Depends(get_current_user)):
    review = await get_visible_review_or_404(review_id, user)
    return review


@router.patch("/reviews/{review_id}/outcome")
async def update_review_outcome_by_id(
    review_id: str,
    body: OutcomeBody,
    user: dict = Depends(get_current_user),
):
    review = await get_visible_review_or_404(review_id, user)
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

    category = next((c for c in categories if c.get("criterion_id") == body.criterion_id), None)
    if category is None:
        # legacy positional fallback for rows scored before criterion_id was stamped
        idx = framework_criteria.index(criterion)
        category = categories[idx] if idx < len(categories) else None
    if category is None:
        raise HTTPException(status_code=400, detail="Criterion not found in scored categories.")

    transcript = review.get("transcript") or []
    advisor_name = (review.get("metadata") or {}).get("advisor_name") or ""

    try:
        text = await run_in_threadpool(
            generate_major_focus, transcript, criterion, category, advisor_name
        )
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


@router.post("/reviews/{review_id}/coaching-email")
async def draft_coaching_email(
    review_id: str,
    user: dict = Depends(require_bds_rep),
):
    """Draft a coaching email (subject + body) for a completed review.

    Ephemeral: the draft is returned to the caller and not persisted. The coach's
    sign-off name comes from the authenticated profile, never from the client.
    """
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")

    if review.get("status") != "complete":
        raise HTTPException(status_code=400, detail="Review is not complete yet.")

    categories = (review.get("review") or {}).get("categories", [])
    if not categories:
        raise HTTPException(status_code=400, detail="Review has no scored categories.")

    sign_off_name = user.get("name") or ""

    try:
        email = await run_in_threadpool(generate_coaching_email, review, sign_off_name)
    except LLMUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Email drafting is unavailable: no AI provider is configured.",
        )
    except Exception as exc:
        logger.error("draft_coaching_email failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Couldn't draft the email. Please try again later.",
        )

    return email


@router.patch("/reviews/{review_id}/tags")
async def update_review_tags_by_id(
    review_id: str,
    body: TagIdsBody,
    user: dict = Depends(require_bds_rep),
):
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    await update_review_tags(review_id, body.tag_ids)
    return await get_review(review_id)


@router.patch("/reviews/{review_id}/notes")
async def update_review_notes_by_id(
    review_id: str,
    body: NotesBody,
    user: dict = Depends(require_bds_rep),
):
    review = await get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found.")
    await update_review_notes(review_id, body.notes or None)
    return await get_review(review_id)


@router.post("/reviews/{review_id}/chat", response_model=ChatResponse)
async def chat_about_review(
    review_id: str,
    body: ChatBody,
    user: dict = Depends(get_current_user),
):
    review = await get_visible_review_or_404(review_id, user)

    transcript = review.get("transcript") or []
    if not transcript:
        raise HTTPException(status_code=400, detail="This review has no transcript to chat about.")
    if not body.messages or body.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="Last message must be from the user.")

    try:
        answer = await run_in_threadpool(
            chat_about_transcript,
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

    # Batch-fetch all requested reviews in one DB round-trip, then filter
    # server-side: drop non-complete, FA-invisible, and scoreless rows.
    fetched = await get_reviews_by_ids(body.review_ids)
    scoped: list[dict] = []
    for review in fetched:
        if review.get("status") != "complete":
            continue
        if user["role"] == "financial_advisor" and not _fa_can_access(review, user):
            continue
        if not (review.get("review") or {}).get("categories"):
            continue
        scoped.append(review)

    if not scoped:
        return ChatResponse(
            answer="No completed calls match the current filters. Try broadening your search."
        )

    try:
        answer = await run_in_threadpool(
            chat_over_reviews, scoped, [m.model_dump() for m in body.messages]
        )
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
    review = await get_visible_review_or_404(review_id, user)
    if review.get("status") != "complete" or not (review.get("review") or {}).get("categories"):
        raise HTTPException(status_code=400, detail="Review is not finished yet.")
    pdf_bytes = await run_in_threadpool(render_review_pdf, review)
    filename = review_pdf_filename(review)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/reviews/{review_id}/retry")
async def retry_review_by_id(review_id: str, user: dict = Depends(get_current_user)):
    review = await get_visible_review_or_404(review_id, user)

    if review.get("status") != "failed":
        raise HTTPException(status_code=400, detail="Only failed reviews can be retried.")

    # Prefer the framework snapshot (now persisted at upload); fall back to the
    # standalone template_id column for legacy rows that predate the upload-time
    # framework save. Rows with neither predate retry support entirely.
    framework = review.get("framework") or {}
    template_id = framework.get("template_id") or review.get("template_id")
    if not template_id and not framework.get("criteria"):
        raise HTTPException(
            status_code=400,
            detail="This review predates retry support and can't be resubmitted. Please re-upload the call.",
        )

    # Write "pending" + clear prior error BEFORE enqueuing so the DB reflects the
    # new state even if the worker picks up the task before we finish writing.
    # Then enqueue. Then write celery_task_id with guard_pending so a fast-starting
    # worker can't have its "transcribing" status regressed back to "pending".
    try:
        await update_review_status(
            review_id, "pending", clear_error_message=True
        )
        task = process_review_task.delay(review_id, template_id)
    except Exception as exc:
        logger.error("Failed to enqueue retry for review %s: %s", review_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Couldn't queue the review for reprocessing. The task queue may be unavailable.",
        )
    try:
        await update_review_status(
            review_id, "pending", celery_task_id=task.id, guard_pending=True
        )
    except Exception as exc:
        logger.warning("Failed to record celery_task_id for retry %s: %s", review_id, exc)

    logger.info("Re-enqueued review %s for retry (template: %s)", review_id, template_id)
    return await get_review(review_id)


@router.delete("/reviews/{review_id}", status_code=204)
async def delete_review_by_id(review_id: str, user: dict = Depends(get_current_user)):
    review = await get_visible_review_or_404(review_id, user)
    await delete_review(review_id)
    if review.get("storage_path"):
        await delete_recording_from_storage(review["storage_path"])
    return Response(status_code=204)
