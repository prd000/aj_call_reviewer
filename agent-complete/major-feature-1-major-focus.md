# Major Feature #1 — "Major Focus" section

## Context

BDS users want a single, highest-leverage coaching takeaway surfaced prominently on each call review — "the one thing this advisor should focus on to get better results" — distinct from the broader Summary and the per-criterion feedback. Today a reviewer reads the whole report to infer the priority. This feature adds a **Major Focus** block directly beneath the Summary (on the Results screen and in the PDF) containing 1-2 LLM-written sentences tied to a specific framework criterion.

It is a **curation tool for BDS**: a BDS-only dropdown picks *which* framework criterion the focus targets, and an explicit **Generate** button (re)writes the focus text for that criterion via the LLM. Advisors see only the resulting text — no dropdown, no button. By default (and for freshly-processed calls), the focus auto-targets the criterion **dragging the overall score down the most** (largest `max_score − score` deficit), so a meaningful focus is always present before any BDS curates it.

### Decisions captured (from user)
- **Text source:** dedicated LLM call (new prompt), not reused criterion feedback.
- **Default target:** the criterion with the largest absolute point deficit (`max_score − score`); tie-break by lowest ratio, then first occurrence. This is "the score dragging overall down the most" since overall = Σscore / Σmax.
- **Regeneration:** explicit **Generate** button (not live on dropdown change), mirroring a deliberate action with a loading state.
- **Pattern:** follow the `call_outcome` precedent end-to-end (top-level column, partial-update storage fn, BDS-gated PATCH endpoint, LLM error classification mirrors the chat endpoint).

---

## Data model

Add one **top-level JSONB column** `major_focus` to `reviews` (nullable; NULL = none yet). Shape:

```json
{
  "criterion_id": "<framework criterion uuid>",
  "criterion_title": "Discovery & Needs Analysis",
  "text": "1-2 sentence focus...",
  "is_auto": true
}
```

