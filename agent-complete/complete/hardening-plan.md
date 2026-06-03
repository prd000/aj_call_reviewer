# Frontend Hardening — Timeout Discipline + Loading-State Watchdog

## Context

We've shipped seven consecutive fixes for "infinite spinner / hung call" bugs. The pattern is identical across all of them: a network call without a timeout, on a code path that controls a loading state, with no safety net if the call never resolves. Each fix patched one location instead of the class.

This plan retires the class by closing two specific gaps in the frontend:

1. **Supabase JS auth calls have no timeouts.** `supabase.auth.getSession()`, `signOut()`, `signInWithPassword()`, `resetPasswordForEmail()` all rely on the Supabase JS client's internal network calls, which have no timeout. The client also uses an internal lock — if a token refresh hangs, every subsequent auth call waits forever for the lock.
2. **Loading states have no upper bound.** Every page/component that sets `loading: true` before a network call depends on its `finally`/`catch` to clear it. If the await never resolves, `setLoading(false)` never runs, and the user sees an indefinite spinner.

The two fixes are paired: wrap auth calls in a single module that enforces timeouts, and put a safety net on long-lived loading states.

This is the immediate hardening pass. The complementary backend refactor (async Supabase migration) lives in `agent/async-supabase-migration-plan.md`.

---

## Decisions

1. **Central auth module — `frontend/src/lib/supabaseAuth.js`** wraps every `supabase.auth.*` call with `Promise.race()` timeouts. Direct imports of `supabase.auth.*` outside this module are banned via ESLint.
2. **Loading-state watchdog hook — `frontend/src/hooks/useLoadingWatchdog.js`** flips `loading` back to `false` after a hard timeout (default 15s, matching `REQUEST_TIMEOUT_MS` in `api.js`) and logs a console error. Applied to every component with a long-lived initial-load loading state.
3. **Timeouts as named constants** in the new wrapper: `AUTH_TIMEOUT_MS = 8000` (matches what AuthContext already uses ad-hoc). The watchdog default reuses `REQUEST_TIMEOUT_MS = 15000` from `services/api.js`.
4. **Fire-and-forget signOut.** `logout()` clears local state synchronously and dispatches `signOut()` in the background — never awaits it. The wrapper logs failures via `console.error` so we keep observability without blocking the UI.
5. **Action-state spinners (`isSaving`, `isAdding`, `isDeleting`) are out of scope.** These gate buttons via `apiFetch`'s existing 15s `AbortSignal.timeout()` and already self-clear. Only initial-load `isLoading` states get the watchdog.
6. **ESLint enforcement.** A `no-restricted-imports` pattern bans `lib/supabase` imports outside `lib/supabaseAuth.js`. Prevents regression in future code.
7. **No new runtime dependencies.** Vanilla React hooks + `Promise.race()`. ESLint (and `@eslint/js`) may need to be added as devDependencies if not already present.

---

## Critical Files

### New files
- `frontend/src/lib/supabaseAuth.js` — wrapped auth API with timeouts and error logging
- `frontend/src/hooks/useLoadingWatchdog.js` — generic loading-state safety net

### Frontend modifications
- `frontend/src/context/AuthContext.jsx` — remove inline `Promise.race` blocks, call wrapper; apply watchdog to `loading` state
- `frontend/src/services/api.js` — import `getSession` and `signOut` from wrapper instead of using `supabase.auth.*` directly (replaces lines 9 and 21)
- `frontend/src/pages/LoginPage.jsx` — verify any direct `supabase.auth` usage is routed through the wrapper (login flow is currently in `AuthContext.login()`; if any local Supabase imports exist here, redirect them)
- `frontend/src/pages/HistoryPage.jsx` — apply `useLoadingWatchdog`
- `frontend/src/pages/ResultsPage.jsx` — apply `useLoadingWatchdog`
- `frontend/src/pages/FirmDetailPage.jsx` — apply `useLoadingWatchdog` to the initial `isLoading` state (firm fetch)
- `frontend/src/components/BdsRepsTab.jsx` — apply `useLoadingWatchdog`
- `frontend/src/components/FirmsTab.jsx` — apply `useLoadingWatchdog`
- `frontend/src/components/TemplateManager.jsx` — apply `useLoadingWatchdog`

### ESLint config
- `frontend/eslint.config.js` (or `.eslintrc.*` — verify during execution) — add `no-restricted-imports` pattern banning `lib/supabase` imports outside `lib/supabaseAuth.js`. If no ESLint config exists, create one and add a `"lint": "eslint src"` script to `frontend/package.json`.

