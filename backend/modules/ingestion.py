import uuid
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_EXTENSIONS = {".mp3", ".mp4", ".m4a", ".wav"}


def validate_file(filename: str) -> bool:
    """Return True if the file extension is in the allowed set."""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


def create_record(
    advisor_name: str,
    firm: str,
    prospect_name: str,
    original_filename: str,
    bds_rep: str = "",
) -> dict:
    """
    Create a new review record with a unique id and ISO 8601 timestamp.
    Returns a dict matching the storage schema with empty transcript and review.
    """
    return {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "metadata": {
            "advisor_name": advisor_name,
            "firm": firm,
            "prospect_name": prospect_name,
            "bds_rep": bds_rep,
            "original_filename": original_filename,
        },
        "transcript": [],
        "review": {},
    }
