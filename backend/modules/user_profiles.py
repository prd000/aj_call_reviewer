import logging
from datetime import datetime, timezone

from modules.supabase_client import get_client

logger = logging.getLogger(__name__)


async def list_bds_reps() -> list[dict]:
    client = await get_client()
    result = await (
        client.table("profiles").select("*").eq("role", "bds_rep").order("name").execute()
    )
    return result.data


async def get_profile(user_id: str) -> dict | None:
    client = await get_client()
    result = await client.table("profiles").select("*").eq("id", user_id).execute()
    if not result.data:
        return None
    return result.data[0]


async def create_user(email: str, name: str, role: str, firm_id: str | None = None) -> dict:
    client = await get_client()
    existing = await client.table("profiles").select("id").eq("email", email).execute()
    if existing.data:
        raise ValueError(f"A user with email {email} is already registered.")

    now = datetime.now(timezone.utc).isoformat()
    user_resp = await client.auth.admin.invite_user_by_email(email)
    auth_user = user_resp.user
    if auth_user is None:
        raise ValueError("Failed to invite user — the email may already be in use.")
    user_id = str(auth_user.id)

    profile = {
        "id": user_id,
        "email": email,
        "name": name,
        "role": role,
        "firm_id": firm_id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await client.table("profiles").insert(profile).execute()
    return profile


async def update_profile(user_id: str, data: dict) -> dict | None:
    client = await get_client()
    now = datetime.now(timezone.utc).isoformat()
    patch = {k: v for k, v in data.items() if k in ("name", "firm_id")}
    patch["updated_at"] = now
    result = await (
        client.table("profiles").update(patch).eq("id", user_id).execute()
    )
    if not result.data:
        return None
    return result.data[0]


async def set_active(user_id: str, active: bool) -> None:
    client = await get_client()
    ban_duration = "none" if active else "876600h"
    await client.auth.admin.update_user_by_id(user_id, {"ban_duration": ban_duration})
    await client.table("profiles").update({
        "is_active": active,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", user_id).execute()


async def delete_user(user_id: str) -> None:
    # Idempotent: a missing auth user or missing profile is a success state
    # (post-condition: user does not exist). Delete auth first since it's the
    # source of truth — if it succeeds but the profile delete fails, the next
    # retry still converges.
    client = await get_client()
    try:
        await client.auth.admin.delete_user(user_id)
    except Exception as exc:
        msg = str(exc).lower()
        if "not found" not in msg and "user_not_found" not in msg:
            raise
        logger.info("Auth user %s already absent; continuing with profile delete", user_id)
    await client.table("profiles").delete().eq("id", user_id).execute()
