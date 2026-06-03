# Plan: Feature #4 — Call Outcome Tracking

## Context

From `context/bug-corrections.md` (Major feature #4): we want to start tracking the
**outcome** of each call so the team can see how calls progress through the pipeline.

Three capabilities are required:
1. **Upload screen** — optionally select an outcome when uploading a call (must NOT be required).
2. **Review/results screen** — change the outcome of an existing call.
3. **History screen** — filter past reviews by outcome, exactly like the existing
   advisor and firm filters.

Outcome is a fixed enum of exactly these strings (note the inconsistent casing — copy verbatim):
- `Lost after first call`
- `No follow-up booked`
- `Follow-up Booked`
- `Lost after follow-up`
- `Closed`

Outcome is metadata about a call, independent of the processing pipeline, so it is editable
at any time and stored alongside the other call metadata (advisor / firm / prospect).

### Confirmed product/UX decisions
- **Results-screen edit:** auto-save on select (optimistic update; revert + inline error on failure). No Save button — mirrors the app's existing single-field edits (`setUserActive`).
- **History row display:** small color-coded outcome pill per row (text color, not card fill, per `DESIGN.md`):
  - `Closed` → green
  - `Lost after first call` / `Lost after follow-up` → red
  - `Follow-up Booked` → blue/info
  - `No follow-up booked` → **yellow**
  - no outcome → render nothing
- **History filter:** fixed canonical list (lifecycle order) + an explicit **"No outcome set"** option (to find untagged calls) + "All". Always available, even before any call has a given outcome.

### Architecture alignment (from `decisions.md`)
- No RLS — access control stays in the FastAPI layer (gate the new PATCH like `GET /reviews/{id}`).
- DB schema changes ship as a dated manual SQL file in `backend/migrations/`, applied in the Supabase SQL Editor before deploy, and noted in `deferredwork.md`.
- Backend first, then wire up the frontend.
- Store the canonical label string (no slug mapping) — consistent with firm/advisor being plain strings.

---

## Storage model decision

Add a new **top-level `call_outcome` column** to the `reviews` table, but surface it
**inside the `metadata` sub-dict** in `_from_row`. This way `_review_summary`, the list
endpoint, and the detail endpoint all expose `metadata.call_outcome` with zero extra wiring —
exactly how `advisor_name` / `firm` / `prospect_name` already flow. `_to_row` reads it back
out of `metadata`. No DB `CHECK` constraint: the enum is validated in the app layer and
single-sourced in Python/JS, so changing labels later needs no second migration.

---

## Implementation steps (backend first)

### 1. Migration — `backend/migrations/2026-05-29_add_call_outcome.sql` (new)
```sql
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS call_outcome TEXT;
```
Nullable, no default (null = "no outcome set" — the legacy/in-progress state, no backfill needed).
Header comment in the style of `2026-05-26_add_has_set_password.sql`, noting validation lives
in the app layer (intentionally no DB CHECK constraint).

### 2. Canonical enum — `backend/modules/ingestion.py`
- Add module-level `CALL_OUTCOMES: list[str]` with the 5 exact strings in lifecycle order.
- Add a `typing.Literal[...]` alias `CallOutcome` for Pydantic reuse, plus an import-time
  `assert set(CALL_OUTCOMES) == set(get_args(CallOutcome))` to keep the two in sync.
- Extend `create_record(...)` with `call_outcome: str | None = None`, placed into the returned
  `metadata` sub-dict as `"call_outcome": call_outcome` (keeps metadata construction in one place
  and keeps `_to_row` symmetric).

### 3. Storage mapping + update helper — `backend/modules/storage.py`
- `_to_row` (line ~22): add `"call_outcome": metadata.get("call_outcome")`.
- `_from_row` (line ~41): add `"call_outcome": row.get("call_outcome")` **inside the `metadata` dict**.
- Add a new partial-update helper mirroring `update_review_status` (line ~104):
  ```python
  async def update_review_outcome(review_id: str, call_outcome: str | None) -> None:
      client = await get_client()
      patch = {"call_outcome": call_outcome}   # always set, even to None (clearing is allowed)
      await client.table("reviews").update(patch).eq("id", review_id).execute()
  ```
  Deliberately always writes the key (unlike `update_review_status`'s conditional adds) so
  selecting "Not set" clears the column back to NULL.

### 4. Upload accepts the optional field — `backend/routers/upload.py`
- Add Form param `call_outcome: str = Form(None)`.
- Validate when present: `if call_outcome is not None and call_outcome not in CALL_OUTCOMES: raise HTTPException(400, "Invalid call outcome.")` (Form fields can't use Pydantic `Literal` directly).
- Pass into `create_record(..., call_outcome=call_outcome)`. It then flows metadata → `_to_row` → DB.
  `UploadPage.handleSubmit` already forwards arbitrary FormData fields, so no other upload changes.

### 5. PATCH endpoint — `backend/routers/reviews.py`
- Import `BaseModel`, `CallOutcome` (from `modules.ingestion`), and `update_review_outcome`.
- Add `class OutcomeBody(BaseModel): call_outcome: CallOutcome | None = None` (null clears; invalid
  strings → automatic 422).
- Add `@router.patch("/reviews/{review_id}/outcome")`:
  - `get_review`; 404 if `None`.
  - Access gate identical to `GET /reviews/{id}`: `if user["role"] == "financial_advisor" and not _fa_can_access(review, user): raise 404`.
  - `await update_review_outcome(review_id, body.call_outcome)`.
  - Re-fetch via `get_review` and return the **full** review (same shape as `GET /reviews/{id}`) so the
    Results page can sync its state.
  - No status restriction — outcome is editable regardless of review status.

### 6. Frontend enum module — `frontend/src/lib/outcomes.js` (new)
- `export const OUTCOME_OPTIONS = [{ value, label }]` for the 5 strings (value === label).
- `export const NO_OUTCOME = '__none__'` sentinel.
- `export const OUTCOME_FILTER_OPTIONS = [{ value: '', label: 'All' }, ...OUTCOME_OPTIONS, { value: NO_OUTCOME, label: 'No outcome set' }]`.
- `export function outcomeColorClass(outcome)` → returns a CSS class key for the badge color
  (green=Closed, red=both Lost, blue=Follow-up Booked, yellow=No follow-up booked). Single source
  of truth for the color mapping.

### 7. API helper — `frontend/src/services/api.js`
- Add `updateReviewOutcome(id, callOutcome)` mirroring `setUserActive`: `PATCH /reviews/${id}/outcome`
  with JSON body `{ call_outcome: callOutcome }` (pass `null` to clear). Place in the Reviews section.

### 8. Upload form field — `frontend/src/components/UploadForm.jsx`
- `const [callOutcome, setCallOutcome] = useState('')`.
- New `.upload-form__field` block after Prospect Name: label "Call Outcome (optional)" +
  `SearchableSelect` (size `md`), options `[{ value: '', label: 'Not set' }, ...OUTCOME_OPTIONS]`,
  `value={callOutcome}`, `onChange={setCallOutcome}`. Not added to `validate()` (optional).
- In `handleSubmit`, after existing appends: `if (callOutcome) formData.append('call_outcome', callOutcome)`.

### 9. Results-screen edit — `frontend/src/pages/ResultsPage.jsx` + `frontend/src/components/ReviewResults.jsx`
- **ResultsPage** (owns `review` state):
  - Add `isSavingOutcome` + `outcomeError` state.
  - `handleOutcomeChange(newOutcome)`: snapshot current review → optimistic
    `setReview(prev => ({ ...prev, metadata: { ...prev.metadata, call_outcome: newOutcome || null } }))`
    → `await updateReviewOutcome(id, newOutcome || null)`; on success replace state with returned review;
    on failure revert to snapshot + set `outcomeError`.
  - Pass `onOutcomeChange`, `isSavingOutcome`, `outcomeError` to `<ReviewResults>`.
- **ReviewResults**: add a 5th `.review-results__meta-item` "Outcome" whose value is a `SearchableSelect`
  (options `[{ value: '', label: 'Not set' }, ...OUTCOME_OPTIONS]`,
  `value={metadata?.call_outcome || ''}`, `onChange={onOutcomeChange}`, `disabled={isSavingOutcome}`),
  with `outcomeError` rendered inline below. Existing 4 read-only meta items unchanged.

### 10. History filter + row badge — `frontend/src/pages/HistoryPage.jsx`, `frontend/src/components/ReviewList.jsx` (+ CSS)
- **HistoryPage**: add `const [filterOutcome, setFilterOutcome] = useState('')`. New
  `.history-page__filter--select` block (alongside Advisor/Firm) with `SearchableSelect size="sm"`
  using the static `OUTCOME_FILTER_OPTIONS` (no `useMemo`). Pass `filterOutcome` to `<ReviewList>`.
- **ReviewList**: accept `filterOutcome`. In the `.filter()` predicate:
  - `filterOutcome === NO_OUTCOME` → keep only rows where `!r.metadata?.call_outcome`;
  - else if `filterOutcome` → keep only `r.metadata?.call_outcome === filterOutcome`.
  - Add `r.metadata?.call_outcome` to the `searchable` join (free-text search matches outcome).
  - Render a small outcome pill in each row when `metadata?.call_outcome` is present, colored via
    `outcomeColorClass(...)`. Add `.review-list-item__outcome--{green|red|blue|yellow}` classes in
    `ReviewList.css` reusing the **existing** green/red/yellow color tokens from `tokens.css` (the same
    ones `ScoreCard` uses) plus the info/blue token; colors applied as text, not card fills (per `DESIGN.md`).

---

## Edge cases
- **Clearing outcome:** upload omits empty field (→ null); PATCH body accepts `null`; `update_review_outcome` always writes the key; "Not set" on Results sends `null`.
- **Legacy / in-progress / failed reviews:** `metadata.call_outcome` is `None`; all displays guard with `|| '—'` or conditional render; the "No outcome set" filter surfaces them; outcome editable regardless of status. In-progress/failed history rows stay non-interactive but can still show a badge.
- **FA vs BDS on PATCH:** FA gated by `_fa_can_access` (firm match + `uploader_role == 'financial_advisor'`); cross-firm/other → 404 (consistent with detail/delete). BDS unrestricted.
- **Invalid enum:** upload → 400; PATCH → 422 via `Literal`. Frontend only ever sends canonical strings (defense in depth).
- **Optimistic race:** failed auto-save reverts to snapshot + inline error so UI never silently diverges.
- **Enum drift:** frontend `OUTCOME_OPTIONS` and backend `CALL_OUTCOMES`/`Literal` are two copies of the same 5 strings — copy byte-identical; the import-time `assert` guards the backend pair.

---

## Files touched
**Backend:** `backend/migrations/2026-05-29_add_call_outcome.sql` (new), `backend/modules/ingestion.py`, `backend/modules/storage.py`, `backend/routers/upload.py`, `backend/routers/reviews.py`
**Frontend:** `frontend/src/lib/outcomes.js` (new), `frontend/src/services/api.js`, `frontend/src/components/UploadForm.jsx`, `frontend/src/pages/ResultsPage.jsx`, `frontend/src/components/ReviewResults.jsx` (+ `.css`), `frontend/src/pages/HistoryPage.jsx`, `frontend/src/components/ReviewList.jsx` (+ `.css`)
**Docs:** `context/log.md` (always), `context/map.md` (new `outcomes.js`, new endpoint/migration), `context/decisions.md` (new entry), `context/deferredwork.md` (migration must be applied)

---

## Verification (no backend test suite exists — manual end-to-end)
1. Run `2026-05-29_add_call_outcome.sql` in the Supabase SQL Editor.
2. Start app (`py -m uvicorn` backend + `npm run dev` frontend, per `start.ps1`).
3. **BDS, no outcome:** upload a call without selecting outcome → saves; history shows no badge; Results shows "Not set".
4. **BDS, with outcome:** upload selecting "Follow-up Booked" → blue badge in history; Results shows it selected.
5. **Results edit:** change to "Closed" → dropdown updates instantly, PATCH 200, reload persists; select "Not set" → clears, reload still cleared.
6. **History filter:** filter "Closed" → only matching rows; "No outcome set" → only untagged rows; free-text "follow-up" matches.
7. **Color check:** confirm Closed=green, Lost*=red, Follow-up Booked=blue, No follow-up booked=yellow.
8. **FA access:** FA can set/change outcome on own-firm review; FA PATCH on a BDS/other-firm review id → 404.
9. **Failure path:** simulate offline, change outcome on Results → value reverts + inline error.
