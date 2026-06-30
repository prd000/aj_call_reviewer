import logging
import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel

from modules.auth import get_current_user
from modules.firms import get_firm
from modules.ingestion import CALL_OUTCOMES, create_record, validate_file
from modules.templates import get_template
from modules.storage import (
    create_recording_upload_url,
    delete_recording_from_storage,
    recording_exists,
    save_review,
    update_review_status,
    upload_recording_to_storage,
)
from modules.user_profiles import get_profile
from tasks import process_review_task

logger = logging.getLogger(__name__)

# Default 200 MB; override via MAX_UPLOAD_SIZE_BYTES env var.
_MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(200 * 1024 * 1024)))

# Pre-signed uploads land in this namespace; the path shape is validated before
# we trust a client-supplied storage_path in /upload-from-storage.
_STAGED_PREFIX = "staged"
_STAGED_PATH_RE = re.compile(r"^staged/[0-9a-f-]{36}/recording\.[a-z0-9]+$")

router = APIRouter()


def _reject_bad_file_type(filename: str | None) -> None:
    if not validate_file(filename or ""):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: '{filename}'. "
                "Accepted formats are .mp3, .mp4, .m4a, and .wav."
            ),
        )


async def _resolve_upload_record(
    user: dict,
    prospect_name: str,
    firm_id: str | None,
    advisor_user_id: str | None,
    template_id: str | None,
    call_outcome: str | None,
    original_filename: str,
) -> tuple[dict, str]:
    """Validate inputs + resolve role/firm/advisor/template into a review record.

    Shared by the multipart `/upload` and the pre-signed `/upload-from-storage`
    paths. Returns `(record, effective_template_id)`; the caller sets
    `record["storage_path"]` then calls `_save_and_enqueue`. Raises HTTPException
    (400) on any validation failure — and never enqueues anything.
    """
    _reject_bad_file_type(original_filename)

    # Form fields can't use a Pydantic Literal directly, so validate manually.
    if call_outcome is not None and call_outcome not in CALL_OUTCOMES:
        raise HTTPException(status_code=400, detail="Invalid call outcome.")

    if user["role"] == "financial_advisor":
        fa_firm_id = user["firm_id"]
        if not fa_firm_id:
            raise HTTPException(
                status_code=400, detail="Your account is not associated with a firm."
            )
        firm = await get_firm(fa_firm_id)
        if firm is None:
            raise HTTPException(status_code=400, detail="Firm not found.")
        effective_template_id = firm.get("template_id")
        if not effective_template_id:
            raise HTTPException(
                status_code=400,
                detail="Your firm does not have a review template assigned. Contact your BDS rep.",
            )
        effective_firm_id = fa_firm_id
        effective_firm_name = firm["name"]
        effective_advisor_name = user["name"]
        effective_uploader_role = "financial_advisor"
    else:
        if not firm_id:
            raise HTTPException(status_code=400, detail="firm_id is required.")
        if not advisor_user_id:
            raise HTTPException(status_code=400, detail="advisor_user_id is required.")
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required.")

        firm = await get_firm(firm_id)
        if firm is None:
            raise HTTPException(status_code=400, detail="Firm not found.")
        advisor = await get_profile(advisor_user_id)
        if advisor is None:
            raise HTTPException(status_code=400, detail="Advisor not found.")
        if advisor.get("firm_id") != firm_id:
            raise HTTPException(
                status_code=400,
                detail="Advisor does not belong to the selected firm.",
            )

        effective_firm_id = firm_id
        effective_firm_name = firm["name"]
        effective_template_id = template_id
        effective_advisor_name = advisor["name"]
        effective_uploader_role = "bds_rep"

    record = create_record(
        advisor_name=effective_advisor_name,
        firm=effective_firm_name,
        prospect_name=prospect_name.strip(),
        original_filename=original_filename or "recording",
        call_outcome=call_outcome,
    )
    record["firm_id"] = effective_firm_id
    record["uploaded_by"] = user["user_id"]
    record["uploader_role"] = effective_uploader_role

    # Build and persist the full framework snapshot at upload time so every review
    # carries its criteria from the start — even failed/in-progress rows. This makes
    # `framework` the single source of truth; the standalone `template_id` column is
    # no longer populated for new rows (kept nullable for legacy backward-compat).
    template = await get_template(effective_template_id)
    if template is None:
        raise HTTPException(status_code=400, detail="Review template not found.")
    record["framework"] = {
        "template_name": template.get("name", ""),
        "template_id": effective_template_id,
        "criteria": template.get("criteria", []),
    }

    return record, effective_template_id


