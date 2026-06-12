import logging
import os
import time

import httpx
import jwt
from fastapi import Depends, HTTPException, Header
from jwt import ExpiredSignatureError, InvalidTokenError, PyJWKClient
from modules.user_profiles import get_profile

logger = logging.getLogger(__name__)

_SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_ISSUER = f"{_SUPABASE_URL}/auth/v1"
_JWKS_URL = f"{_SUPABASE_URL}/auth/v1/.well-known/jwks.json"

_TRANSIENT_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)

# Lazy singleton — fetches JWKS once, caches by key ID
_jwks_client: PyJWKClient | None = None

# Short-TTL in-process profile cache.  Keyed by user_id; value is
# (profile_dict, monotonic_timestamp).  Eliminates one Supabase round-trip per
# request on the hot polling path while keeping deactivation/role-change lag
# <= TTL.  Per-process: each uvicorn/Celery worker has its own cache.
_PROFILE_CACHE_TTL = float(os.environ.get("PROFILE_CACHE_TTL_SECONDS", "30"))
_profile_cache: dict[str, tuple[dict, float]] = {}


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_JWKS_URL, cache_keys=True)
    return _jwks_client


def invalidate_profile(user_id: str) -> None:
    """Remove a user's cached profile, forcing a fresh DB fetch on next request.

    Call this after any write that changes role, firm, or is_active so
    deactivation/role changes take effect within one request rather than
    waiting for the TTL to expire.
    """
    _profile_cache.pop(user_id, None)


def _validate_token(token: str) -> str:
    """Verify JWT. Supports HS256 (secret) and RS256 (JWKS). Returns sub claim."""
    try:
        alg = jwt.get_unverified_header(token).get("alg", "HS256")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        if alg == "HS256":
            if not SUPABASE_JWT_SECRET:
                logger.error("HS256 token received but SUPABASE_JWT_SECRET is unset")
                raise HTTPException(status_code=401, detail="Invalid token")
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
                issuer=SUPABASE_ISSUER,
                options={"require": ["exp", "sub", "aud", "iss"]},
                leeway=30,
            )
        else:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                audience="authenticated",
                issuer=SUPABASE_ISSUER,
                options={"require": ["exp", "sub", "aud", "iss"]},
                leeway=30,
            )
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except InvalidTokenError as e:
        logger.info("JWT rejected (alg=%s): %s", alg, e)
        raise HTTPException(status_code=401, detail="Invalid token")
    except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.NetworkError) as e:
        logger.warning("JWKS fetch failed: %r", e)
        raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token")
    return sub


async def get_current_user(authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.removeprefix("Bearer ")
    user_id = _validate_token(token)

    # Check the short-TTL cache before hitting Supabase.
    now = time.monotonic()
    cached = _profile_cache.get(user_id)
    if cached is not None:
        p, ts = cached
        if now - ts < _PROFILE_CACHE_TTL:
            if not p["is_active"]:
                raise HTTPException(status_code=403, detail="Account deactivated")
            return {
                "user_id": user_id,
                "role": p["role"],
                "firm_id": p.get("firm_id"),
                "name": p["name"],
            }
        # Expired — evict and fall through to DB fetch.
        del _profile_cache[user_id]

    try:
        p = await get_profile(user_id)
    except _TRANSIENT_EXCEPTIONS as e:
        logger.warning("Transient Supabase error loading profile: %r", e)
        raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")

    if not p:
        raise HTTPException(status_code=401, detail="No profile found")
    if not p["is_active"]:
        raise HTTPException(status_code=403, detail="Account deactivated")

    _profile_cache[user_id] = (p, now)

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
