# Plan: Download call reviews as a PDF (Major Feature #1)

## Context

`context/bug-corrections.md` lists as Major Feature #1: *"I want to be able to download my call reviews as a PDF."* This was originally in the PRD's **Out of Scope** list and has now been promoted to a feature. There is no existing implementation, decision, or log entry for it.

**Goal:** Let a user on the single-call results page download that review as a real, shareable/archivable PDF file.

**Scope decisions (confirmed with user):**
- **Generation:** Backend endpoint that returns a true `application/pdf` (not browser print, not client-side).
- **Content:** Review summary + metadata, and per-criterion scores + feedback. **No** framework/criteria section and **no** transcript.
- **Trigger location:** Results page only (single call). No History per-row or batch export in this version.

## Approach

Add a backend PDF render module + endpoint, then wire a "Download PDF" button on the Results page. Per CLAUDE.md, build the backend first, then the frontend.

### PDF engine: `xhtml2pdf` (recommended over WeasyPrint)

The PDF is generated from an HTML/CSS template. **Use `xhtml2pdf`** (pure-Python; depends on `reportlab`) rather than WeasyPrint:
- This is a Windows dev machine (memory: `py -m` prefix) deploying to Railway (Linux). WeasyPrint needs native GTK/Pango/Cairo libraries — painful to install locally and adds an apt build step on Railway, undermining "robust local testing" (CLAUDE.md).
- `xhtml2pdf` installs with plain `pip`, runs identically on Windows and Railway, and its CSS support is more than enough for this report (tables, fonts, colors, simple bars).
- Trade-off: lower CSS fidelity than WeasyPrint. Acceptable for this layout. Record this in `decisions.md`.

## Backend changes (do first)

### 1. Dependency
- `backend/requirements.txt`: add `xhtml2pdf>=0.2.16`. Install with `py -m pip install -r backend/requirements.txt`.

### 2. New module `backend/modules/pdf_export.py`
A self-contained, testable module (no network, no Supabase). Public function:

```python
def render_review_pdf(review: dict) -> bytes        # returns %PDF bytes
def review_pdf_filename(review: dict) -> str         # ASCII-safe, e.g. "Call-Review-Jane-Doe-2026-06-08.pdf"
```

Structure:
- `_overall_score(categories)` — reuse the exact formula already in `routers/reviews.py::_review_summary` (`round((sum(score)/sum(max_score))*10, 1)`, denom 10). Keep one source of truth by importing/extracting a shared helper if convenient; otherwise mirror it and note the link in a comment.
- `_score_color(ratio)` — mirror `frontend/src/components/ScoreCard.jsx` thresholds: `>=0.7 → #0ecb81` (green), `>=0.4 → #fcd535` (yellow), `<0.4 → #f6465d` (red). These hexes come from `context/design.md` / `frontend/src/styles/tokens.css`.
- `_build_html(review)` — assemble the HTML string from the review dict. Light/printable theme per design.md (white canvas `#ffffff`, ink text `#181a20`, yellow accent `#fcd535`). Sections:
  1. **Header band** — "Call Review" title; metadata grid: Advisor (`metadata.advisor_name`), Firm (`metadata.firm`), Prospect (`metadata.prospect_name`), Date (formatted from `created_at`), Outcome (`metadata.call_outcome` — stored value is already the human label, no mapping needed; omit row if null).
  2. **Overall score** — big `N/10`, colored via `_score_color`.
  3. **Summary** — `review.review.summary` (omit if empty).
  4. **Category Scores** — for each `review.review.categories[i]`: title = `framework.criteria[i].title or category.name` (same fallback as `ReviewResults.jsx`), `score/max_score`, a colored bar, and `feedback`.
- HTML is built in Python with escaping (`html.escape`) on all user/LLM-derived strings — no new templating dependency, content is small and well-structured. Convert with `xhtml2pdf.pisa.CreatePDF` into a `BytesIO`, return bytes.
- `review_pdf_filename` — sanitize advisor/prospect + date to `[A-Za-z0-9-]`, ASCII-only (safe for `Content-Disposition`).

