import base64
import json as _json
from pathlib import Path

from modules.scoring import overall_score as _compute_overall_score
from modules.supabase_client import get_client

STORAGE_BUCKET = "recordings"

# Columns selected for the narrow summary list query (no heavy jsonb payloads).
_SUMMARY_COLUMNS = (
    "id, status, created_at, advisor_name, firm, prospect_name, original_filename, "
    "call_outcome, firm_id, uploaded_by, uploader_role, "
    "overall_score, overall_max_score, template_name, tag_ids"
)

# Columns selected for the history-chat batch fetch (transcript needed for tools;
# skips notes, major_focus, framework, storage_path, celery_task_id).
_CHAT_COLUMNS = (
    "id, created_at, status, firm_id, uploader_role, "
    "review_results, transcript, speaker_map, advisor_name, firm"
)


def _to_row(review: dict) -> dict:
    metadata = review.get("metadata", {})
    score, max_score = _compute_overall_score(review.get("review"))
    template_name = (review.get("framework") or {}).get("template_name")
    return {
        "id": review["id"],
        "created_at": review["created_at"],
        "status": review.get("status", "pending"),
        "advisor_name": metadata.get("advisor_name"),
        "firm": metadata.get("firm"),
        "prospect_name": metadata.get("prospect_name"),
        "original_filename": metadata.get("original_filename"),
        "call_outcome": metadata.get("call_outcome"),
        "speaker_map": review.get("speaker_map"),
        "transcript": review.get("transcript"),
        "review_results": review.get("review"),
        "framework": review.get("framework"),
        "error_message": review.get("error_message"),
        "storage_path": review.get("storage_path"),
        "celery_task_id": review.get("celery_task_id"),
        "firm_id": review.get("firm_id"),
        "uploaded_by": review.get("uploaded_by"),
        "uploader_role": review.get("uploader_role"),
        "major_focus": review.get("major_focus"),
        "template_id": review.get("template_id"),
        "tag_ids": review.get("tag_ids", []),
        "notes": review.get("notes"),
        "overall_score": score,
        "overall_max_score": max_score,
        "template_name": template_name,
    }


def _from_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "metadata": {
            "advisor_name": row.get("advisor_name"),
            "firm": row.get("firm"),
            "prospect_name": row.get("prospect_name"),
            "original_filename": row.get("original_filename"),
            "call_outcome": row.get("call_outcome"),
        },
        "speaker_map": row.get("speaker_map"),
        "transcript": row.get("transcript"),
        "review": row.get("review_results"),
        "framework": row.get("framework"),
        "error_message": row.get("error_message"),
        "storage_path": row.get("storage_path"),
        "celery_task_id": row.get("celery_task_id"),
        "firm_id": row.get("firm_id"),
        "uploaded_by": row.get("uploaded_by"),
        "uploader_role": row.get("uploader_role"),
        "major_focus": row.get("major_focus"),
        "template_id": row.get("template_id"),
        "tag_ids": row.get("tag_ids") or [],
        "notes": row.get("notes"),
        # Precomputed summary columns (populated by _to_row on every write).
        "overall_score": row.get("overall_score"),
        "overall_max_score": row.get("overall_max_score"),
        "template_name": row.get("template_name"),
    }


def _from_summary_row(row: dict) -> dict:
    """Map a narrow summary-query row to the shape _review_summary expects."""
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "metadata": {
            "advisor_name": row.get("advisor_name"),
            "firm": row.get("firm"),
            "prospect_name": row.get("prospect_name"),
            "original_filename": row.get("original_filename"),
            "call_outcome": row.get("call_outcome"),
        },
        "firm_id": row.get("firm_id"),
        "uploaded_by": row.get("uploaded_by"),
        "uploader_role": row.get("uploader_role"),
        "tag_ids": row.get("tag_ids") or [],
        "overall_score": row.get("overall_score"),
        "overall_max_score": row.get("overall_max_score"),
        "template_name": row.get("template_name"),
    }


def _encode_cursor(created_at: str, row_id: str) -> str:
    return base64.urlsafe_b64encode(
        _json.dumps({"c": created_at, "i": row_id}).encode()
    ).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    data = _json.loads(base64.urlsafe_b64decode(cursor))
    return data["c"], data["i"]


async def save_review(review: dict) -> str:
    """Upsert a review record to Supabase. Returns the review id."""
    client = await get_client()
    await client.table("reviews").upsert(_to_row(review)).execute()
    return review["id"]


