import logging
import os

import httpx
import jwt
from fastapi import Depends, HTTPException, Header
from jwt import ExpiredSignatureError, InvalidTokenError
from modules.user_profiles import get_profile

logger = logging.getLogger(__name__)

SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
SUPABASE_ISSUER = f"{os.environ['SUPABASE_URL'].rstrip('/')}/auth/v1"

_TRANSIENT_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)


def _validate_token(token: str) -> str:
    """Verify JWT locally. Returns user_id from `sub` claim. Raises 401 on failure."""
    try:
        # Diagnostic: decode without verification to log actual claims
        unverified = jwt.decode(token, options={"verify_signature": False})
        logger.warning(
            "JWT claims (unverified) — iss=%r aud=%r sub=%r | expected iss=%r aud=%r",
            unverified.get("iss"),
            unverified.get("aud"),
            unverified.get("sub"),
            SUPABASE_ISSUER,
            "authenticated",
        )
    except Exception as diag_err:
        logger.warning("JWT diagnostic decode failed: %r", diag_err)

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=SUPABASE_ISSUER,
            options={"require": ["exp", "sub", "aud", "iss"]},
            leeway=30,
        )
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except InvalidTokenError as e:
        logger.warning("JWT rejected: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token")
    return sub


async def get_current_user(authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.removeprefix("Bearer ")
    user_id = _validate_token(token)

    try:
        p = await get_profile(user_id)
    except _TRANSIENT_EXCEPTIONS as e:
        logger.warning("Transient Supabase error loading profile: %r", e)
        raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")

    if not p:
        raise HTTPException(status_code=401, detail="No profile found")
    if not p["is_active"]:
        raise HTTPException(status_code=403, detail="Account deactivated")
    return {
        "user_id": user_id,
        "role": p["role"],
        "firm_id": p.get("firm_id"),
        "name": p["name"],
    }


def require_bds_rep(user: dict = Depends(get_current_user)):
    if user["role"] != "bds_rep":
        raise HTTPException(status_code=403, detail="BDS reps only")
    return user