### Context doc modifications
- `context/decisions.md` — append the timeout policy entry
- `context/log.md` — add hardening pass entry
- `context/map.md` — add the two new files to the frontend tree

---

## Implementation Steps

### 1. Create `frontend/src/lib/supabaseAuth.js`

```js
import { supabase } from './supabase'

const AUTH_TIMEOUT_MS = 8000

function withTimeout(promise, ms, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms)
    ),
  ])
}

export async function getSession() {
  try {
    return await withTimeout(supabase.auth.getSession(), AUTH_TIMEOUT_MS, 'getSession')
  } catch (e) {
    console.error('[supabaseAuth] getSession failed:', e)
    return { data: { session: null } }
  }
}

export async function signInWithPassword(credentials) {
  return withTimeout(
    supabase.auth.signInWithPassword(credentials),
    AUTH_TIMEOUT_MS,
    'signInWithPassword'
  )
}

// Fire-and-forget: callers must clear local state synchronously.
// supabase-js holds an internal lock during signOut; if the network call hangs,
// awaiting this would block the caller indefinitely.
export function signOut() {
  withTimeout(supabase.auth.signOut(), AUTH_TIMEOUT_MS, 'signOut').catch((e) => {
    console.error('[supabaseAuth] signOut failed:', e)
  })
}

export async function resetPasswordForEmail(email) {
  return withTimeout(
    supabase.auth.resetPasswordForEmail(email),
    AUTH_TIMEOUT_MS,
    'resetPasswordForEmail'
  )
}

// Pass-through; subscription model can't be wrapped meaningfully.
export function onAuthStateChange(callback) {
  return supabase.auth.onAuthStateChange(callback)
}
```

### 2. Create `frontend/src/hooks/useLoadingWatchdog.js`

```js
import { useEffect } from 'react'

const DEFAULT_TIMEOUT_MS = 15_000

export function useLoadingWatchdog(isLoading, setLoading, options = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, onTimeout, label = 'loading' } = options

  useEffect(() => {
    if (!isLoading) return
    const id = setTimeout(() => {
      console.error(
        `[useLoadingWatchdog] ${label} exceeded ${timeoutMs}ms — auto-clearing`
      )
      setLoading(false)
      if (onTimeout) onTimeout()
    }, timeoutMs)
    return () => clearTimeout(id)
  }, [isLoading, setLoading, timeoutMs, onTimeout, label])
}
```

### 3. Refactor `AuthContext.jsx`

- Remove the inline `Promise.race` in the `useEffect` (currently wrapping `getSession()`).
- Replace `supabase.auth.getSession()` with `getSession()` from `../lib/supabaseAuth`.
- Replace `supabase.auth.signInWithPassword(...)` in `login()` with the wrapper.
- Replace `supabase.auth.signOut()` in `logout()` with the wrapper's fire-and-forget `signOut()`.
- Replace `supabase.auth.resetPasswordForEmail(email)` with the wrapper.
- Replace `supabase.auth.onAuthStateChange(...)` with the wrapper.
- Add `useLoadingWatchdog(loading, setLoading, { timeoutMs: 10_000, label: 'auth-init' })` inside `AuthProvider`.

### 4. Update `services/api.js`

- Replace `supabase.auth.getSession()` on line 9 with `getSession()` from `../lib/supabaseAuth`.
- Replace `supabase.auth.signOut()` on line 21 with the wrapper's `signOut()`.

### 5. Apply `useLoadingWatchdog` to each long-lived initial-load loading state

In each of the following files, import the hook and add a single line near where the loading state is declared:

```js
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
// ...
useLoadingWatchdog(isLoading, setIsLoading, { label: '<page-name>' })
```

Targets:
- `pages/HistoryPage.jsx` (`isLoading` at line 14)
- `pages/ResultsPage.jsx` (`isLoading` at line 10)
- `pages/FirmDetailPage.jsx` (`isLoading` at line 82)
- `components/BdsRepsTab.jsx` (`isLoading` at line 66)
- `components/FirmsTab.jsx` (`isLoading` at line 9)
- `components/TemplateManager.jsx` (`isLoading` at line 22)

### 6. Add ESLint rule banning direct `lib/supabase` imports outside the wrapper

Verify which ESLint config the project uses (`eslint.config.js` for flat config, or `.eslintrc.*`). Add a `no-restricted-imports` pattern:

