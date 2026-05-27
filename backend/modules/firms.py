import uuid
from datetime import datetime, timezone

from modules.supabase_client import get_client


async def list_firms() -> list[dict]:
    client = await get_client()
    result = await (
        client.table("firms").select("*, templates(name)").order("name").execute()
    )
    return result.data


async def get_firm(firm_id: str) -> dict | None:
    client = await get_client()
    result = await client.table("firms").select("*").eq("id", firm_id).execute()
    if not result.data:
        return None
    return result.data[0]


async def get_firm_users(firm_id: str) -> list[dict]:
    client = await get_client()
    result = await (
        client.table("profiles").select("*").eq("firm_id", firm_id).execute()
    )
    return result.data


async def save_firm(firm: dict) -> dict:
    client = await get_client()
    now = datetime.now(timezone.utc).isoformat()
    if not firm.get("id"):
        firm["id"] = str(uuid.uuid4())
    if "created_at" not in firm:
        firm["created_at"] = now
    firm["updated_at"] = now
    await client.table("firms").upsert(firm).execute()
    return firm


async def delete_firm(firm_id: str) -> None:
    client = await get_client()
    # Deactivate all FA profiles first; reviews stay permanently (firm_id SET NULL via FK)
    await client.table("profiles").update({"is_active": False}).eq(
        "firm_id", firm_id
    ).eq("role", "financial_advisor").execute()
    await client.table("firms").delete().eq("id", firm_id).execute()
