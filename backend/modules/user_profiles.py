import logging
import os
import secrets
from datetime import datetime, timezone
from uuid import uuid4

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
    app_url = os.environ.get("VITE_APP_URL", "").rstrip("/")
    invite_options = {"redirect_to": f"{app_url}/set-password"} if app_url else {}
    user_resp = await client.auth.admin.invite_user_by_email(email, invite_options)
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
        "has_set_password": False,
        "created_at": now,
        "updated_at": now,
    }
    await client.table("profiles").insert(profile).execute()
    return profile


async def create_advisor_only(name: str, firm_id: str) -> dict:
    client = await get_client()
    placeholder_email = f"advisor-{uuid4()}@noreply.internal"
    now = datetime.now(timezone.utc).isoformat()

    user_resp = await client.auth.admin.create_user({
        "email": placeholder_email,
        "password": secrets.token_urlsafe(32),
        "email_confirm": True,
    })
    user_id = str(user_resp.user.id)

    profile = {
        "id": user_id,
        "email": placeholder_email,
        "name": name,
        "role": "financial_advisor",
        "firm_id": firm_id,
        "is_active": True,
        "is_platform_user": False,
        "has_set_password": False,
        "created_at": now,
        "updated_at": now,
    }
    await client.table("profiles").insert(profile).execute()
    return profile


async def promote_advisor_to_user(user_id: str, email: str) -> dict:
    """Convert an advisor-only profile into a full platform user in place.

    Same auth `id` is preserved so historical reviews stay linked.
    """
    client = await get_client()

    profile = await get_profile(user_id)
    if profile is None:
        raise ValueError("User not found.")
    if profile.get("is_platform_user") is not False:
        raise ValueError("User is already a platform user.")

    existing = (
        await client.table("profiles")
        .select("id")
        .eq("email", email)
        .neq("id", user_id)
        .execute()
    )
    if existing.data:
        raise ValueError(f"A user with email {email} is already registered.")

    await client.auth.admin.update_user_by_id(
        user_id, {"email": email, "email_confirm": True}
    )

    app_url = os.environ.get("VITE_APP_URL", "").rstrip("/")
    redirect_to = f"{app_url}/set-password" if app_url else None
    try:
        link_options = {"redirect_to": redirect_to} if redirect_to else {}
        await client.auth.admin.generate_link({
            "type": "recovery",
            "email": email,
            "options": link_options,
        })
    except Exception as exc:
        logger.warning(
            "admin.generate_link failed for %s; falling back to reset_password_for_email: %s",
            user_id,
            exc,
        )
        reset_options = {"redirect_to": redirect_to} if redirect_to else {}
        await client.auth.reset_password_for_email(email, reset_options)

    now = datetime.now(timezone.utc).isoformat()
    result = await (
        client.table("profiles")
        .update({
            "email": email,
            "is_platform_user": True,
            "has_set_password": False,
            "updated_at": now,
        })
        .eq("id", user_id)
        .execute()
    )
    if not result.data:
        raise ValueError("Failed to update profile.")
    return result.data[0]


async def mark_password_set(user_id: str) -> dict | None:
    """Flip `has_set_password=True` after the user successfully chooses a password."""
    client = await get_client()
    now = datetime.now(timezone.utc).isoformat()
    result = await (
        client.table("profiles")
        .update({"has_set_password": True, "updated_at": now})
        .eq("id", user_id)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


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