```js
// flat config example (eslint.config.js)
export default [
  {
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [{
          group: ['**/lib/supabase'],
          message: "Import from 'lib/supabaseAuth' instead — direct supabase.auth.* calls have no timeout and can hang on internal lock contention.",
        }],
      }],
    },
  },
  {
    // Exempt the wrapper itself, which legitimately imports the supabase client.
    files: ['src/lib/supabaseAuth.js'],
    rules: { 'no-restricted-imports': 'off' },
  },
]
```

If ESLint is not yet installed: add `eslint` + `@eslint/js` to `frontend/package.json` devDependencies and a `"lint": "eslint src"` script.

### 7. Update `context/decisions.md`

Append:

```markdown
## Network call timeout & loading-state safety net (2026-05-25)

All Supabase JS auth calls go through `frontend/src/lib/supabaseAuth.js`, which
wraps each call in `Promise.race()` with an 8s timeout. Direct use of
`supabase.auth.*` outside that module is banned via ESLint
(`no-restricted-imports` on `**/lib/supabase`).

All long-lived loading states (initial-load `isLoading` in pages and contexts)
use `frontend/src/hooks/useLoadingWatchdog.js` with a 15s default timeout that
auto-clears the loading state and logs a console error if the underlying call
hangs.

Rationale: seven consecutive bugs traced to the same shape (untimed network call
controlling loading state with no safety net). Policy retires the class.
```

### 8. Update `context/log.md`

Add a top entry:

```markdown
## 2026-05-25 — Frontend hardening: timeout discipline + loading-state watchdog

Eliminated infinite-spinner failure class by centralizing all Supabase JS auth
calls behind a timeout-enforcing wrapper (`lib/supabaseAuth.js`) and adding a
universal loading-state safety-net hook (`hooks/useLoadingWatchdog.js`) used by
every long-lived loading state in the app. Added ESLint rule preventing direct
`lib/supabase` imports outside the wrapper.

**Files created**: `frontend/src/lib/supabaseAuth.js`,
`frontend/src/hooks/useLoadingWatchdog.js`.
**Files modified**: `AuthContext.jsx`, `services/api.js`, 6 pages/components,
ESLint config.
```

### 9. Update `context/map.md`

Add the two new files to the existing frontend tree section.

---

## Verification

1. Boot the dev server (`py -m npm run dev` from `frontend/` or whatever the project's dev command is). App boots cleanly with no console errors.
2. Login as financial advisor — successful login, lands on Upload page.
3. Click Logout — immediate redirect to `/login`, no perceptible delay.
4. Login → throttle Chrome DevTools network to "Offline" → click Logout → redirects to `/login` within ~5s; check console for `[supabaseAuth] signOut failed: ... timed out` log.
5. Login → set network Offline → refresh page → spinner shows then auto-clears within ~10s, lands on `/login`; check console for `[useLoadingWatchdog] auth-init exceeded` log.
6. With network restored, history page loads reviews normally.
7. Throttle network to "Slow 3G" and visit each page (history, results, firm detail, BDS reps tab, firms tab, templates) — each loads or auto-clears within 15s. No indefinite spinners.
8. `grep -r "supabase.auth" frontend/src` — confirm zero matches outside `lib/supabaseAuth.js`.
9. Run `npm run lint` (or `py -m npm run lint`) — confirm zero `no-restricted-imports` violations.
10. Confirm Railway deploy succeeds with the new bundle.
11. Smoke-test the full happy path (login → upload → review → logout) one more time on the deployed app.

---

## Overlap & Coordination With Async Supabase Migration

This plan runs in a separate Claude Code context window from `agent/async-supabase-migration-plan.md`. They may run in parallel. Key coordination notes:

- **Code overlap: none.** This plan is 100% frontend; the migration is 100% backend. Zero source files are touched by both plans. The HTTP contract between frontend and backend is unchanged by both.
- **Context-doc overlap: high.** Both plans append entries to `context/decisions.md` and `context/log.md`. Run the doc-update steps **last** so any merge conflict is mechanical ("keep both entries"). `context/map.md` is touched only by this plan. `context/bug-corrections.md` is touched only by the migration plan.
- **Behavioral independence.** All verification steps in this plan work against either the current sync backend or the post-migration async backend; no contract changes either way.
- **Deployment order (recommended).** Ship this plan first; verify in production. The migration ships next.
- **Spurious failure mode to watch.** If the async migration is mid-flight with a missed `await` (returning a coroutine instead of data), this plan's smoke test could fail spuriously. Verify each plan against a deploy that does NOT include the other's in-flight changes.
