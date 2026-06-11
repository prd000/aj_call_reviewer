# Fix: reviews stuck in "reviewing" forever (Bug #3)

## Context

A review (`cb2ba839…`) sat in `status="reviewing"` for 1+ hour with `review_results={}`, `framework=null`, and — the tell — `error_message=null`. Transcription had succeeded (transcript + `speaker_map` were checkpointed), so the task was wedged inside `reviewer.review_call()` at `tasks.py:71`.

Root cause is two missing guards:
1. **No LLM request timeout.** `get_llm()` (`llm_config.py:52`) builds `ChatOpenAI` with no `timeout`/`max_retries`, so a stalled DeepSeek call (the default provider) blocks `llm.invoke()` indefinitely. No exception is ever raised, so `tasks.py`'s `except` never writes `failed`.
2. **No Celery task time limit.** `celery_app.py` sets no `task_soft_time_limit`/`task_time_limit`, so nothing force-fails a wedged task. The 3600s `visibility_timeout` redelivers it after an hour; it resumes from the checkpoint and re-hangs — a silent loop.

**Outcome wanted:** a hung review fails fast with a real `error_message` (UI stops spinning), and any review that *still* ends up stranded is auto-recovered by a periodic reaper. All library facts below were verified by a Plan agent against the installed versions (`langchain-openai 1.2.1`, `openai 2.33.0`, `celery 5.6.3`).

**Decisions incorporated (this session):**
- **`LLM_MAX_RETRIES = 1`** (user choice) — one in-library retry for resilience to a transient blip. Tradeoff accepted: a *pathologically* slow-but-legit job (every call near the 120s ceiling) can reach the hard limit and redeliver; survivable via checkpoint.
- **Self-heal sweep included now** (not deferred), with the hard constraint that it **queries only in-progress rows server-side** — `status IN (...)` + stale `updated_at`, narrow column select — and never scans the hundreds of completed reviews or pulls transcript/review payloads.

---

## Part A — LLM request timeout + bounded retries (PRIMARY fix)

**File:** `backend/modules/llm_config.py`

- Add module constants `_DEFAULT_LLM_REQUEST_TIMEOUT = 120.0`, `_DEFAULT_LLM_MAX_RETRIES = 1`.
- Add private env helpers mirroring the file's existing `.strip()`-everywhere defensive style:
  - `_get_request_timeout()` → parse `LLM_REQUEST_TIMEOUT` as float; fall back to default on empty/`ValueError`; **clamp `<= 0` to the default** (httpx treats `0` as *no timeout* — that would reintroduce the bug).
  - `_get_max_retries()` → parse `LLM_MAX_RETRIES` as int; fall back on empty/`ValueError`; clamp `< 0` to `0`.
- In `get_llm()`, after the `kwargs` dict is built, add `kwargs["timeout"] = _get_request_timeout()` and `kwargs["max_retries"] = _get_max_retries()` so both flow through the existing `return ChatOpenAI(**kwargs)`. **No signature change** — `review_call`, `generate_major_focus`, `identify_speakers`, and both chat paths all inherit the timeout for free.

Verified: `ChatOpenAI(timeout=<float>, max_retries=<int>)` is correct; the instance exposes `.request_timeout` and `.max_retries`. A plain float caps all httpx phases (connect/read/write) — sufficient for the hung-read failure mode; no `httpx.Timeout` tuple needed.

---

## Part B — Celery soft/hard task time limits (BACKSTOP)

**File:** `backend/celery_app.py`

- Parse `CELERY_TASK_SOFT_TIME_LIMIT` (default `3000`) and `CELERY_TASK_TIME_LIMIT` (default `3300`) from env (int + fallback).
- Add `task_soft_time_limit` and `task_time_limit` to the existing `app.conf.update(...)`.
- Add a loud comment stating the **ordering invariant** and cross-referencing `transcriber._POLL_MAX_ATTEMPTS`:

  `1800 (transcription poll ceiling) < soft (3000) < hard (3300) < 3600 (visibility_timeout)`

  Soft too low would kill legitimate long transcriptions; both must stay under `visibility_timeout` so a hard-killed task redelivers rather than double-runs. This extends the coupling already documented in the 2026-06-08 decision.

