# Plan: Fix reviews stuck in "reviewing" (Bug #1) + save framework earlier (Bug #2)

## Context

**Why this change:** Call reviews keep getting stuck in the `reviewing` status for 15–20+ minutes. The previous fix (LLM 120s timeout, a 50-min Celery soft limit, a 90-min stuck-review "reaper", and a Retry button) is deployed correctly — the active `backend/Procfile` has the `-B` beat flag, so the reaper *does* run — but it **isn't working in practice for two reasons**:

1. **The safety nets are tuned 3–5× too slow.** The reaper only fails a review after **5400s / 90 min** of no progress (`tasks.py:19`), and the Celery soft limit is **3000s / 50 min** (`celery_app.py:13`). A review stuck for 15–20 min is nowhere near either threshold, so from the user's perspective it just hangs. The limits are high on purpose: a *legitimate* transcription can poll up to **1800s / 30 min** (`transcriber.py:9`), so a blanket low limit would kill slow transcriptions. The fix must be **phase-aware** — aggressive on the fast `reviewing` phase, generous on `transcribing`.

2. **A hung LLM call blocks the worker, not just the row.** `reviewer.review_call()` is a synchronous, blocking loop of `llm.invoke()` calls (`reviewer.py`). If the per-request 120s timeout isn't honored (e.g. a custom `base_url`/streaming provider), the call never returns. The reaper can mark the *database row* failed, but the *worker process* stays blocked, so the existing auto-retry never fires and new uploads back up behind it. We need a **hard wall-clock timeout** around the review phase so the hang actually **raises**, which feeds the existing `self.retry()` path.

**Bug #2 relationship (the user's framing):** `template_id` is saved at **upload** (`upload.py:97`), but the full `framework` snapshot (`{template_name, template_id, criteria}`) is only written on **success** (`tasks.py:111`). So a failed/stuck review has `framework = null` and Retry must fall back to `template_id`. The user wants the framework **saved at upload** so failed reviews carry it, making `framework` the single source of truth and the standalone `template_id` column redundant.

**Intended outcome:** A review that hangs in `reviewing` reliably **auto-retries twice and then lands in `failed` within ~15 min** (surfacing the existing Retry button), the worker is never permanently starved, legitimate slow transcriptions are never falsely failed, and every review carries its full `framework` from the moment it's uploaded.

## Decisions already made (with the user)

- **Fix depth:** Reaper tuning **+** worker-unblock (hard per-phase timeout).
- **Bug #2:** Save the framework earlier; auto-retry twice before finally failing and letting the user know.

## Decisions resolved here (recommended defaults, no further input needed)

- **Per-attempt review timeout = 240s** so the retry path *itself* meets the <15-min target (3×240 + 2×10 ≈ 12.5 min to terminal `failed`), with the reaper as a pure backstop. 240s is generous for a healthy multi-criterion review (normal reviews finish in tens of seconds).
- **Do NOT add `app.control.revoke(terminate=True)` to the reaper.** With `task_acks_late=True` + `task_reject_on_worker_lost=True`, terminating mid-task triggers redelivery that fights the reaper. The per-phase timeout is the correct in-process unblock; the reaper stays a pure DB-state backstop for rows whose worker is already gone.
- **`framework` becomes the single source of truth**, saved at upload. Stop populating the standalone `template_id` column for **new** rows; keep the column nullable for legacy/backward-compat (no risky migration now; an optional drop can come later once legacy rows age out). This honors "don't store it twice" going forward with zero migration risk.

---

## Part 1 — Phase-aware reaper (deterministic backstop)

**`backend/tasks.py`**
- Replace the single `_get_stuck_threshold_seconds()` with a **per-status** resolver and defaults:
  - `pending` → `STUCK_PENDING_THRESHOLD_SECONDS` = **300** (5 min)
  - `transcribing` → `STUCK_TRANSCRIBING_THRESHOLD_SECONDS` = **2100** (35 min; above the 1800s poll ceiling + margin)
  - `reviewing` → `STUCK_REVIEWING_THRESHOLD_SECONDS` = **720** (12 min)
  - Stop reading the old `STUCK_REVIEW_THRESHOLD_SECONDS` (document as deprecated — honoring it would re-introduce the single-threshold bug).
- Refactor `reap_stuck_reviews()` to **iterate `storage.IN_PROGRESS_STATUSES`**, compute a per-status cutoff, and call the existing `storage.list_stuck_reviews(cutoff, statuses=(status,))` (already supports a `statuses` arg — reuse it). Keep `guard_terminal=True` and the per-row failure logging.

