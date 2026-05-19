import logging
from fastapi import APIRouter, Form, HTTPException, UploadFile

from modules.ingestion import create_record, validate_file
from modules.storage import save_recording, save_review

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload")
async def upload_call(
    advisor_name: str = Form(...),
    firm: str = Form(...),
    prospect_name: str = Form(...),
    bds_rep: str = Form(""),
    file: UploadFile = ...,
):
    """
    Accept a call recording with metadata.

    Validates the file extension, creates a pending review record,
    saves both the file and the record to disk, and returns the record id.
    """
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
        save_recording(record["id"], file_bytes, file.filename or "recording")
    except OSError as exc:
        logger.error("Failed to save recording for review %s: %s", record["id"], exc)
        raise HTTPException(status_code=500, detail="Failed to save recording file.")

    try:
        save_review(record)
    except OSError as exc:
        logger.error("Failed to save review record %s: %s", record["id"], exc)
        raise HTTPException(status_code=500, detail="Failed to save review record.")

    logger.info(
        "Uploaded recording for review %s (advisor: %s, firm: %s, prospect: %s, bds_rep: %s)",
        record["id"],
        advisor_name,
        firm,
        prospect_name,
        bds_rep,
    )

    return {"id": record["id"], "status": record["status"]}
