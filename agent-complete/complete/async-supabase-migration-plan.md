# Backend Async Supabase Migration

## Context

Backend uses sync supabase-py running in FastAPI's default 40-thread executor pool. Every request that touches Supabase occupies one of those threads for the duration of the HTTP call. Under load — or during a brief Supabase slowdown — the pool saturates and unrelated requests queue behind blocked threads, manifesting as cascading timeouts on the client.

The 10-second `httpx.Client` timeout we added in `backend/modules/supabase_client.py` prevents permanent thread loss, but doesn't address the architectural ceiling. supabase-py 2.x ships `acreate_client`, an async client built on `httpx.AsyncClient`; combined with `async def` route handlers, FastAPI dispatches each request on the asyncio event loop with no thread-pool cap. The PRD targets 300 clients with hundreds of users — large enough that this becomes load-bearing in production.

This is the planned refactor sprint already named in `context/bug-corrections.md` item #4. It is not urgent (the companion `agent/hardening-plan.md` retires the user-visible bug class) but is architecturally correct.

---

## Decisions

1. **Big-bang cutover, not incremental.** Reasons: (a) every backend module imports the same `supabase_client.get_client()` getter, so introducing both sync and async clients in parallel is messier than a single swap; (b) FastAPI's `def` route handlers can't `await` async module functions, so a partial migration leaves half the codebase still on threads; (c) the surface (~35 call sites across 5 modules + 4 routers) is small enough to convert and verify in one sprint.
2. **Keep singleton-getter pattern.** Replace `create_client` with `acreate_client`, return `AsyncClient`. Lazy-initialize per process via module-level guard.
3. **`httpx.AsyncClient(timeout=10.0)`** replaces the sync `httpx.Client`. Same 10s budget, same `ClientOptions(httpx_client=...)` injection.
4. **All module functions become `async def`.** Every `.execute()` becomes `await ....execute()`. Every `client.auth.get_user(...)` becomes `await client.auth.get_user(...)`. Every `client.auth.admin.*` becomes `await ...`.
5. **All route handlers become `async def`.** Every module function call inside them gets an `await`.
6. **`get_current_user` returns to `async def`.** It was reverted to sync in a prior fix because it called sync Supabase from an async context, blocking the event loop. With the async client it becomes correctly async again.
7. **Celery tasks stay sync.** Celery workers are sync by design. Tasks that need to call async module functions wrap calls in `asyncio.run(...)`. If a task makes many async calls, define a single inner `async def _run()` and call `asyncio.run(_run())` once so the task shares a single event loop.
8. **No public API changes.** Frontend `services/api.js` is untouched. All routes preserve their existing paths, request/response shapes, and auth behavior.
9. **Migration verified by load test.** A 100-concurrent-connection burst against `/api/users/me` should complete with <2s p99 latency and zero 5xx. Pre-migration baseline should be measured at the start of the sprint for comparison.

---

## Critical Files

### Backend modifications (sync → async cutover)
- `backend/modules/supabase_client.py` — REWRITE INTERNALS: `acreate_client` + `AsyncClient` + lazy init via `async def get_client()`
- `backend/modules/auth.py` — convert `get_current_user` back to `async def`; await Supabase auth/profile calls
- `backend/modules/user_profiles.py` — convert all ~9 call sites; await every `.execute()` and `.auth.admin.*`
- `backend/modules/firms.py` — convert all ~5 call sites
- `backend/modules/storage.py` — convert all ~12 call sites (reviews table + storage bucket operations)
- `backend/modules/templates.py` — convert all ~6 call sites
- `backend/routers/upload.py` — `async def` handlers; await module calls (~6 sites)
- `backend/routers/reviews.py` — `async def` handlers; await module calls (~4 sites)
- `backend/routers/management.py` — `async def` handlers; await module calls (~8+ sites)
- `backend/routers/templates.py` — `async def` handlers; await module calls (~4 sites)