Backstop value: the soft limit also catches a hung **Rev.ai** HTTP call (the `rev_ai` SDK has no per-call timeout), which Part A does not cover.

---

## Part C — Graceful soft-timeout handling + shared cleanup helper

**File:** `backend/tasks.py`

- Extend the import: `from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded`.
- **Refactor** the inline `_cleanup()` (currently nested in the `MaxRetriesExceeded` branch) into a module-level `async def _mark_failed_and_cleanup(review_id, error_message, *, guard_terminal=False)`: writes `failed` via `storage.update_review_status(..., guard_terminal=guard_terminal)`, then defensively re-fetches the row and deletes the recording in a `try/except`. It does **not** reset the supabase client (the caller owns the loop).
- Add a small sync helper `_fail_in_new_loop(review_id, error_message, *, guard_terminal=False)` that resets `_supabase_client._client = None`, then `asyncio.run(_mark_failed_and_cleanup(...))` inside a `try/except` — used by the two task-failure paths that run after the main loop is dead.
- Rework the outer handler around `asyncio.run(_run())` into an **ordered** chain (specific first, because `SoftTimeLimitExceeded` subclasses `Exception` directly):
  - `except SoftTimeLimitExceeded:` → log, then `_fail_in_new_loop(review_id, f"Task exceeded soft time limit of {app.conf.task_soft_time_limit}s")`. **Terminal — must NOT call `self.retry`** (retrying re-runs the same long work and re-wedges). This handler is the loop-breaker: a redelivered hung task now writes a terminal `failed` instead of re-hanging.
  - `except Exception as exc:` → existing retry logic unchanged, with the `MaxRetriesExceededError` branch now calling `_fail_in_new_loop(review_id, str(exc))`.
- Leave the happy-path / Bug #2 idempotency + checkpoint logic untouched. The non-fatal `major_focus` `try/except` stays as-is (if a soft-timeout fires during that final step, the review is essentially done and proceeds to save `complete` — acceptable).

---

## Part D — Self-heal reaper (sweep) — server-side filtered