- `criterion_id` is the stable join key (`framework.criteria[*].id`). `criterion_title` is denormalized so the PDF/frontend render without a lookup. `is_auto` = true when default-generated, false when BDS-set (lets the UI label it "Auto-selected").
- Stored top-level (not inside `review_results`) so it partial-updates cleanly via the same pattern as `update_review_outcome`. The full review dict surfaces it as `review["major_focus"]`. It is **not** added to `_review_summary` (History list doesn't need it).

**Migration:** `backend/migrations/2026-06-08_add_major_focus.sql`
```sql
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS major_focus JSONB;
```
No backfill (legacy reviews = NULL → section simply absent). Apply manually in Supabase SQL Editor before deploying; **add a note to `context/deferredwork.md`** and alert the user (manual migration step).

---

## Backend (edit first)

### 1. Prompt files — `backend/prompts/`
- `major_focus.system.txt` — instructs the model to write **exactly 1-2 sentences** of the single highest-leverage thing the advisor should do better on the named criterion; concrete, coaching tone, grounded in the call; no score, no preamble, no markdown.
- `major_focus.user.txt` — template formatted with `{criterion_title}`, `{criterion_description}`, `{success_condition}`, `{score}`, `{max_score}`, `{feedback}`, `{transcript}`. Loaded via `prompts.load_prompt` (caller `.format()`s), consistent with the externalized-prompt decision (2026-06-03).

### 2. `backend/modules/reviewer.py`
Add `generate_major_focus(transcript, criterion, category) -> str`:
- `criterion` = framework criterion dict (`title`/`description`/`success_condition`); `category` = matching review category dict (`score`/`max_score`/`feedback`).
- Builds prompt via `load_prompt("major_focus.system"/"major_focus.user")`, calls `get_llm(temperature=0.3)` (low temp for tight, deterministic coaching), returns stripped text.
- Mirror the existing API-key guard: raise `LLMUnavailableError` when no provider key (same class the chat path uses). Reuse `_format_transcript_labeled` for the transcript section.

Add a small pure helper `pick_default_focus_index(categories) -> int | None`:
- Returns `argmax(max_score − score)` over scored categories; tie-break lowest `score/max_score`, then first index. `None` if no scored categories. Unit-testable in isolation.

### 3. `backend/tasks.py` — default at review time
After `review_call` produces `categories` and the `framework` snapshot is set, compute the default focus:
- `idx = pick_default_focus_index(categories)`; if not None, resolve `criterion = framework["criteria"][idx]`, `category = categories[idx]`, call `generate_major_focus(...)`, and set `review["major_focus"] = {criterion_id, criterion_title, text, is_auto: True}` before the final `save_review`/status=complete.
- **Non-fatal**, like `identify_speakers`: wrap in try/except, log on failure, leave `major_focus` unset so the pipeline never fails on focus generation.

### 4. `backend/modules/storage.py`
- `_to_row()` / `_from_row()`: pass `major_focus` through (read/write the JSONB column; `_from_row` exposes `review["major_focus"]`).
- Add `update_review_major_focus(review_id, major_focus: dict | None)` — exact shape of `update_review_outcome` (always writes the key; `None` clears).

### 5. `backend/routers/reviews.py` — BDS-only PATCH endpoint
Add `MajorFocusBody(BaseModel)` with `criterion_id: str`. Add:
```
PATCH /reviews/{review_id}/major-focus   (Depends: require_bds_rep)
```
- Load review; 404 if missing. (No FA branch — `require_bds_rep` already blocks advisors with 403.)
- 400 if `status != "complete"` or no scored categories or no `framework.criteria`.
- Find the criterion in `framework["criteria"]` by `id` → its index `i`; 422/400 if not found. Resolve `category = categories[i]`.
- `text = generate_major_focus(transcript, criterion, category)`.
- `await update_review_major_focus(review_id, {criterion_id, criterion_title: criterion["title"], text, is_auto: False})`.
- Return the full updated review (`await get_review(...)`).
- **Error classification mirrors the chat endpoint** (`reviews.py:189-199`): `LLMUnavailableError → 503`, other `Exception → 502`.

`require_bds_rep` already exists in `backend/modules/auth.py` (used by `management.py`).

### 6. `backend/modules/pdf_export.py`
Inside `_summary_card`, immediately after the summary `multi_cell` block (~line 222), render a Major Focus block when `review.get("major_focus", {}).get("text")` is present — **read top-level `review["major_focus"]`**, not `review_data`. Mirror the summary styling:
- A small gap, then a `"MAJOR FOCUS"` muted 8pt bold label (optionally append the criterion title), then the `text` via `multi_cell` in `INK` 11pt — reusing `_t()`, the existing fonts/colors, and the `_NL` newline kwarg. The block stays inside the summary card so card pagination (`_draw_card` offset measurement) accounts for it automatically.

---

## Frontend (wire up after backend)

### 7. `frontend/src/services/api.js`
Add `updateReviewMajorFocus(id, criterionId)` — PATCH `/reviews/{id}/major-focus` with body `{ criterion_id: criterionId }`, same `authHeaders` + `handleResponse` wrapper as `updateReviewOutcome` (`api.js:112-120`). It will hit the LLM, so pass a longer timeout (reuse `CHAT_TIMEOUT_MS`/30s rather than the default 15s).

### 8. `frontend/src/pages/ResultsPage.jsx`
- Derive `const isBds = user?.role === 'bds_rep'` via `useAuth()` (same idiom as `HistoryPage.jsx:92`).
- Add state `isGeneratingFocus` / `majorFocusError` and `handleGenerateMajorFocus(criterionId)` following the **optimistic-update + revert** shape of `handleOutcomeChange` (`ResultsPage.jsx:69-88`): snapshot review, set generating, call `updateReviewMajorFocus`, `setReview(updated)` on success, revert + inline error on failure, clear generating in `finally`. (No optimistic text preview since the text comes from the server — just show a loading state on the button.)
- Pass `isBds`, `majorFocus={review.major_focus}`, `onGenerateMajorFocus`, `isGeneratingFocus`, `majorFocusError` into `<ReviewResults>`.

### 9. `frontend/src/components/ReviewResults.jsx` + `.css`
Insert a **Major Focus** block inside `.review-results__summary-card`, directly beneath the Summary (after line 99). Structure:
- Heading `MAJOR FOCUS` (reuse `.review-results__summary-heading` styling).
- The focus text (`majorFocus?.text`) in summary-text styling; if absent and the user is an advisor, render nothing (or a muted "No focus set yet").
- **BDS only** (`isBds &&`): a control row above/below the text with a `SearchableSelect` (`size="sm"`, `options = frameworkCriteria.map(c => ({ value: c.id, label: c.title }))`, `value` = local selected id defaulting to `majorFocus?.criterion_id`, `disabled={isGeneratingFocus}`) **and** a primary **Generate** button (`button-primary` per DESIGN.md — yellow `#fcd535`/`{rounded.md}`, disabled/loading state while `isGeneratingFocus`). Clicking calls `onGenerateMajorFocus(selectedId)`. Show `majorFocusError` inline (reuse `.review-results__meta-error`).
- When `majorFocus?.is_auto`, show a small muted "Auto-selected" caption next to the criterion so BDS knows it hasn't been curated.
- ReviewResults takes the new props; advisors fall through the `isBds` guard and never see the dropdown/button.

Styling references DESIGN.md: yellow primary CTA = `button-primary` token; muted labels = `{colors.muted}`; card stays flat with hairline. Keep the section visually subordinate to Summary (label + text), not a second heavy card.

---

## Critical files
- **Migration:** `backend/migrations/2026-06-08_add_major_focus.sql` (new)
- **Prompts:** `backend/prompts/major_focus.system.txt`, `backend/prompts/major_focus.user.txt` (new)
- **Backend:** `backend/modules/reviewer.py`, `backend/tasks.py`, `backend/modules/storage.py`, `backend/routers/reviews.py`, `backend/modules/pdf_export.py`
- **Frontend:** `frontend/src/services/api.js`, `frontend/src/pages/ResultsPage.jsx`, `frontend/src/components/ReviewResults.jsx` (+ `.css`)
- **Tests:** `backend/tests/test_pdf_export.py` (extend), new `backend/tests/test_major_focus.py`

## Reuse (do not reinvent)
- `update_review_outcome` (storage) → template for `update_review_major_focus`.
- PATCH `/reviews/{id}/outcome` + `OutcomeBody` (reviews.py) → template for the new endpoint; `require_bds_rep` (auth.py) for the BDS gate.
- Chat endpoint LLM error classification (reviews.py:189-199), `LLMUnavailableError`, `get_llm`, `load_prompt`, `_format_transcript_labeled` (reviewer.py).
- `handleOutcomeChange` optimistic/revert pattern (ResultsPage.jsx:69-88); `SearchableSelect`; `updateReviewOutcome` fetch wrapper (api.js).
- PDF helpers `_t`, summary `multi_cell` styling, `_draw_card` (pdf_export.py).

## Docs to update (per CLAUDE.md)
- `context/log.md` — feature entry.
- `context/map.md` — new prompt files, `major_focus` endpoint/column, reviewer fn, ReviewResults props.
- `context/decisions.md` — record: top-level JSONB column, default = largest-deficit criterion, dedicated LLM prompt, explicit Generate button (BDS-only).
- `context/deferredwork.md` — manual Supabase migration step (alert user).

---

## Verification

1. **Migration:** apply `2026-06-08_add_major_focus.sql` in Supabase SQL Editor; confirm `reviews.major_focus` exists.
2. **Backend unit tests** (`py -m pytest`):
   - `pick_default_focus_index`: largest-deficit wins; tie-break by ratio; `None` on no scores.
   - `test_major_focus.py`: `generate_major_focus` returns text with a stubbed/mock LLM; raises `LLMUnavailableError` with no key.
   - Extend `test_pdf_export.py`: a review with `major_focus.text` renders `%PDF` bytes; a review without it still renders (graceful absence).
3. **Pipeline default:** upload a call (`py -m uvicorn` + worker running); when complete, GET `/reviews/{id}` shows `major_focus` auto-targeting the largest-deficit criterion with `is_auto: true`.
4. **Endpoint (BDS):** `PATCH /reviews/{id}/major-focus` with a valid `criterion_id` → 200, focus text regenerated, `is_auto: false`. With no AI key → 503; invalid `criterion_id` → 422/400; as an advisor (FA token) → 403.
5. **Frontend (run the app):**
   - As **BDS**: Results screen shows Major Focus beneath Summary with the dropdown + Generate button; selecting a different criterion and clicking Generate shows a loading state then new text; error surfaces inline on failure.
   - As **advisor**: same call shows the focus **text only** — no dropdown, no button.
6. **PDF:** Download PDF as both roles → Major Focus block appears directly under the Summary paragraph with the same styling.
