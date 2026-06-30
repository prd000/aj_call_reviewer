"""API-key issuance and verification.

A key is a high-entropy bearer secret (`ak_live_<token>`) that links to a profile.
At verification time the linked profile is loaded (by auth.py) so the key inherits
that profile's role — a BDS rep's key can upload + draft emails, an FA's key stays
FA-scoped. Only the sha256 hash of the secret is stored; the raw key is returned to
the caller exactly once at creation and is never recoverable afterward.
"""
import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4

from modules.supabase_client import get_client

logger = logging.getLogger(__name__)

# Tag prefix that lets the auth layer cheaply tell an API key from a JWT.
KEY_TAG = "ak_live_"
# Leading chars stored/displayed so a user can recognise a key without the secret.
_PREFIX_DISPLAY_LEN = 16

# last_used_at is informational; throttle writes so a 5s poll loop doesn't hammer
# the DB. Per-process map of key_id -> monotonic timestamp of last write.
_LAST_USED_THROTTLE_SECONDS = 60.0
_last_used_writes: dict[str, float] = {}


def hash_key(full_key: str) -> str:
    """Deterministic sha256 hex of the full key (indexed-equality lookup)."""
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, key_prefix, key_hash). The full_key is shown to the user once."""
    full_key = KEY_TAG + secrets.token_urlsafe(32)
    return full_key, full_key[:_PREFIX_DISPLAY_LEN], hash_key(full_key)


def _public_row(row: dict) -> dict:
    """Strip the hash; keys metadata is safe to return, the secret/hash never is."""
    return {
        "id": row["id"],
        "label": row["label"],
        "key_prefix": row["key_prefix"],
        "created_at": row.get("created_at"),
        "last_used_at": row.get("last_used_at"),
        "revoked_at": row.get("revoked_at"),
    }


async def create_api_key(user_id: str, label: str) -> dict:
    """Create a key for ``user_id``. Returns metadata PLUS ``full_key`` (shown once)."""
    full_key, key_prefix, key_hash = generate_api_key()
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "label": (label or "").strip() or "API key",
        "key_prefix": key_prefix,
        "key_hash": key_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    client = await get_client()
    await client.table("api_keys").insert(row).execute()
    return {**_public_row(row), "full_key": full_key}


async def list_api_keys(user_id: str) -> list[dict]:
    """Return the caller's keys (metadata only — never the hash), newest first."""
    client = await get_client()
    result = await (
        client.table("api_keys")
        .select("id, label, key_prefix, created_at, last_used_at, revoked_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [_public_row(r) for r in (result.data or [])]


async def revoke_api_key(key_id: str, user_id: str) -> bool:
    """Revoke a key the caller owns. Returns True if an active key was revoked."""
    client = await get_client()
    result = await (
        client.table("api_keys")
        .update({"revoked_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", key_id)
        .eq("user_id", user_id)
        .is_("revoked_at", "null")
        .execute()
    )
    return bool(result.data)


async def resolve_api_key(full_key: str) -> dict | None:
    """Return ``{user_id, key_id}`` for an active (non-revoked) key, else ``None``.

    Revocation is enforced every call (``revoked_at IS NULL``) so a revoked key
    stops working immediately, with no cache lag.
    """
    if not full_key or not full_key.startswith(KEY_TAG):
        return None
    client = await get_client()
    result = await (
        client.table("api_keys")
        .select("id, user_id")
        .eq("key_hash", hash_key(full_key))
        .is_("revoked_at", "null")
        .execute()
    )
    if not result.data:
        return None
    row = result.data[0]
    return {"user_id": row["user_id"], "key_id": row["id"]}


async def touch_last_used(key_id: str) -> None:
    """Best-effort, throttled update of ``last_used_at``. Never raises."""
    now = time.monotonic()
    last = _last_used_writes.get(key_id)
    if last is not None and now - last < _LAST_USED_THROTTLE_SECONDS:
        return
    _last_used_writes[key_id] = now
    try:
        client = await get_client()
        await (
            client.table("api_keys")
            .update({"last_used_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", key_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — last_used is informational, never fail a request
        logger.warning("touch_last_used failed for key %s: %r", key_id, exc)