**`backend/celery_app.py`**
- Lower `REAP_INTERVAL_SECONDS` default **600 → 120** (run every 2 min). With the 720s `reviewing` threshold, worst-case detection is ~14 min — inside the 15-min target. Cost is one indexed query per status; negligible. Update the inline "every 10 minutes" comment.
- The `1800 < soft(3000) < hard(3300) < 3600` ordering invariant is **unchanged** (soft/hard limits untouched). Add a sentence cross-referencing the new `REVIEW_PHASE_TIMEOUT_SECONDS` as the finer in-process bound that fires long before the soft limit.

## Part 2 — Worker unblock (hard per-phase timeout)

**`backend/tasks.py`**
- Add `_review_call_with_timeout(transcript, criteria, timeout_s)` using `concurrent.futures.ThreadPoolExecutor(max_workers=1)` + `future.result(timeout=timeout_s)`; on `TimeoutError`, call `ex.shutdown(wait=False)` (do **not** block on the orphan thread) and raise a plain `TimeoutError`.
  - **Why ThreadPoolExecutor, not SIGALRM:** cross-platform (dev is Windows, prod is Linux/Railway) so behavior matches in both; SIGALRM is Unix-only and interacts badly with the active asyncio loop. Accepted trade-off (note in a code comment): the orphan worker thread keeps running until `llm.invoke`'s own 120s timeout (+1 internal retry ≈ 240s) fires, but **the Celery task slot is freed immediately** because the task raises and acks.
- Add `_get_review_phase_timeout_seconds()` reading `REVIEW_PHASE_TIMEOUT_SECONDS` (default **240**).
- In `_run()`, replace the direct `reviewer.review_call(transcript, criteria)` call (`tasks.py:105`) with `_review_call_with_timeout(...)`. The raised `TimeoutError` is a generic `Exception`, so it hits the existing `except Exception → self.retry()` block (`tasks.py:158`) — **no exception-handler change needed**. `TimeoutError` is intentionally *not* `SoftTimeLimitExceeded`, so it retries (twice) rather than failing immediately.

**`backend/modules/reviewer.py`** — no change (kept pure; the timeout wraps it from `tasks.py`).
**`backend/modules/llm_config.py`** — no change; the existing `timeout=120.0` / `max_retries=1` is the inner bound that eventually kills the orphan thread. Note this as belt-and-suspenders.

**Auto-retry-twice requirement:** already satisfied by the existing `@app.task(bind=True, max_retries=2, default_retry_delay=10)` + `self.retry()` → after 2 retries → `_fail_in_new_loop` marks `failed`. Part 2 simply makes the hang *raise* so this path actually runs. The frontend already renders the `failed` state + Retry button (user is "let know").

## Part 3 — Save framework at upload (Bug #2)

**`backend/routers/upload.py`**
- Import `get_template`. After resolving `effective_template_id` (~line 97), fetch the template and set the snapshot **before** `save_review`:
  ```python
  template = await get_template(effective_template_id)
  if template is None:
      raise HTTPException(status_code=400, detail="Review template not found.")
  record["framework"] = {
      "template_name": template.get("name", ""),
      "template_id": effective_template_id,
      "criteria": template.get("criteria", []),
  }
  ```
- **Stop setting** the standalone `record["template_id"]` for new rows (framework now carries it). `storage._to_row` already maps `framework`, so no storage change.

**`backend/tasks.py` `_run()`**
- Move the `get_review` fetch **before** template resolution, then read criteria framework-first with a legacy fallback:
  ```python
  framework = review.get("framework") or {}
  criteria = framework.get("criteria")
  template_name = framework.get("template_name", "")
  if not criteria:  # legacy row predating upload-time framework
      template = await get_template(template_id)
      if not template:
          await storage.update_review_status(review_id, "failed",
              error_message="Template not found and no persisted framework")
          return
      criteria, template_name = template["criteria"], template.get("name", "")
  ```
- Keep writing `review["framework"]` on completion (idempotent — same value). Keep the `template_id` task param for the legacy fallback path.

**`backend/routers/reviews.py` retry endpoint**
- Prefer the persisted framework; keep a legacy fallback so old `template_id`-only failed rows still retry:
  ```python
  framework = review.get("framework") or {}
  template_id = framework.get("template_id") or review.get("template_id")
  if not template_id and not framework.get("criteria"):
      raise HTTPException(status_code=400, detail="This review predates retry support and can't be resubmitted. Please re-upload the call.")
  ```