### D1. Migration — `updated_at` heartbeat
**New file:** `backend/migrations/2026-06-09_add_reviews_updated_at.sql` (manual-apply, per project convention).
- `ALTER TABLE reviews ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();`
- Backfill `UPDATE reviews SET updated_at = created_at ...` (runs *before* the trigger, so it isn't overwritten).
- `CREATE OR REPLACE FUNCTION set_reviews_updated_at()` (plpgsql, `NEW.updated_at = now(); RETURN NEW;`) + `BEFORE UPDATE ... FOR EACH ROW` trigger.

DB-enforced heartbeat: every status write (`transcribing`→checkpoint→`reviewing`→`complete`) bumps `updated_at`, so a row making progress stays fresh and a stranded row goes stale. **No app write-site changes** and **no change to `_to_row`/`_from_row`** (the app never sets `updated_at`; the trigger/default own it).

### D2. Storage helper — narrow, filtered query (honors the user's constraint)
**File:** `backend/modules/storage.py` (modeled on `list_reviews`, `storage.py:81`).
- Add `IN_PROGRESS_STATUSES = ("pending", "transcribing", "reviewing")`.
- Add `async def list_stuck_reviews(cutoff_iso, statuses=IN_PROGRESS_STATUSES)`:
  ```
  client.table("reviews")
    .select("id, status, storage_path, created_at, updated_at")   # narrow columns only
    .in_("status", list(statuses))                                # never touches 'complete'/'failed'
    .lt("updated_at", cutoff_iso)                                 # only stale rows
    .execute()
  ```
  Returns `result.data or []`. This is the whole point of the user's requirement: row-filtered **and** column-narrowed — it never scans completed reviews or fetches transcript/review_results payloads.

### D3. Reaper task
**File:** `backend/tasks.py`.
- Add `_get_stuck_threshold_seconds()` env helper (`STUCK_REVIEW_THRESHOLD_SECONDS`, default `5400` = 90 min).
- Add `@app.task(bind=True) def reap_stuck_reviews(self)`:
  - `asyncio.run(_run())` where `_run()` resets `_supabase_client._client = None`, computes `cutoff = (datetime.now(timezone.utc) - timedelta(seconds=threshold)).isoformat()`, calls `storage.list_stuck_reviews(cutoff)`, and for each row calls `await _mark_failed_and_cleanup(rid, f"Auto-failed by stuck-review reaper: no progress for >{threshold}s (was '{row['status']}')", guard_terminal=True)`.
  - `guard_terminal=True` protects against the SELECT→reap race (a row that completed in between is skipped).
  - Wrap the whole run in `try/except` + `logger.error(..., exc_info=True)` so a reaper hiccup never crashes the beat loop. Log the count found/reaped (`logger.warning`).
- Threshold rationale (default 5400s): must exceed the longest legit no-write gap — transcription holds `updated_at` for up to 1800s — and sit safely above one `visibility_timeout` (3600s) redelivery cycle, so an in-flight job is never falsely reaped. With Parts A–C in place, an actively-stuck task already fails at the 3000s soft limit; the reaper's real job is rows with **no** owning task (lost message, worker was down). Env-tunable.

### D4. Beat schedule + process
**File:** `backend/celery_app.py` — add:
```
app.conf.beat_schedule = {
    "reap-stuck-reviews": {
        "task": "tasks.reap_stuck_reviews",
        "schedule": float(os.environ.get("REAP_INTERVAL_SECONDS", "600")),  # 10 min
    },
}
```
**File:** `backend/Procfile` — run beat **embedded in the existing worker** (no new Railway service, no extra cost): change the `worker` line to
`worker: celery -A celery_app worker -B --loglevel=info`
Recommended because the deployment is single-worker and reaping is idempotent. Note in docs: if worker replicas are ever scaled > 1, split beat into its own single-replica `beat: celery -A celery_app beat --loglevel=info` process to avoid duplicate scheduling. (If the embedded scheduler can't write its `celerybeat-schedule` file on Railway, add `--schedule=/tmp/celerybeat-schedule`.)

---

## Constants (all env-overridable)

| Env var | Default | Where |
|---|---|---|
| `LLM_REQUEST_TIMEOUT` | `120.0` (s, all-phase) | `llm_config.py` |
| `LLM_MAX_RETRIES` | `1` | `llm_config.py` |
| `CELERY_TASK_SOFT_TIME_LIMIT` | `3000` | `celery_app.py` |
| `CELERY_TASK_TIME_LIMIT` | `3300` | `celery_app.py` |
| `STUCK_REVIEW_THRESHOLD_SECONDS` | `5400` | `tasks.py` |
| `REAP_INTERVAL_SECONDS` | `600` | `celery_app.py` |

Invariant: `1800 < 3000 < 3300 < 3600`. Worst-case task wall-time with `max_retries=1` ≈ 1800 (transcribe) + ~1440 (review) + ~240 (focus) ≈ **3480s** — only reached if *every* call sits at the 120s ceiling (a degenerate near-failure). Realistic legit jobs finish well under 3000s. If false hard-limit trips are ever observed, lower `LLM_REQUEST_TIMEOUT` to ~90 or drop `LLM_MAX_RETRIES` to 0.

---

## Tests (`backend/tests/`)

Reuse the existing `FakeReviewDB` / `_install` / `_attempt` / `_make_query_recorder` harness in `test_tasks.py`.

1. **`test_tasks.py` — extend `test_celery_delivery_hardening_config()`** (or sibling): assert `task_soft_time_limit` and `task_time_limit` are set and `1800 < soft < hard < broker_transport_options["visibility_timeout"]`. Assert `"reap-stuck-reviews" in app.conf.beat_schedule`.
2. **`test_tasks.py` — new `test_soft_time_limit_fails_fast_no_retry()`**: `review_call = MagicMock(side_effect=SoftTimeLimitExceeded())`; patch `process_review_task.retry`; assert row ends `failed`, `retry.call_count == 0`, a `delete` event occurred, and the error message mentions the soft limit.
3. **`test_tasks.py` — new `test_reap_stuck_reviews()`**: stub `storage.list_stuck_reviews` to return two stuck rows; assert each is marked `failed` (`guard_terminal=True`) and its recording deleted; assert completed rows are never touched (the filter lives in the query layer).
4. **`test_tasks.py` — new `test_list_stuck_reviews_filters_server_side()`**: extend `_make_query_recorder` with `.select/.in_/.lt`; assert `list_stuck_reviews` issues `in_("status", [...])` + `lt("updated_at", cutoff)` and selects the **narrow column list** (no `transcript`/`review_results`). This directly guards the user's "don't scan all reviews" requirement.
5. **New `backend/tests/test_llm_config.py`**: (a) defaults → `ChatOpenAI.request_timeout == 120.0`, `.max_retries == 1`; (b) env overrides honored; (c) invalid/`"0"`/empty → safe default (never `0`/no-timeout). Construct a real `ChatOpenAI` (lazy, dummy key) or patch `langchain_openai.ChatOpenAI` in the module namespace.

Run from `backend/`: `py -m pytest tests/test_llm_config.py tests/test_tasks.py -q` (note: 3 `test_prompts_fidelity.py` failures are pre-existing/by-design per map.md).

---

## Docs to update (per CLAUDE.md)

- `context/bug-corrections.md` — add entry **3.** (stuck-in-`reviewing` symptom + root cause + fix).
- `context/decisions.md` — new top entry `## 2026-06-09 — Bug #3 fix: LLM/task timeouts + stuck-review reaper`, cross-referencing the 2026-06-08 idempotency entry and stating the time-limit ordering invariant and the heartbeat/reaper design.
- `context/log.md` — new top entry (root-cause paragraph + **Fix** + **Tests**).
- `context/map.md` — update `llm_config.py`, `celery_app.py`, `tasks.py`, `storage.py`, `tests/`, `migrations/`, and `Procfile` bullets (new helpers, reaper task, beat config, `list_stuck_reviews`, the migration, `-B`).
- `.env.example` — document the 6 vars + the `1800 < soft < hard < 3600` invariant.

---

## Deployment steps (call out to user)

1. Apply `backend/migrations/2026-06-09_add_reviews_updated_at.sql` in the Supabase SQL Editor **before** deploying.
2. Deploy backend (web + worker). The worker now runs embedded beat (`-B`).
3. (Optional) set any of the 6 env vars on the worker/web services to override defaults.

---

## Verification

**Automated:** the pytest suite above; confirm existing Bug #2 tests still pass.

**Manual — LLM-timeout path (any OS):** point the provider `base_url` at a TCP-accepting/never-responding host (or a local stub that sleeps > timeout), set `LLM_REQUEST_TIMEOUT=10`, upload a call. Expect `transcribing`→`reviewing`, the call raises within ~10s×(criteria+1), Celery retries resume from the checkpoint (verify Rev.ai is **not** re-submitted in logs), and after retries the row is `failed` with a non-empty `error_message` and the recording deleted.

**Manual — soft-limit + reaper (Linux/prefork):** set `CELERY_TASK_SOFT_TIME_LIMIT=20`, `CELERY_TASK_TIME_LIMIT=30` and make `review_call` block > 20s → worker logs `SoftTimeLimitExceeded` at ~20s, handler writes `failed` ("Task exceeded soft time limit of 20s"), recording deleted, **no retry, no loop**. Separately, set `STUCK_REVIEW_THRESHOLD_SECONDS=60`, `REAP_INTERVAL_SECONDS=30`, manually leave a row in `reviewing` with an old `updated_at` (or insert one), and confirm the reaper marks only that row `failed` within a cycle while leaving completed rows untouched.

**Regression:** a normal call with a real key + default limits still reaches `complete`, Major Focus still generates, no spurious `failed`.

---

## Deferred / future (note in `deferredwork.md`)

- **Rev.ai per-request timeout** — the `rev_ai` SDK calls are bounded only by the Celery soft limit; add explicit HTTP timeouts later.
- **Reaper re-enqueue instead of fail** — currently marks `failed` (clear, safe, stops the spinner); a future version could attempt one checkpoint-resume re-enqueue before failing.
- **Dedicated `beat:` service** — if worker replicas scale > 1.
