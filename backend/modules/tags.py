import uuid
from datetime import datetime, timezone

from modules.supabase_client import get_client


async def list_tags() -> list[dict]:
    """Return all tags ordered by name."""
    client = await get_client()
    result = await client.table("tags").select("*").order("name").execute()
    return result.data or []


async def create_tag(name: str) -> dict:
    """Return the tag with the given name, creating it if it doesn't exist.

    Deduplication is case-insensitive: 'Follow-up' and 'follow-up' return the same tag.
    """
    name = name.strip()
    client = await get_client()
    # ilike performs case-insensitive exact match (no wildcards).
    existing = await client.table("tags").select("*").ilike("name", name).execute()
    if existing.data:
        return existing.data[0]
    tag = {
        "id": str(uuid.uuid4()),
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await client.table("tags").insert(tag).execute()
    return tag