async def _save_and_enqueue(record: dict, effective_template_id: str) -> dict:
    """Persist the review (with `storage_path` set) and enqueue processing.

    On save failure the recording is deleted (orphan cleanup) and 500 is raised.
    An enqueue failure is non-fatal: the review is marked `failed` and returned,
    so the row exists and is retryable. Shared by both upload entry points.
    """
    try:
        await save_review(record)
    except Exception as exc:
        logger.error("Failed to save review record %s: %s", record["id"], exc)
        await delete_recording_from_storage(record["storage_path"])
        raise HTTPException(status_code=500, detail="Failed to save review record.")

    # Status is already "pending" from save_review. Enqueue first; write
    # celery_task_id after. guard_pending ensures a fast-starting worker that
    # has already advanced status won't be regressed back to "pending".
    try:
        task = process_review_task.delay(record["id"], effective_template_id)
    except Exception as exc:
        logger.error("Failed to enqueue task for review %s: %s", record["id"], exc)
        await update_review_status(
            record["id"],
            "failed",
            error_message="Failed to queue processing task — Redis may be unavailable.",
        )
    else:
        await update_review_status(
            record["id"], "pending", celery_task_id=task.id, guard_pending=True
        )

    logger.info(
        "Enqueued review %s (firm: %s, role: %s, template: %s)",
        record["id"],
        record.get("firm_id"),
        record.get("uploader_role"),
        effective_template_id,
    )

    return {"id": record["id"], "status": "pending"}


@router.post("/upload")
async def upload_call(
    prospect_name: str = Form(...),
    file: UploadFile = ...,
    firm_id: str = Form(None),
    advisor_user_id: str = Form(None),
    template_id: str = Form(None),
    call_outcome: str = Form(None),
    user: dict = Depends(get_current_user),
):
    record, effective_template_id = await _resolve_upload_record(
        user, prospect_name, firm_id, advisor_user_id, template_id, call_outcome,
        file.filename or "",
    )

    # Read with a size cap to avoid loading arbitrarily large files into memory.
    # Read one byte past the limit so we can detect an oversize file before
    # attempting to upload it to storage.
    file_bytes = await file.read(_MAX_UPLOAD_SIZE_BYTES + 1)
    if len(file_bytes) > _MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File exceeds the maximum upload size of "
                f"{_MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB."
            ),
        )

    try:
        storage_path = await upload_recording_to_storage(
            record["id"], file_bytes, file.filename or "recording"
        )
    except Exception as exc:
        logger.error(
            "Failed to upload recording to storage for review %s: %s", record["id"], exc
        )
        raise HTTPException(status_code=500, detail="Failed to upload recording file.")

    record["storage_path"] = storage_path
    return await _save_and_enqueue(record, effective_template_id)


class PresignBody(BaseModel):
    filename: str


@router.post("/uploads/presign")
async def presign_upload(body: PresignBody, user: dict = Depends(get_current_user)):
    """Return a pre-signed Supabase Storage upload URL for a recording.

    Lets a client (e.g. the MCP server) PUT a large file straight to Supabase,
    then call `/upload-from-storage` with the returned `storage_path`. The bytes
    never pass through this API.
    """
    _reject_bad_file_type(body.filename)
    ext = Path(body.filename).suffix.lower()
    storage_path = f"{_STAGED_PREFIX}/{uuid4()}/recording{ext}"
    try:
        return await create_recording_upload_url(storage_path)
    except Exception as exc:
        logger.error("Failed to create signed upload URL: %s", exc)
        raise HTTPException(status_code=502, detail="Could not create an upload URL.")


class UploadFromStorageBody(BaseModel):
    storage_path: str
    filename: str
    prospect_name: str
    firm_id: str | None = None
    advisor_user_id: str | None = None
    template_id: str | None = None
    call_outcome: str | None = None


@router.post("/upload-from-storage")
async def upload_from_storage(
    body: UploadFromStorageBody, user: dict = Depends(get_current_user)
):
    """Create a review from a recording already uploaded via `/uploads/presign`.

    Mirrors `/upload` but the file is fetched-from-storage rather than streamed
    through the request — the path for MCP/large-file clients.
    """
    if not _STAGED_PATH_RE.match(body.storage_path):
        raise HTTPException(status_code=400, detail="Invalid storage path.")
    if not await recording_exists(body.storage_path):
        raise HTTPException(
            status_code=400,
            detail="Uploaded recording not found in storage. Request a new upload URL and retry.",
        )

    record, effective_template_id = await _resolve_upload_record(
        user, body.prospect_name, body.firm_id, body.advisor_user_id, body.template_id,
        body.call_outcome, body.filename,
    )
    record["storage_path"] = body.storage_path
    return await _save_and_enqueue(record, effective_template_id)
