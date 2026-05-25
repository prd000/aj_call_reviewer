import logging
from fastapi import APIRouter, Form, HTTPException, UploadFile

from modules.ingestion import create_record, validate_file
from modules.storage import delete_recording_from_storage, save_review, upload_recording_to_storage
from tasks import process_review_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload")
async def upload_call(
    advisor_name: str = Form(...),
    firm: str = Form(...),
    prospect_name: str = Form(...),
    bds_rep: str = Form(""),
    template_id: str = Form(...),
    file: UploadFile = ...,
):
    if not validate_file(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: '{file.filename}'. "
                "Accepted formats are .mp3, .mp4, .m4a, and .wav."
            ),
        )

    record = create_record(
        advisor_name=advisor_name.strip(),
        firm=firm.strip(),
        prospect_name=prospect_name.strip(),
        bds_rep=bds_rep.strip(),
        original_filename=file.filename or "recording",
    )

    file_bytes = await file.read()

    try:
        storage_path = upload_recording_to_storage(
            record["id"], file_bytes, file.filename or "recording"
        )
    except Exception as exc:
        logger.error("Failed to upload recording to storage for review %s: %s", record["id"], exc)
        raise HTTPException(status_code=500, detail="Failed to upload recording file.")

    record["storage_path"] = storage_path

    try:
        save_review(record)
    except Exception as exc:
        logger.error("Failed to save review record %s: %s", record["id"], exc)
        delete_recording_from_storage(storage_path)
        raise HTTPException(status_code=500, detail="Failed to save review record.")

    task = process_review_task.delay(record["id"], template_id)
    storage.update_review_status(record["id"], "pending", celery_task_id=task.id)

    logger.info(
        "Enqueued review %s (advisor: %s, firm: %s, prospect: %s, bds_rep: %s, template_id: %s)",
        record["id"],
        advisor_name,
        firm,
        prospect_name,
        bds_rep,
        template_id,
    )

    return {"id": record["id"], "status": "pending"}
