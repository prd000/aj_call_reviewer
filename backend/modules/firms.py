import uuid
from datetime import datetime, timezone

from modules.supabase_client import get_client


def list_firms() -> list[dict]:
    result = (
        get_client().table("firms").select("*, templates(name)").order("name").execute()
    )
    return result.data


def get_firm(firm_id: str) -> dict | None:
    result = get_client().table("firms").select("*").eq("id", firm_id).execute()
    if not result.data:
        return None
    return result.data[0]


def get_firm_users(firm_id: str) -> list[dict]:
    result = (
        get_client().table("profiles").select("*").eq("firm_id", firm_id).execute()
    )
    return result.data


def save_firm(firm: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    if not firm.get("id"):
        firm["id"] = str(uuid.uuid4())
    if "created_at" not in firm:
        firm["created_at"] = now
    firm["updated_at"] = now
    get_client().table("firms").upsert(firm).execute()
    return firm


def delete_firm(firm_id: str) -> None:
    # Deactivate all FA profiles first; reviews stay permanently (firm_id SET NULL via FK)
    get_client().table("profiles").update({"is_active": False}).eq(
        "firm_id", firm_id
    ).eq("role", "financial_advisor").execute()
    get_client().table("firms").delete().eq("id", firm_id).execute()
