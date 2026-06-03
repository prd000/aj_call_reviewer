# Idle Auto-Logout Fix — Plan

Bug #2 from `context/bug-corrections.md`: "If I am idle for too long, it kicks me to the login screen. We need to be able to differentiate between user being idle and calls hanging, and not punish the user for staying on one screen."

## Context

A previous fix on **2026-05-25** ("Fix: idle auto-logout from transient backend errors") split backend 401-vs-503 and stopped re-fetching the profile on every `TOKEN_REFRESHED` event. The bug is still happening because the same "distinguish transient from real auth failure" discipline was **not applied to the frontend Supabase-session wrapper**. One layer still silently lies about session state, and that lie cascades through every downstream check, turning a single slow Supabase call during idle into `setUser(null)` → `ProtectedRoute` → `/login`.

The fix below makes that distinction explicit at the layer where it currently collapses, mirroring the 401-vs-503 discipline the backend already has.

## Root cause

### The smoking gun — `frontend/src/lib/supabaseAuth.js:14-21`

```js
export async function getSession() {
  try {
    return await withTimeout(supabase.auth.getSession(), AUTH_TIMEOUT_MS, 'getSession')
  } catch (e) {
    console.error('[supabaseAuth] getSession failed:', e)
    return { data: { session: null } }   // ← lies: timeout reported as "no session"
  }
}
```

When `supabase.auth.getSession()` hangs more than 8s (supabase-js internal lock contention, slow network, Supabase cold start on Railway), this returns the same shape as a real logged-out state. Every call site downstream is built around the assumption that `session: null` means "user is not logged in".

### How that leak becomes `/login` during idle

**Path A — bootstrap / focus-triggered refetch** (proven from current code: `AuthContext.jsx:48-58`, `:72-74`)