async def get_review(review_id: str) -> dict | None:
    """Fetch a review record from Supabase by id. Returns None if not found."""
    client = await get_client()
    result = await client.table("reviews").select("*").eq("id", review_id).execute()
    if not result.data:
        return None
    return _from_row(result.data[0])


IN_PROGRESS_STATUSES = ("pending", "transcribing", "reviewing")


async def list_stuck_reviews(
    cutoff_iso: str,
    statuses: tuple = IN_PROGRESS_STATUSES,
) -> list[dict]:
    """Return in-progress reviews that haven't been updated since cutoff_iso.

    Queries only rows with in-progress statuses and a stale updated_at — never
    scans completed reviews or fetches transcript/review_results payloads.
    """
    client = await get_client()
    result = (
        await client.table("reviews")
        .select("id, status, storage_path, created_at, updated_at")
        .in_("status", list(statuses))
        .lt("updated_at", cutoff_iso)
        .execute()
    )
    return result.data or []


async def list_reviews(
    firm_id: str | None = None,
    uploader_role: str | None = None,
) -> list[dict]:
    """Fetch full review records from Supabase, sorted by created_at descending.

    Selects all columns including heavy jsonb payloads. Use
    list_review_summaries() for the History list endpoint — it fetches only
    summary columns and supports keyset pagination.
    """
    client = await get_client()
    query = client.table("reviews").select("*").order("created_at", desc=True)
    if firm_id is not None:
        query = query.eq("firm_id", firm_id)
    if uploader_role is not None:
        query = query.eq("uploader_role", uploader_role)
    result = await query.execute()
    return [_from_row(row) for row in result.data]


async def list_review_summaries(
    firm_id: str | None = None,
    uploader_role: str | None = None,
    limit: int = 50,
    before_cursor: str | None = None,
) -> tuple[list[dict], str | None]:
    """Return paginated review summaries without heavy jsonb payloads.

    Selects only scalar/summary columns — no transcript, review_results,
    speaker_map, or framework. Uses keyset pagination on (created_at DESC,
    id DESC).

    Returns (rows, next_cursor) where next_cursor is None when no more pages
    exist. Callers should pass next_cursor back as before_cursor to fetch the
    next page.
    """
    client = await get_client()
    fetch_limit = limit + 1  # one extra to detect has_more
    query = (
        client.table("reviews")
        .select(_SUMMARY_COLUMNS)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .limit(fetch_limit)
    )
    if firm_id is not None:
        query = query.eq("firm_id", firm_id)
    if uploader_role is not None:
        query = query.eq("uploader_role", uploader_role)
    if before_cursor:
        ca, rid = _decode_cursor(before_cursor)
        # Rows that come after the cursor in DESC order:
        # (created_at < ca) OR (created_at = ca AND id < rid)
        query = query.or_(
            f"created_at.lt.{ca},and(created_at.eq.{ca},id.lt.{rid})"
        )
    result = await query.execute()
    rows = result.data or []

    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor: str | None = _encode_cursor(last["created_at"], last["id"])
    else:
        next_cursor = None

    return [_from_summary_row(r) for r in rows], next_cursor


async def get_reviews_by_ids(ids: list[str]) -> list[dict]:
    """Batch-fetch reviews by id list, selecting only history-chat columns.

    Returns dicts in the same shape as get_review() for the subset of fields
    needed by the history-chat path (transcript, review_results, metadata).
    Order is not guaranteed to match ids.
    """
    if not ids:
        return []
    client = await get_client()
    result = (
        await client.table("reviews")
        .select(_CHAT_COLUMNS)
        .in_("id", ids)
        .execute()
    )
    return [
        {
            "id": r["id"],
            "created_at": r["created_at"],
            "status": r["status"],
            "firm_id": r.get("firm_id"),
            "uploader_role": r.get("uploader_role"),
            "review": r.get("review_results"),
            "transcript": r.get("transcript"),
            "speaker_map": r.get("speaker_map"),
            "metadata": {
                "advisor_name": r.get("advisor_name"),
                "firm": r.get("firm"),
            },
        }
        for r in (result.data or [])
    ]


async def delete_review(review_id: str) -> None:
    """Delete a review record from Supabase. Raises FileNotFoundError if not found."""
    client = await get_client()
    existing = await client.table("reviews").select("id").eq("id", review_id).execute()
    if not existing.data:
        raise FileNotFoundError(f"Review '{review_id}' not found.")
    await client.table("reviews").delete().eq("id", review_id).execute()


