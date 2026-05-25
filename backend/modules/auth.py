import asyncio
import logging

import httpx
from fastapi import Depends, HTTPException, Header
from supabase_auth.errors import AuthApiError
from modules.supabase_client import get_client

logger = logging.getLogger(__name__)

# Transient transport errors that mean "Supabase Auth was unreachable", NOT
# "the token is bad". Caller should retry; we surface 503 so the frontend
# treats it as a service blip instead of forcing a logout.
_TRANSIENT_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
    asyncio.TimeoutError,
)


async def _validate_token(token: str):
    """Validate the JWT against Supabase Auth with one retry on transient failure.

    Returns the auth user on success.
    Raises HTTPException(401) on real auth failures.
    Raises HTTPException(503) on transient Supabase service failures.
    """
    last_transient: Exception | None = None
    for attempt in range(2):
        try:
            client = await get_client()
            resp = await client.auth.get_user(token)
            if resp.user is None:
                raise HTTPException(status_code=401, detail="Invalid token")
            return resp.user
        except HTTPException:
            raise
        except AuthApiError as e:
            # Real auth failure surfaced by Supabase (expired, malformed, revoked)
            logger.info("Auth rejected token: %s", e)
            raise HTTPException(status_code=401, detail="Invalid token")
        except _TRANSIENT_EXCEPTIONS as e:
            last_transient = e
            logger.warning(
                "Transient Supabase auth error (attempt %d/2): %r", attempt + 1, e
            )
            continue
        except Exception as e:
            # Unknown error — log loudly and treat as transient rather than
            # silently logging users out. If it turns out to be a real auth
            # bug, the log will tell us.
            logger.exception("Unexpected Supabase auth error: %r", e)
            last_transient = e
            continue
    raise HTTPException(
        status_code=503,
        detail="Auth service temporarily unavailable",
    ) from last_transient


async def get_current_user(authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.removeprefix("Bearer ")
    auth_user = await _validate_token(token)

    try:
        client = await get_client()
        profile_resp = await (
            client.table("profiles").select("*").eq("id", str(auth_user.id)).execute()
        )
    except _TRANSIENT_EXCEPTIONS as e:
        logger.warning("Transient Supabase error loading profile: %r", e)
        raise HTTPException(
            status_code=503, detail="Auth service temporarily unavailable"
        )

    if not profile_resp.data:
        raise HTTPException(status_code=401, detail="No profile found")
    p = profile_resp.data[0]
    if not p["is_active"]:
        raise HTTPException(status_code=403, detail="Account deactivated")
    return {
        "user_id": str(auth_user.id),
        "role": p["role"],
        "firm_id": p.get("firm_id"),
        "name": p["name"],
    }


def require_bds_rep(user: dict = Depends(get_current_user)):
    if user["role"] != "bds_rep":
        raise HTTPException(status_code=403, detail="BDS reps only")
    return user
