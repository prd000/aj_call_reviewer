import logging

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from modules.auth import get_current_user
from modules.firms import get_firm
from modules.ingestion import create_record, validate_file
from modules.storage import (
    delete_recording_from_storage,
    save_review,
    update_review_status,
    upload_recording_to_storage,
)
from modules.user_profiles import get_profile
from tasks import process_review_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload")
async def upload_call(
    prospect_name: str = Form(...),
    file: UploadFile = ...,
    firm_id: str = Form(None),
    advisor_user_id: str = Form(None),
    template_id: str = Form(None),
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
    )
    record["firm_id"] = effective_firm_id
    record["uploaded_by"] = user["user_id"]
    record["uploader_role"] = effective_uploader_role

    file_bytes = await file.read()

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

    try:
        task = process_review_task.delay(record["id"], effective_template_id)
        await update_review_status(record["id"], "pending", celery_task_id=task.id)
    except Exception as exc:
        logger.error("Failed to enqueue task for review %s: %s", record["id"], exc)
        await update_review_status(
            record["id"],
            "failed",
            error_message="Failed to queue processing task — Redis may be unavailable.",
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
