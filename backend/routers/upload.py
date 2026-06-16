import logging
import os

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from modules.auth import get_current_user
from modules.firms import get_firm
from modules.ingestion import CALL_OUTCOMES, create_record, validate_file
from modules.templates import get_template
from modules.storage import (
    delete_recording_from_storage,
    save_review,
    update_review_status,
    upload_recording_to_storage,
)
from modules.user_profiles import get_profile
from tasks import process_review_task

logger = logging.getLogger(__name__)

# Default 200 MB; override via MAX_UPLOAD_SIZE_BYTES env var.
_MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(200 * 1024 * 1024)))

router = APIRouter()


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
    if not validate_file(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: '{file.filename}'. "
                "Accepted formats are .mp3, .mp4, .m4a, and .wav."
            ),
        )

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
        original_filename=file.filename or "recording",
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

    try:
        await save_review(record)
    except Exception as exc:
        logger.error("Failed to save review record %s: %s", record["id"], exc)
        await delete_recording_from_storage(storage_path)
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
        "Enqueued review %s (advisor: %s, firm: %s, prospect: %s, role: %s, template: %s)",
        record["id"],
        effective_advisor_name,
        effective_firm_name,
        prospect_name,
        effective_uploader_role,
        effective_template_id,
    )

    return {"id": record["id"], "status": "pending"}
