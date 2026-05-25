import logging
from datetime import datetime, timezone

from modules.supabase_client import get_client

logger = logging.getLogger(__name__)


def list_bds_reps() -> list[dict]:
    result = (
        get_client().table("profiles").select("*").eq("role", "bds_rep").order("name").execute()
    )
    return result.data


def get_profile(user_id: str) -> dict | None:
    result = get_client().table("profiles").select("*").eq("id", user_id).execute()
    if not result.data:
        return None
    return result.data[0]


def create_user(email: str, name: str, role: str, firm_id: str | None = None) -> dict:
    existing = get_client().table("profiles").select("id").eq("email", email).execute()
    if existing.data:
        raise ValueError(f"A user with email {email} is already registered.")

    now = datetime.now(timezone.utc).isoformat()
    user_resp = get_client().auth.admin.invite_user_by_email(email)
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
    get_client().table("profiles").insert(profile).execute()
    return profile


def update_profile(user_id: str, data: dict) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    patch = {k: v for k, v in data.items() if k in ("name", "firm_id")}
    patch["updated_at"] = now
    result = (
        get_client().table("profiles").update(patch).eq("id", user_id).execute()
    )
    if not result.data:
        return None
    return result.data[0]


def set_active(user_id: str, active: bool) -> None:
    ban_duration = "none" if active else "876600h"
    get_client().auth.admin.update_user_by_id(user_id, {"ban_duration": ban_duration})
    get_client().table("profiles").update({
        "is_active": active,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", user_id).execute()


def delete_user(user_id: str) -> None:
    # Delete profile first, then auth user
    get_client().table("profiles").delete().eq("id", user_id).execute()
    get_client().auth.admin.delete_user(user_id)
