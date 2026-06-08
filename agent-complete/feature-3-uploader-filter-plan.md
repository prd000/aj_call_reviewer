# Plan — Major Feature #3: Filter History by who uploaded the call

## Context

From `context/bug-corrections.md` (Major feature #3): *"I want to be able to search by which user uploaded the call for review."*

Today the History page can filter by Advisor (who the call is *about*), Firm, Template, assigned BDS Rep, Outcome, and date range — but there is no way to find calls by **who actually clicked Upload**. Every review already stores `uploaded_by` (a profile UUID) and `uploader_role`, set in `routers/upload.py:93` to the authenticated user. That UUID is carried through `storage._from_row` but is never resolved to a name or surfaced to the UI.

This feature resolves `uploaded_by` → the uploader's profile name and exposes it as (a) a new multi-select **"Uploaded By"** history filter and (b) an **"Uploaded by X"** line on each history row. Per the user's decision, both are **BDS-rep-only** (FAs get neither — and because the name is only attached on the BDS response path, FA responses never carry it).

This is intentionally the same shape prescribed by the 2026-06-02 "History filters: Template & assigned BDS rep" decision in `context/decisions.md`: *"Any new BDS-only history facet should follow this shape: resolve/annotate in `_review_summary`, derive options client-side, gate the UI on `isBds`."*

**Distinction from the existing "BDS Rep" filter:** that filter is the firm's *assigned* `bds_rep_id` (resolved from `firms`), answering "calls for firms assigned to rep X." This new filter is the *actual uploader* (`reviews.uploaded_by`), answering "calls rep X personally uploaded" — which may be a BDS rep uploading on behalf of an advisor, or (rarely) an FA self-uploading. They are genuinely different facets.

Per `CLAUDE.md`: backend first, then wire the frontend.

## Backend changes (do first)

### 1. `backend/modules/user_profiles.py` — add a bulk id→name fetch
Uploaders can be any role (BDS rep, FA, or advisor-only shadow user), so `list_bds_reps()` is insufficient. Add a small helper that resolves only the ids actually present (avoids fetching all profiles):

```python
async def list_profiles_by_ids(ids: list[str]) -> list[dict]:
    """Fetch id+name for the given profile ids (any role). Empty list if none."""
    unique = [i for i in {i for i in ids} if i]
    if not unique:
        return []
    client = await get_client()
    result = await client.table("profiles").select("id, name").in_("id", unique).execute()
    return result.data
```

### 2. `backend/routers/reviews.py` — resolve + annotate (mirror `_build_firm_bds_rep_map`)
- Add a builder analogous to the existing `_build_firm_bds_rep_map()` (`reviews.py:59`):

```python
async def _build_uploader_name_map(reviews: list[dict]) -> dict:
    """Map uploaded_by (profile id) -> uploader name, for the loaded reviews."""
    ids = [r.get("uploaded_by") for r in reviews]
    profiles = await list_profiles_by_ids(ids)
    return {p["id"]: p.get("name") for p in profiles}
```

- In `_review_summary` (`reviews.py:27`), add the name **only when a map is supplied** (BDS path), exactly like `bds_rep_name`. Change the signature to also accept the uploader map (or pass both maps): set `metadata["uploaded_by_name"] = uploader_map.get(review.get("uploaded_by"))` only when `uploader_map is not None`. FA summaries omit it (they call `_review_summary(r)` with no maps), so the name never leaks to FAs.

- In `get_reviews` (`reviews.py:106`), BDS branch only: build the uploader map from `all_reviews` alongside the existing `firm_rep_map`, and pass it into `_review_summary`. Import `list_profiles_by_ids` from `modules.user_profiles` (the module is already imported for `list_bds_reps`).

No storage/migration changes — `uploaded_by` already exists on every row and is already returned by `_from_row`. Cost: one extra lightweight `profiles` read per BDS `GET /reviews` (and per 5s poll), consistent with the existing `list_firms` + `list_bds_reps` reads noted in the 2026-06-02 decision. The `.in_(...)` query is bounded by the number of *distinct* uploaders, not the number of reviews.

## Frontend changes (wire up after backend)

### 3. `frontend/src/pages/HistoryPage.jsx` — new filter (clone the BDS-Rep filter)
The BDS-Rep filter is the exact template to copy. Add in parallel to it:
- State: `const [filterUploader, setFilterUploader] = useState([])` (near `filterBdsRep`, line 49).
- Options (BDS-gated, derived from loaded reviews like `bdsRepOptions` at line 79):
  ```js
  const uploaderOptions = useMemo(() => {
    if (!isBds) return []
    const names = reviews.map((r) => r.metadata?.uploaded_by_name).filter(Boolean)
    return [...new Set(names)].sort()
  }, [isBds, reviews])
  ```
- Filter predicate in `visibleReviews` (line 86): `if (filterUploader.length && !filterUploader.includes(r.metadata?.uploaded_by_name)) return false`. Add `filterUploader` to the `useMemo` dependency array (line 119).
- Add `r.metadata?.uploaded_by_name` to the free-text `searchable` array (line 107) so the Search box also matches uploader — this directly satisfies the "search by … user uploaded" wording.
- Render a new `SearchableSelect` block gated on `isBds && uploaderOptions.length > 0`, labeled **"Uploaded By"**, placed next to the BDS-Rep filter (after line 328). Copy the BDS-Rep `<SearchableSelect multiple size="sm" …>` markup verbatim, swapping ids/label/value/onChange/options to the uploader ones.

### 4. `frontend/src/components/ReviewList.jsx` — show "Uploaded by X" on rows
In `ReviewListItem`'s `review-list-item__secondary` block (lines 113–117), render an uploader span when present:
```jsx
{metadata?.uploaded_by_name && (
  <span className="review-list-item__uploader">Uploaded by {metadata.uploaded_by_name}</span>
)}
```
Because the backend only attaches `uploaded_by_name` on the BDS response, this line is automatically absent for FAs — no role check needed in the component. Style `.review-list-item__uploader` in `ReviewList.css` to match the existing muted secondary-line text (reuse the same color/size tokens as `review-list-item__prospect`/`__date`); follow `context/DESIGN.md` muted-text conventions.

## Docs to update (required by CLAUDE.md)
- `context/log.md` — add a dated entry for Feature #3.
- `context/map.md` — note `list_profiles_by_ids` in `user_profiles.py`, the `uploaded_by_name` annotation + `_build_uploader_name_map` in `reviews.py`, the new "Uploaded By" filter in `HistoryPage.jsx`, and the uploader line in `ReviewList.jsx`.
- `context/decisions.md` — short entry: actual-uploader vs assigned-BDS-rep distinction; BDS-only (name attached only on BDS path so it can't leak to FAs); name-string matching reuses the advisor/bds-rep pattern (same same-name-collision caveat); resolved-on-read (no stored copy, no migration).

## Notable behaviors / edge cases
- **Name-string matching** (not id) keeps it consistent with the advisor/firm/bds-rep filters; two distinct users sharing a name would collide, the same pre-existing limitation those filters have. Acceptable and consistent.
- **Deleted/missing uploader profile** → name resolves to absent → row simply omits the line and the value never appears as an option (graceful, same as a review missing `advisor_name`).
- **Legacy pre-auth reviews** have no `uploaded_by` → no line, no option. Fine.

## Verification

Backend (run with `py -m`, per machine convention):
1. `cd backend; py -m uvicorn main:app --reload` (or use `start.ps1`).
2. As a BDS rep, `GET /api/reviews` → confirm each summary's `metadata.uploaded_by_name` is populated for reviews that have an `uploaded_by`. As an FA, confirm the field is **absent**.
3. Quick check that `list_profiles_by_ids` returns `[{id, name}]` for a couple of known ids and `[]` for `[]`.

Frontend end-to-end:
4. `npm run dev` (frontend) — log in as a BDS rep, open **History**. Confirm a new **"Uploaded By"** multi-select appears (only when ≥1 uploader name exists), multi-select narrows the list (OR within the facet, AND across facets), and the free-text Search box also matches uploader names.
5. Confirm each row shows **"Uploaded by X"** in the secondary line.
6. Log in as an FA: confirm **no** "Uploaded By" filter and **no** uploader line on rows.
7. Upload a call as the BDS rep on behalf of an advisor, let it complete, and confirm the row's "Uploaded by" shows the **BDS rep's** name (the uploader) while "Advisor" still shows the advisor — verifying the two facets are distinct.
