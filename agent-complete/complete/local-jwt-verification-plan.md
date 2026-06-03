# Plan: Local JWT Verification on the Backend

## Context

Users are still being kicked to the login screen intermittently while actively using the app, despite three rounds of frontend fixes (Phases 1–3). The frontend changes are defensive band-aids; the real fragility is in the backend.

Today, `backend/modules/auth.py:_validate_token()` calls `client.auth.get_user(token)` on **every protected API request**. That makes an HTTP round-trip from Railway to Supabase Auth per request, which:

- Adds latency to every request.
- Fails whenever the Railway↔Supabase network has any blip (manifests as transient 401/503 on the frontend).
- Creates concurrent-refresh race conditions during JWT rotation.
- Couples backend uptime to Supabase Auth uptime, even though JWTs are self-validating.

**The fix**: verify the JWT signature locally on the backend using Supabase's HS256 JWT secret. No network call needed for the common path. Combined with bumping the JWT expiry from 1h to a longer window in the Supabase dashboard, this eliminates the root cause of the repeated logout bugs.

**Intended outcome**: Zero spurious logouts from transient Supabase Auth blips. Faster API responses. Backend stays available even if Supabase Auth has a hiccup. The whole class of "Phase N fix" patches stops accumulating.

---

## Approach

**Cutover**: Hard cutover (user-confirmed). Replace network validation with local verification in one commit. Failure mode is a 401 on the first request if `SUPABASE_JWT_SECRET` is misconfigured — caught immediately in Railway logs. Rollback is `git revert` + redeploy.

**JWT expiry**: Bump from 1h (default) to 24h in the Supabase dashboard as part of this work (user-confirmed). Reduces rotation frequency ~24x.

**Library**: `PyJWT[crypto]` (lighter, actively maintained, native `exp`/`aud`/`iss` validation in one call).

---

## Implementation

### 1. Add dependency

**File: `backend/requirements.txt`**

Add one line:

```
PyJWT[crypto]>=2.8.0
```

### 2. Add env var

**Where to get it**: Supabase dashboard → Project Settings → API → JWT Settings → JWT Secret. ~64-char base64 string. Treat as service_role-level secret.

**Where to set it**: Railway environment variables for the backend service (and worker if it ever uses auth, which currently it does not). Add to local `.env` for dev.

**Env var name**: `SUPABASE_JWT_SECRET`

### 3. Rewrite `backend/modules/auth.py`

The new file:

- Removes: `supabase_auth.errors.AuthApiError` import, the retry loop in `_validate_token`, `client.auth.get_user(token)` call, `asyncio` import.
- Adds: `jwt` import, `SUPABASE_JWT_SECRET` and `SUPABASE_ISSUER` module-level constants read from env at import time (fail-fast on missing).
- Reuses: `modules.user_profiles.get_profile()` instead of duplicating the profile query.

**New `_validate_token` sketch**:

```python
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
SUPABASE_ISSUER = f"{os.environ['SUPABASE_URL'].rstrip('/')}/auth/v1"

def _validate_token(token: str) -> str:
    """Verify JWT locally. Returns user_id from `sub` claim. Raises 401 on failure."""
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=SUPABASE_ISSUER,
            options={"require": ["exp", "sub", "aud", "iss"]},
            leeway=30,  # 30s clock skew tolerance
        )
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except InvalidTokenError as e:
        logger.info("JWT rejected: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token")
    return sub
```

Note: `_validate_token` becomes **synchronous** — no network, no `async` needed.

**New `get_current_user`**:

```python
from modules.user_profiles import get_profile

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
```

- Return shape preserved exactly — no caller changes needed.
- `_TRANSIENT_EXCEPTIONS` tuple is kept (still relevant for the profile lookup).
- `require_bds_rep` is unchanged.

### 4. Bump JWT expiry (Supabase dashboard)

Project Settings → Authentication → JWT Settings → set **JWT expiry limit** to `86400` (24 hours). Save. No code change. Existing sessions continue with their original expiry; new logins get the new window.

### 5. Files touched

- `backend/requirements.txt` — add PyJWT
- `backend/modules/auth.py` — rewrite per above
- `backend/.env.example` (if it exists) — add `SUPABASE_JWT_SECRET=` placeholder; otherwise document in a README
- Railway env vars — add `SUPABASE_JWT_SECRET` to backend service

### Files NOT touched

- `backend/modules/supabase_client.py` — no change
- `backend/modules/user_profiles.py` — reused as-is via `get_profile()`
- All `backend/routers/*.py` — no caller signature changes
- `backend/tasks.py` — Celery worker has no auth, unaffected
- Frontend — entirely unaffected (this is a pure backend swap)

---

## Verification

1. **Local manual curl** — grab a real token from browser devtools (`localStorage` → `sb-*-auth-token` → `access_token`):
   ```
   curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/users/me
   ```
   Expect 200 with the profile JSON. Then mangle one character of the token → expect 401 with `"Invalid token"`.

2. **Log inspection** — tail backend logs while making 5 sequential authenticated requests. Confirm **zero** outbound HTTPS calls to `<project>.supabase.co/auth/v1/user`. Previously there was one per request.

3. **UI smoke test** — log in to the deployed app, leave a tab idle for 10 minutes, then perform actions (create firm, upload, browse history). No spurious logout. This is the bug being fixed.

4. **Deactivation test** — set a test profile to `is_active=false` directly in Supabase. Next request from that user should return 403, not 200.

5. **Expiry test** — wait past the JWT expiry without using the app (frontend won't auto-refresh if tab is closed). Reopen and make a request — expect 401, frontend's Phase 3 `refreshSession()` should recover transparently.

---

## Risks and edge cases

- **Revocation latency**: Local verification cannot detect server-side revocation until the JWT's natural `exp`. Mitigation: the profile lookup still runs every request, so flipping `is_active=false` takes effect within one request. Supabase's `set_active()` already handles this.
- **Clock skew**: 30s `leeway` in `jwt.decode()` handles minor drift between Railway and clients.
- **Refresh token rotation**: Untouched — frontend's supabase-js handles this; backend only sees access tokens.
- **Future asymmetric signing**: If Supabase migrates to RS256 with JWKS endpoints, swap to `PyJWKClient` with cached JWKS fetch (one network call per key rotation, not per request). Not urgent.
- **Secret rotation**: Rotating `SUPABASE_JWT_SECRET` invalidates all existing sessions. Document; not needed for this work.
- **Missing env var at startup**: `os.environ["SUPABASE_JWT_SECRET"]` raises `KeyError` at import. Fail-fast in Railway logs is preferable to silently 500-ing every request.

---

## Post-implementation

Update `context/log.md` with a new entry describing the change. Update `context/decisions.md` with the new auth-validation decision (replacing the 2026-05-25 "Auth error classification (401 vs 503)" entry's implicit assumption that we call `client.auth.get_user` per request).
