from pathlib import Path
from modules.supabase_client import get_client

DATA_DIR = Path(__file__).parent.parent / "data"
RECORDINGS_DIR = DATA_DIR / "recordings"


def _ensure_recordings_dir() -> None:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def _to_row(review: dict) -> dict:
    metadata = review.get("metadata", {})
    return {
        "id": review["id"],
        "created_at": review["created_at"],
        "status": review.get("status", "pending"),
        "advisor_name": metadata.get("advisor_name"),
        "firm": metadata.get("firm"),
        "prospect_name": metadata.get("prospect_name"),
        "bds_rep": metadata.get("bds_rep"),
        "original_filename": metadata.get("original_filename"),
        "speaker_map": review.get("speaker_map"),
        "transcript": review.get("transcript"),
        "review_results": review.get("review"),
        "framework": review.get("framework"),
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
            "bds_rep": row.get("bds_rep"),
            "original_filename": row.get("original_filename"),
        },
        "speaker_map": row.get("speaker_map"),
        "transcript": row.get("transcript"),
        "review": row.get("review_results"),
        "framework": row.get("framework"),
    }


def save_review(review: dict) -> str:
    """Upsert a review record to Supabase. Returns the review id."""
    get_client().table("reviews").upsert(_to_row(review)).execute()
    return review["id"]


def get_review(review_id: str) -> dict | None:
    """Fetch a review record from Supabase by id. Returns None if not found."""
    result = get_client().table("reviews").select("*").eq("id", review_id).execute()
    if not result.data:
        return None
    return _from_row(result.data[0])


def list_reviews() -> list[dict]:
    """Fetch all review records from Supabase, sorted by created_at descending."""
    result = get_client().table("reviews").select("*").order("created_at", desc=True).execute()
    return [_from_row(row) for row in result.data]


def delete_review(review_id: str) -> None:
    """Delete a review record from Supabase. Raises FileNotFoundError if not found."""
    existing = get_client().table("reviews").select("id").eq("id", review_id).execute()
    if not existing.data:
        raise FileNotFoundError(f"Review '{review_id}' not found.")
    get_client().table("reviews").delete().eq("id", review_id).execute()


def save_recording(review_id: str, file_bytes: bytes, filename: str) -> Path:
    """Save a raw recording file to disk temporarily (for transcription). Returns the saved path."""
    _ensure_recordings_dir()
    safe_filename = Path(filename).name
    recording_path = RECORDINGS_DIR / f"{review_id}_{safe_filename}"
    recording_path.write_bytes(file_bytes)
    return recording_path


def delete_recording(review_id: str, original_filename: str) -> bool:
    """Delete the temporary recording file from disk. Returns True if deleted, False if not found."""
    safe_filename = Path(original_filename).name
    recording_path = RECORDINGS_DIR / f"{review_id}_{safe_filename}"
    if recording_path.exists():
        recording_path.unlink()
        return True
    return False
