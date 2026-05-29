import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, get_args

ALLOWED_EXTENSIONS = {".mp3", ".mp4", ".m4a", ".wav"}

# Canonical call-outcome labels, in pipeline-lifecycle order. The exact strings
# (including their inconsistent casing) are the single source of truth shared by
# the validation layer and the frontend. No DB CHECK constraint depends on these,
# so relabeling here needs no migration.
CALL_OUTCOMES: list[str] = [
    "Lost after first call",
    "No follow-up booked",
    "Follow-up Booked",
    "Lost after follow-up",
    "Closed",
]

# Pydantic-reusable type alias mirroring CALL_OUTCOMES. The assert keeps the two
# in sync at import time so they can never silently drift.
CallOutcome = Literal[
    "Lost after first call",
    "No follow-up booked",
    "Follow-up Booked",
    "Lost after follow-up",
    "Closed",
]
assert set(CALL_OUTCOMES) == set(get_args(CallOutcome)), (
    "CALL_OUTCOMES and CallOutcome must stay in sync"
)


def validate_file(filename: str) -> bool:
    """Return True if the file extension is in the allowed set."""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


def create_record(
    advisor_name: str,
    firm: str,
    prospect_name: str,
    original_filename: str,
    call_outcome: str | None = None,
) -> dict:
    """
    Create a new review record with a unique id and ISO 8601 timestamp.
    Returns a dict matching the storage schema with empty transcript and review.
    auth fields (firm_id, uploaded_by, uploader_role) are added by the upload router.
    call_outcome is optional metadata (None = no outcome set).
    """
    return {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "metadata": {
            "advisor_name": advisor_name,
            "firm": firm,
            "prospect_name": prospect_name,
            "original_filename": original_filename,
            "call_outcome": call_outcome,
        },
        "transcript": [],
        "review": {},
    }