### Celery layer (inspect, possibly modify)
- `backend/celery_app.py` — likely no change (Celery is sync; task functions call `asyncio.run(...)` if they need async module functions)
- `backend/tasks.py` — modify to wrap async module calls: `asyncio.run(module.func(...))`. Confirm during execution. If a task makes many calls, share one event loop via inner `async def _run()` + single `asyncio.run(_run())`.

### Context doc modifications
- `context/decisions.md` — record async cutover and the rationale (thread-pool ceiling)
- `context/log.md` — add migration entry
- `context/bug-corrections.md` — strike item #4 (it's done)

### Out of scope
- No schema changes
- No frontend changes
- No router path or response-shape changes
- No new runtime dependencies (`acreate_client` ships in installed supabase-py 2.x)

---

## Implementation Steps

### 1. Rewrite `backend/modules/supabase_client.py`

```python
import os
import httpx
from supabase import acreate_client, AsyncClient, ClientOptions

_client: AsyncClient | None = None

async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = await acreate_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
            options=ClientOptions(httpx_client=httpx.AsyncClient(timeout=10.0)),
        )
    return _client
```

### 2. Convert each module (auth.py, user_profiles.py, firms.py, storage.py, templates.py)

Pattern repeated across modules:

```python
# before
def get_user(user_id: str):
    client = get_client()
    resp = client.table("profiles").select("*").eq("id", user_id).single().execute()
    return resp.data

# after
async def get_user(user_id: str):
    client = await get_client()
    resp = await client.table("profiles").select("*").eq("id", user_id).single().execute()
    return resp.data
```

Apply mechanically to every function in each module. No function-signature changes beyond `def` → `async def` and `await` insertions.

**Watch points:**
- `client.auth.get_user(token)` → `await client.auth.get_user(token)`
- `client.auth.admin.invite_user_by_email(...)` → `await client.auth.admin.invite_user_by_email(...)`
- `client.auth.admin.delete_user(uid)` → `await client.auth.admin.delete_user(uid)`
- Storage bucket operations (`client.storage.from_("recordings").upload(...)` etc.) → `await client.storage.from_(...).upload(...)` (verify behavior in supabase-py async storage API)

### 3. Convert each router (upload.py, reviews.py, management.py, templates.py)

```python
# before
@router.get("/me")
def get_me(user = Depends(get_current_user)):
    return user_profiles.get_user(user["id"])

# after
@router.get("/me")
async def get_me(user = Depends(get_current_user)):
    return await user_profiles.get_user(user["id"])
```

### 4. Convert `get_current_user` back to `async def`

```python
async def get_current_user(authorization: str = Header(...)):
    token = authorization.removeprefix("Bearer ").strip()
    client = await get_client()
    user_resp = await client.auth.get_user(token)
    # ... rest of logic, with await on any Supabase calls
```

FastAPI handles `async def` dependencies natively on the event loop. No additional plumbing.

### 5. Inspect and adapt Celery tasks

Read `backend/tasks.py`. For each call into a now-async module function, wrap in `asyncio.run(...)`:

```python
# before
storage.update_review_status(review_id, "transcribing")

# after
asyncio.run(storage.update_review_status(review_id, "transcribing"))
```

If a task makes many async calls, define a single inner `async def _run()` and call `asyncio.run(_run())` once at the end so the task shares a single event loop:

```python
@celery_app.task(bind=True, max_retries=2)
def process_review_task(self, review_id: str, ...):
    async def _run():
        await storage.update_review_status(review_id, "transcribing")
        transcript = await transcriber.transcribe(...)
        await storage.update_review_status(review_id, "reviewing")
        # ...
    asyncio.run(_run())
```

### 6. Update `context/decisions.md`

```markdown
## Backend async Supabase migration (2026-MM-DD)

Backend uses async supabase-py via `acreate_client`. All FastAPI route handlers
and all backend module functions are `async def`. Supabase HTTP calls run on
the asyncio event loop via `httpx.AsyncClient(timeout=10.0)`.

Rationale: sync supabase-py occupied a thread from FastAPI's default 40-thread
executor pool for the duration of every Supabase HTTP call, capping concurrent
throughput and creating cascading-timeout failure modes under load. Async
client lifts the ceiling. PRD scale target (300 clients / hundreds of users)
makes this necessary before further growth.

Celery tasks remain sync; they call async module functions via `asyncio.run(...)`.
```