async def update_review_status(
    review_id: str,
    status: str,
    *,
    error_message: str | None = None,
    celery_task_id: str | None = None,
    guard_terminal: bool = False,
    clear_error_message: bool = False,
) -> None:
    """Partial update of a review's status and optional fields.

    When ``guard_terminal`` is True the write becomes a no-op for rows already in
    the terminal ``"complete"`` state (via a ``status != "complete"`` filter),
    preventing a stray retry/redelivery from regressing a finished review back to
    ``"transcribing"``/``"reviewing"``. Default False preserves unconditional
    writes for callers that must always apply — the ``"failed"`` cleanup write
    (tasks.py) and the initial ``"pending"`` write (upload.py).

    Pass ``clear_error_message=True`` to reset ``error_message`` back to NULL (used
    by the Retry endpoint when re-queuing a previously-failed review). An explicit
    ``error_message`` takes precedence over the clear.
    """
    client = await get_client()
    patch: dict = {"status": status}
    if error_message is not None:
        patch["error_message"] = error_message
    elif clear_error_message:
        patch["error_message"] = None
    if celery_task_id is not None:
        patch["celery_task_id"] = celery_task_id
    query = client.table("reviews").update(patch).eq("id", review_id)
    if guard_terminal:
        query = query.neq("status", "complete")
    await query.execute()


async def update_review_transcript(
    review_id: str,
    transcript: list[dict],
    speaker_map: dict,
) -> None:
    """Persist just the transcript + speaker_map as a mid-pipeline checkpoint.

    Written immediately after transcription succeeds (and BEFORE the status flips
    to ``"reviewing"``) so a retry that later fails during the review phase can
    resume from this persisted transcript instead of re-submitting a new Rev.ai
    job. Writes only these two columns; never touches status.
    """
    client = await get_client()
    patch = {"transcript": transcript, "speaker_map": speaker_map}
    await client.table("reviews").update(patch).eq("id", review_id).execute()


async def update_review_major_focus(review_id: str, major_focus: dict | None) -> None:
    """Partial update of a review's major focus block.

    Always writes the key so passing None clears back to NULL.
    """
    client = await get_client()
    patch = {"major_focus": major_focus}
    await client.table("reviews").update(patch).eq("id", review_id).execute()


async def update_review_outcome(review_id: str, call_outcome: str | None) -> None:
    """Partial update of a review's call outcome.

    Always writes the key (unlike update_review_status's conditional adds) so that
    passing None clears the column back to NULL ("no outcome set").
    """
    client = await get_client()
    patch = {"call_outcome": call_outcome}
    await client.table("reviews").update(patch).eq("id", review_id).execute()


async def upload_recording_to_storage(review_id: str, file_bytes: bytes, filename: str) -> str:
    """Upload a recording to Supabase Storage. Returns the storage path."""
    client = await get_client()
    safe_name = Path(filename).name
    path = f"{review_id}/{safe_name}"
    await client.storage.from_(STORAGE_BUCKET).upload(path=path, file=file_bytes)
    return path


async def get_recording_signed_url(storage_path: str) -> str:
    """Return a signed URL for the recording, valid for 1 hour."""
    client = await get_client()
    result = await client.storage.from_(STORAGE_BUCKET).create_signed_url(
        path=storage_path,
        expires_in=3600,
    )
    if isinstance(result, dict):
        return result.get("signedURL") or result.get("signedUrl", "")
    return str(getattr(result, "signed_url", "") or getattr(result, "signedURL", ""))


async def delete_recording_from_storage(storage_path: str) -> None:
    """Delete a recording from Supabase Storage. Silent if not found."""
    try:
        client = await get_client()
        await client.storage.from_(STORAGE_BUCKET).remove([storage_path])
    except Exception:
        pass


async def update_review_tags(review_id: str, tag_ids: list[str]) -> None:
    """Replace the tag_ids array on a review."""
    client = await get_client()
    await client.table("reviews").update({"tag_ids": tag_ids}).eq("id", review_id).execute()


async def update_review_notes(review_id: str, notes: str | None) -> None:
    """Set or clear the internal notes on a review.

    Always writes the key so passing None clears back to NULL.
    """
    client = await get_client()
    await client.table("reviews").update({"notes": notes}).eq("id", review_id).execute()