- Because `_run()` now prefers `framework.criteria`, a retry no longer depends on `get_template` succeeding (resilient to a since-deleted template) — an improvement.

**Backward-compat:** legacy rows with `template_id` but no `framework` are handled by the runtime fallbacks above; no data migration required.

---

## Files to modify
- `backend/tasks.py` — per-status thresholds, refactored `reap_stuck_reviews`, `_review_call_with_timeout` + `_get_review_phase_timeout_seconds`, framework-first criteria + review-fetch reordering.
- `backend/celery_app.py` — `REAP_INTERVAL_SECONDS` 600→120; comment updates.
- `backend/routers/upload.py` — build & save `framework` at upload; stop setting standalone `template_id`.
- `backend/routers/reviews.py` — retry prefers persisted framework.
- No new migration required (recommended path). No changes to `storage.py`, `reviewer.py`, `llm_config.py`.

## Env vars (document in `decisions.md` / `.env.example` if present)
`STUCK_PENDING_THRESHOLD_SECONDS=300`, `STUCK_TRANSCRIBING_THRESHOLD_SECONDS=2100`, `STUCK_REVIEWING_THRESHOLD_SECONDS=720`, `REAP_INTERVAL_SECONDS=120` (was 600), `REVIEW_PHASE_TIMEOUT_SECONDS=240`. Deprecate `STUCK_REVIEW_THRESHOLD_SECONDS`. Set these in Railway on deploy.

## Context-file updates (per CLAUDE.md conventions)
- `context/log.md` — phase-aware reaper, hard review timeout, upload-time framework, framework-as-source-of-truth.
- `context/map.md` — new `tasks.py` helpers; `upload.py` now builds the framework snapshot.
- `context/decisions.md` — reaper = DB backstop vs timeout = worker unblock; ThreadPoolExecutor over SIGALRM (Win dev/Linux prod parity) + orphan-thread trade-off; `framework` is the single source of truth, standalone `template_id` no longer populated for new rows (kept nullable for legacy); skip reaper-revoke; chosen timeout/threshold values.
- `context/bug-corrections.md` — mark the "stuck reviewing 15–20 min" bug fixed.
- `context/deferredwork.md` — note `review_call` has no per-criterion checkpoint (a retry re-runs all criteria; acceptable at low criterion count); optional future drop of the `template_id` column once legacy rows age out.

## Verification (end-to-end)

Run the worker locally from `backend/`: `py -m celery -A celery_app worker -B --loglevel=info` (env activated; `-B` matches the Procfile). The timeout mechanism is cross-platform, so Windows dev exercises the real prod path.

1. **Hang raises fast:** unit-test `_review_call_with_timeout` with `reviewer.review_call` monkeypatched to `time.sleep(30)` and `timeout_s=2` → asserts `TimeoutError` within ~2s (proves the wrapper returns control while the sleep thread lingers).
2. **Auto-retry twice → failed:** upload/enqueue with `REVIEW_PHASE_TIMEOUT_SECONDS=2`; watch logs for "Retrying … attempt 1 of 2", "attempt 2 of 2", "Max retries exceeded … marking as failed"; confirm the row ends `failed` within ≈3×2 + 2×10s.
3. **Retry button:** `GET /reviews/{id}` shows `status=="failed"`; click Retry → `POST /reviews/{id}/retry` flips to `pending`, clears error, re-enqueues; with a normal timeout it completes.
4. **No false reaping of transcription:** assert `_get_stuck_threshold_seconds("transcribing")==2100` and `("reviewing")==720`, and that `reap_stuck_reviews` queries each status with its own cutoff (assert the cutoff passed to `list_stuck_reviews`). Confirms a row in `transcribing` isn't reaped before 35 min while a `reviewing` row is reaped at 12.
5. **Framework at upload:** upload, then immediately `GET /reviews/{id}` (still `pending`/`transcribing`) → assert `framework.criteria` is populated; force a failure (tiny timeout) → confirm the failed row still carries `framework.criteria`.
6. **Legacy regression:** craft a row with `template_id` set + `framework` null, enqueue → `_run()` falls back to `get_template` and still completes.

**Production (Railway):** same mechanism (no platform-specific code); set the new env vars; confirm beat runs embedded (`-B`) on the single worker. No migration to apply for the recommended path.