### 7. Update `context/bug-corrections.md`

Remove item #4 (the async migration entry); it is now done.

### 8. Update `context/log.md`

Add a top entry:

```markdown
## 2026-MM-DD — Backend async Supabase migration

Replaced sync supabase-py with `acreate_client` (async). All FastAPI route
handlers and module functions are now `async def`; every Supabase call is
awaited on the event loop via `httpx.AsyncClient(timeout=10.0)`. Eliminates
the 40-thread executor-pool ceiling that gated server concurrency.

**Files modified**: `supabase_client.py`, `auth.py`, `user_profiles.py`,
`firms.py`, `storage.py`, `templates.py`, four routers, `tasks.py`.
```

---

## Verification

1. App boots cleanly: `py -m uvicorn backend.main:app --reload` — no startup errors.
2. Login as BDS rep — `/api/users/me` returns profile in <500ms.
3. Login as financial advisor — `/api/users/me` returns scoped profile.
4. Upload a recording → confirm Supabase `reviews` row appears with status `pending`.
5. Celery worker processes the upload → status progresses `transcribing → reviewing → complete`.
6. List history — all rows render with correct scores.
7. View a completed review — criteria scores and transcript render.
8. Management → create firm → row appears in Supabase `firms` table.
9. Management → invite financial advisor → Supabase Auth row created, email sent.
10. Management → delete firm → row gone from Supabase.
11. Templates → list → edit a criterion → save → confirm change persists in Supabase.
12. **Load test**: `wrk -t4 -c100 -d30s -H "Authorization: Bearer <jwt>" https://<deployed>/api/users/me` — confirm <2s p99 latency and zero 5xx. Run the same test against the pre-migration deployment first to establish baseline.
13. Trigger a Celery task while load test is running — confirm both web and worker traffic complete cleanly.
14. Railway deploy succeeds for both web and worker services with no startup errors.
15. Inspect Railway logs for any thread-pool warnings — confirm none.

---

## Risks and Rollback

- **Risk**: a single missed `await` (e.g., forgetting `await client.table(...).execute()`) returns a coroutine instead of data, surfacing as cryptic errors. **Mitigation**: run the manual verification list end-to-end before deploying; lint with `mypy`/`pyright` if configured; the load test will surface unhandled coroutine errors as 500s.
- **Risk**: Celery `asyncio.run()` per call creates and tears down an event loop each invocation. If a task makes many calls, this is wasteful — share a single `asyncio.run(_run())` per task (see step 5).
- **Risk**: supabase-py async storage API surface may differ slightly from sync (`.upload`, `.create_signed_url`, `.remove`). Verify each storage call site against current supabase-py docs during migration.
- **Rollback**: this is a single-PR change; revert the PR if needed. `supabase_client.py` is the only file with structural changes; everything else is mechanical `def → async def` + `await` insertions.

---

## Overlap & Coordination With Frontend Hardening

This plan runs in a separate Claude Code context window from `agent/hardening-plan.md`. They may run in parallel. Key coordination notes:

- **Code overlap: none.** This plan is 100% backend; the hardening plan is 100% frontend. Zero source files are touched by both plans. The HTTP contract between frontend and backend is unchanged by both.
- **Context-doc overlap: high.** Both plans append entries to `context/decisions.md` and `context/log.md`. Run the doc-update steps **last** so any merge conflict is mechanical ("keep both entries"). `context/bug-corrections.md` is touched only by this plan. `context/map.md` is touched only by the hardening plan.
- **Behavioral independence.** All verification steps in this plan work against the current frontend (no contract changes either way).
- **Deployment order (recommended).** Ship the hardening plan first; verify in production. This migration ships next.
- **Spurious failure mode to watch.** If this migration is mid-flight with a missed `await` (returning a coroutine instead of data), the frontend's smoke tests (run as part of the hardening plan's verification) could fail spuriously. Verify each plan against a deploy that does NOT include the other's in-flight changes.