1. User idle on a screen. supabase-js fires `INITIAL_SESSION` on bootstrap, or `SIGNED_IN` on tab focus / internal session sync.
2. `AuthContext` calls `loadProfile(s)`.
3. `loadProfile` calls `getCurrentUserProfile()` → `authHeaders()` → **redundantly re-calls `getSession()`** (we already have `s`, but the API layer doesn't take it as input).
4. That second `getSession()` times out → returns fake `{ session: null }`.
5. `authHeaders()` throws `NoSessionError` (`api.js:17`).
6. `loadProfile`'s catch hits `if (err instanceof NoSessionError) setUser(null)` (`AuthContext.jsx:35-38`).
7. `ProtectedRoute` sees `user=null` → `Navigate to="/login"`.

**Path B — `SIGNED_OUT` fires after failed background token refresh** (`AuthContext.jsx:63-66`)

- supabase-js auto-refreshes the access token periodically. If the refresh ultimately fails, it dispatches `SIGNED_OUT`.
- Current handler treats this as ground truth and `setUser(null)` unconditionally — even though the failure may have been transient (Supabase blip, brief network outage), not a real session revocation.

## Recommended approach

Make the frontend stack distinguish **`NoSession`** (Supabase confirmed there is no session) from **`SessionUnavailable`** (we couldn't determine session state right now). `SessionUnavailable` must never demote the user. Then plug the redundant `getSession()` call and loosen the auth-init watchdog so cold start is forgiving.

---

### Change 1 — `frontend/src/lib/supabaseAuth.js`

Stop catching the timeout silently. Add a typed error and throw it.

```js
export class SessionUnavailableError extends Error {
  constructor(cause) {
    super('Supabase session check failed')
    this.name = 'SessionUnavailableError'
    this.cause = cause
  }
}

export async function getSession() {
  try {
    return await withTimeout(supabase.auth.getSession(), AUTH_TIMEOUT_MS, 'getSession')
  } catch (e) {
    console.warn('[supabaseAuth] getSession transient failure:', e)
    throw new SessionUnavailableError(e)
  }
}
```

---

### Change 2 — `frontend/src/services/api.js`

Re-export the new error so callers can `instanceof`-check it. `authHeaders()` doesn't need restructuring — `getSession()` now throws on the transient case, so a successful return implies the null-check below it is meaningful.

```js
export { SessionUnavailableError } from '../lib/supabaseAuth'
```

Also: thread an optional access token through `getCurrentUserProfile` so `loadProfile` (which already has a session) can skip the redundant `getSession()` call inside `authHeaders` — see Change 4.

---

### Change 3 — `frontend/src/context/AuthContext.jsx`

Four small edits.

**3a.** Import the new error:

```js
import { ..., SessionUnavailableError } from '../lib/supabaseAuth'
```

**3b. The key behavioral fix — `loadProfile` catch preserves user state on transient failures:**

```js
} catch (err) {
  if (err instanceof SessionUnavailableError) {
    console.warn('loadProfile: transient session-check failure — preserving user state')
    return
  }
  if (err instanceof NoSessionError) { setUser(null); return }
  if (err?.message === 'Session expired. Please log in again.') {
    setUser(null); return
  }
  console.error('loadProfile failed (transient):', err)
}
```

This is what stops Path A. Even if a transient `getSession()` failure throws while we have a valid session, we keep the user logged in.

**3c. Bootstrap `useEffect` — handle the same error on initial mount:**

```js
getSession()
  .then(async ({ data: { session: s } }) => {
    setSession(s)
    await loadProfile(s)
  })
  .catch((err) => {
    if (err instanceof SessionUnavailableError) {
      console.warn('Initial getSession transient failure — user can retry')
    } else {
      console.error('Auth session check failed:', err)
    }
  })
  .finally(() => setLoading(false))
```

**3d. Defensive `SIGNED_OUT` re-check — closes Path B:**

```js
if (event === 'SIGNED_OUT') {
  try {
    const { data: { session: recheck } } = await getSession()
    if (!recheck) setUser(null)
    // otherwise: false alarm — supabase-js fired SIGNED_OUT but a session still exists
  } catch (err) {
    if (err instanceof SessionUnavailableError) {
      console.warn('SIGNED_OUT received but session re-check failed transiently; preserving user')
    } else {
      setUser(null)
    }
  }
  return
}
```

---

### Change 4 — Eliminate redundant `getSession()` inside `authHeaders()` when caller already has a session

This was the second `getSession()` call in Path A. With Change 3b in place it's no longer dangerous, but removing it closes the gap entirely and reduces background traffic during idle.

**`frontend/src/services/api.js`** — accept an optional pre-resolved token:

```js
async function authHeaders(accessToken) {
  if (accessToken) return { Authorization: `Bearer ${accessToken}` }
  const { data: { session } } = await getSession()
  if (!session) throw new NoSessionError()
  return { Authorization: `Bearer ${session.access_token}` }
}

export async function getCurrentUserProfile(accessToken) {
  const headers = await authHeaders(accessToken)
  const response = await apiFetch(`${BASE_URL}/users/me`, { headers })
  return handleResponse(response)
}
```

Only `getCurrentUserProfile` needs the new signature — it's the only call site that already has a session in scope from the auth flow. All other callers (`listReviews`, `uploadCall`, firms, templates, etc.) continue passing nothing and the existing `getSession()` path runs unchanged.

**`frontend/src/context/AuthContext.jsx`** — pass the token through:

```js
async function loadProfile(activeSession) {
  if (!activeSession) {
    setUser(null)
    return
  }
  try {
    const profile = await getCurrentUserProfile(activeSession.access_token)
    setUser({ id: activeSession.user.id, ...profile })
  } catch (err) {
    // ...catch block from Change 3b
  }
}
```

Also update the explicit `login()` flow if it calls `getCurrentUserProfile()` — pass `data.session.access_token` there too so the post-login profile fetch can't be tripped up by a slow second `getSession()`.

---

### Change 5 — Loosen `useLoadingWatchdog` auth-init timeout 10s → 20s

`AuthContext.jsx:19` currently:

```js
useLoadingWatchdog(loading, setLoading, { timeoutMs: 10_000, label: 'auth-init' })
```

Bump to `20_000`. Railway cold start (backend + Supabase) can plausibly exceed 10s, and when the watchdog fires while `user` is still null, the user lands on `/login`. The architectural fix is "don't let a watchdog make a logout decision", but bumping the bound is a cheap one-line change that materially reduces the false-positive window for cold start.

---

## Critical files

| File | Change |
|------|--------|
| `frontend/src/lib/supabaseAuth.js` | Add `SessionUnavailableError`; throw on timeout instead of returning fake null |
| `frontend/src/services/api.js` | Re-export `SessionUnavailableError`; `authHeaders` accepts optional token; `getCurrentUserProfile` accepts optional token |
| `frontend/src/context/AuthContext.jsx` | Import error; 3b/3c/3d behavioral changes; pass token to `getCurrentUserProfile`; bump watchdog to 20s |

No backend changes. The 2026-05-25 backend fix already returns 503 (not 401) on transient Supabase failures, and `handleResponse` in `api.js` already preserves auth state on 5xx — that half is sound.

## Verification

**Manual idle test (the golden path the user reported):**

1. `py -m uvicorn main:app --reload` from `backend/` and `npm run dev` from `frontend/`.
2. Log in. Navigate to `/history`.
3. DevTools → Network → throttle to "Slow 3G", or block the Supabase domain in the request blocking panel.
4. Wait 3+ minutes without interacting.
5. **Expected:** stays on `/history`, no `/login` redirect, polling errors logged silently in the console as transient.
6. Restore network. App keeps working without a manual refresh.

**Targeted transient simulation (forces the failure mode deterministically):**

- Temporarily lower `AUTH_TIMEOUT_MS` in `lib/supabaseAuth.js` to `100` and throttle the network. Confirm:
  - `SessionUnavailableError` thrown (visible in console)
  - User state preserved
  - **No redirect to `/login`**
- Restore `AUTH_TIMEOUT_MS` to `8000` before commit.

**Regression checks (these must still work):**

- Explicit logout (TopNav button) → routes to `/login` immediately, clears state.
- Real backend 401 from `/me` (e.g. manually clear Supabase localStorage mid-session) → routes to `/login`.
- Cold start with no Supabase session → lands on `/login` cleanly.
- Watchdog still fires after 20s if auth-init truly hangs (don't break the "stuck loading" safety net).

## Per-CLAUDE.md follow-ups

After implementation:
- Add an entry to `context/log.md` summarizing the fix, the files modified, and the root cause distinction (`SessionUnavailableError` vs `NoSessionError`).
- No `decisions.md` update needed — this is a bug fix consistent with the 401-vs-503 discipline already recorded.
- No `map.md` update needed — no new files, no new folders, no new top-level functionality.
- No `deferredwork.md` update — no new env vars or API keys.