### 3. New endpoint in `backend/routers/reviews.py`
```python
@router.get("/reviews/{review_id}/pdf")
async def download_review_pdf(review_id, user = Depends(get_current_user)):
```
- Fetch via `get_review`; 404 if missing.
- Apply the **same FA visibility check** used by the other review routes: `if user["role"] == "financial_advisor" and not _fa_can_access(review, user): raise 404`.
- If `review["status"] != "complete"` or no `review["review"]["categories"]` → `400` ("Review is not finished yet.").
- `pdf_bytes = render_review_pdf(review)` (run in a threadpool via `await run_in_threadpool(...)` since `pisa` is sync/CPU-bound, to avoid blocking the event loop).
- Return `Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{review_pdf_filename(review)}"'})`. `Response` is already imported.

## Frontend changes (wire up after backend)

### 4. `frontend/src/services/api.js`
Add `downloadReviewPdf(id)`. Cannot reuse `handleResponse` (it calls `response.json()`); the success path needs `response.blob()`:
- Build auth headers via existing `authHeaders()`.
- `apiFetch(`${BASE_URL}/reviews/${id}/pdf`, { headers }, PDF_TIMEOUT_MS)` — add a `PDF_TIMEOUT_MS = 30_000` constant.
- On `!response.ok`: parse `detail` for the message and throw (mirror the non-401 branch of `handleResponse`; a 401 here is an edge case — surface a retryable error).
- On success: return `await response.blob()` (filename comes from the known pattern; optionally parse `Content-Disposition`).

### 5. New util `frontend/src/lib/download.js`
Small reusable helper (no such util exists today):
```js
export function downloadBlob(blob, filename) { /* create object URL, click temp <a>, revoke URL */ }
```

### 6. `frontend/src/pages/ResultsPage.jsx`
- Add `isDownloading` / `downloadError` state.
- Add a **"Download PDF" button** in the header row (next to `results-page__title` / the back-link row). Render it only when `review.status === 'complete'` and there are categories.
- Handler: set downloading → `const blob = await downloadReviewPdf(id)` → `downloadBlob(blob, `Call-Review-...pdf`)` → clear; on error set `downloadError` (inline message near the button). Show "Generating…" label + disabled state while in flight.
- Style as a **secondary** action per design.md (yellow `button-primary` is reserved for primary CTAs; use a secondary/outline button). Add minimal CSS to `ResultsPage.css`.

## Documentation updates (required by CLAUDE.md)
- `context/log.md` — add an entry for Feature #1 (PDF download): backend module + endpoint, frontend button, engine choice.
- `context/map.md` — add `backend/modules/pdf_export.py`, the `GET /reviews/{id}/pdf` route under `routers/reviews.py`, `frontend/src/lib/download.js`, and the new `api.js` function.
- `context/decisions.md` — record: (a) PDF generation is server-side returning `application/pdf`; (b) engine is `xhtml2pdf` (pure-Python) chosen over WeasyPrint to avoid native deps on Windows/Railway; (c) v1 PDF intentionally excludes transcript and framework.
- No `deferredwork.md` entry needed — no new env var, API key, or dummy data is introduced.

## Verification

**Backend unit tests** — new `backend/tests/test_pdf_export.py` (follows existing pytest patterns; conftest already seeds env):
- `render_review_pdf(sample_review)` returns non-empty bytes starting with `b"%PDF"`.
- Works with a minimal review (missing summary, missing outcome, missing framework titles) — no exception, falls back to `category.name`.
- `review_pdf_filename` returns an ASCII-only, sanitized `.pdf` name.
- `_score_color` returns the correct hex at boundary ratios (0.7, 0.4, below).
- Run: `py -m pytest backend/tests/test_pdf_export.py`.

**Manual end-to-end:**
1. `py -m pip install -r backend/requirements.txt`.
2. Start backend (`py -m uvicorn main:app --reload` from `backend/`) and frontend (`npm run dev` from `frontend/`).
3. Open a **completed** review at `/results/:id`; confirm the "Download PDF" button appears (and is absent on in-progress reviews).
4. Click it → a PDF downloads → opens correctly with: metadata header, overall score (right number + color), summary, and each category's title/score/colored bar/feedback. Confirm transcript and framework are **not** present.
5. Confirm FA visibility: an FA cannot download another firm's review (`GET /api/reviews/{id}/pdf` → 404).
