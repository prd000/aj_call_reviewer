# Plan: Configurable Scoring Per Criterion (Feature #3)

## Context

Currently every criterion is scored on a fixed 1–10 scale. The overall score is a simple average of those values. The user wants to assign a different `max_score` to each criterion when editing a template — for example, a less-important criterion might be scored out of 5, while a core one remains out of 10. Criteria with a higher max carry proportionally more weight in the overall score.

**Overall score rule**: sum of individual scores / sum of individual max scores, displayed as "X / Y"
(e.g., 8/10 + 4/5 = **12/15**)

> **Note on Feature #2 compatibility**: The import/export plan (`template-json-import-export-plan.md`) defines a strict key whitelist and validator for imported JSON. `max_score` must be added to that whitelist and validator, and exports must include it. Those required adjustments are called out explicitly in the steps below.

---

## Affected Files

| Layer | File | Change |
|---|---|---|
| Backend | `backend/routers/templates.py` | Add `max_score` to Pydantic model + dict builder |
| Backend | `backend/modules/reviewer.py` | Dynamic LLM prompt; pass `max_score` through to category output |
| Backend | `backend/routers/reviews.py` | Overall score = sum/sum, return `overall_max_score` |
| Frontend | `frontend/src/components/CriteriaCard.jsx` | `max_score` number input in edit mode; label in view mode |
| Frontend | `frontend/src/components/ScoreCard.jsx` | Accept `maxScore` prop; dynamic bar + display + color thresholds |
| Frontend | `frontend/src/components/ReviewResults.jsx` | Pass `maxScore` to ScoreCard; overall = "X/Y" |
| Frontend | `frontend/src/components/ReviewList.jsx` | Score badge shows "X/Y" using new `overall_max_score` field |
| Frontend | `frontend/src/components/TemplateManager.jsx` | Update import validator + export serializer to include `max_score` |

---

## Implementation Steps

### 1. Backend — `backend/routers/templates.py`

- Add `max_score: int | None = None` to `CriterionBody` Pydantic model.
- In `_criterion_dict()`, write `"max_score": c.max_score if c.max_score is not None else 10` so every criterion stored in Supabase always has an explicit integer value.

### 2. Backend — `backend/modules/reviewer.py`

- Update `CRITERION_PROMPT_TEMPLATE` to use a `{max_score}` placeholder:
  `"score": <integer 1-{max_score}>` instead of the hardcoded `1-10`.
- In `review_call()`, extract `max_score = criterion.get("max_score", 10)` per criterion and pass it into the `.format()` call.
- After parsing the LLM JSON response, include `"max_score": max_score` on each category dict appended to `categories`.
- Update `STUB_REVIEW` to add `"max_score": 10` to each stub category so existing dev/fallback behaviour stays consistent.

### 3. Backend — `backend/routers/reviews.py`

- In `_review_summary()`, replace the simple average with a sum/sum calculation:
  ```python
  total_score = sum(c["score"] for c in categories if isinstance(c.get("score"), (int, float)))
  total_max   = sum(c.get("max_score", 10) for c in categories)
  ```
- Return both `"overall_score": total_score` and `"overall_max_score": total_max` in the summary dict, replacing the old single `overall_score` float.

### 4. Frontend — `frontend/src/components/CriteriaCard.jsx`

- **Edit mode**: Add a `Max Score` number input (min=1, max=10, default=10) below the `success_condition` textarea.
- **View mode**: Show a small label "Out of {criterion.max_score || 10}" beneath the criterion title.
- Ensure `max_score` is included in the object passed to `onUpdate` / `onSave`.

### 5. Frontend — `frontend/src/components/ScoreCard.jsx`

- Accept a new `maxScore` prop (default `10`).
- **Bar**: `const barPercent = (score / maxScore) * 100`
- **Display**: `{score}<span>/</span>{maxScore}` instead of the hardcoded `{score}<span>/10</span>`.
- **Color thresholds** (proportional): `score / maxScore >= 0.7` → green; `>= 0.4` → yellow; else red.

### 6. Frontend — `frontend/src/components/ReviewResults.jsx`

- Replace `getAverageScore()` with `getOverallScore(categories)` that returns `{ score, maxScore }` using sum/sum logic matching the backend.
- When rendering `ScoreCard` for each category, pass `maxScore={category.max_score || 10}`.
- Update the overall score display section to render "X / Y" using `{ score, maxScore }` from `getOverallScore`.
- Color the overall score badge proportionally (`score / maxScore` thresholds, same as ScoreCard).

### 7. Frontend — `frontend/src/components/ReviewList.jsx`

- The list API now returns `overall_score` (int sum) and `overall_max_score` (int sum).
- Update the score badge to show `{overall_score}/{overall_max_score}`.
- Adjust the color threshold to be proportional: `overall_score / overall_max_score`.
- Guard against missing `overall_max_score` on legacy rows: default to `(criteria count × 10)` or simply omit the denominator for rows with no score.

### 8. Frontend — `frontend/src/components/TemplateManager.jsx` (Feature #2 compatibility)

Feature #2's import/export code uses a strict key whitelist and validator. Without changes, importing a template that includes `max_score` on its criteria will fail with an "unknown field" error, and exporting will silently strip `max_score`. The following targeted edits are required:

**a. Extend `ALLOWED_CRITERION_KEYS`:**
```js
// Before:
const ALLOWED_CRITERION_KEYS = new Set(['id', 'title', 'description', 'success_condition'])
// After:
const ALLOWED_CRITERION_KEYS = new Set(['id', 'title', 'description', 'success_condition', 'max_score'])
```

**b. Add `max_score` validation inside `validateImportedTemplate` (after the `success_condition` check):**
```js
if (c.max_score !== undefined) {
  if (!Number.isInteger(c.max_score) || c.max_score < 1 || c.max_score > 10) {
    return { ok: false, error: `criteria[${i}].max_score must be an integer between 1 and 10 if present.` }
  }
}
```

**c. Include `max_score` in the rebuilt criterion object inside the validator:**
```js
criteria.push({
  id: crypto.randomUUID(),
  ...(c.title !== undefined ? { title: c.title } : {}),
  description: c.description,
  success_condition: c.success_condition,
  max_score: c.max_score ?? 10,   // default 10 if not supplied
})
```

**d. Include `max_score` in `handleExport`:**
```js
criteria: activeCriteria.map(c => ({
  ...(c.title !== undefined ? { title: c.title } : {}),
  description: c.description,
  success_condition: c.success_condition,
  max_score: c.max_score ?? 10,
})),
```

No other changes to `TemplateManager` are needed — criteria flow through state as opaque objects, so `max_score` propagates automatically once `CriteriaCard` emits it and the validator/exporter handle it.

---

## Backward Compatibility

- **Existing templates** in Supabase have no `max_score` on criteria → `criterion.get("max_score", 10)` defaults to 10 everywhere; the first save after this feature ships writes an explicit `10`.
- **Existing reviews** have categories without `max_score` → `category.get("max_score", 10)` defaults to 10; displays as "X/10" unchanged.
- **Existing list rows** have no `overall_max_score` → the list component falls back gracefully (show raw `overall_score` or omit the badge) for old rows.
- **Templates exported before Feature #3** ship will have no `max_score` field on criteria — re-importing them after Feature #3 ships works fine because the validator defaults to 10 when the field is absent.

---

## Verification

1. Open the template editor — confirm a `Max Score` input (1–10, default 10) appears on each criterion card in edit mode.
2. Set one criterion to max 5, save the template.
3. **Export the template** as JSON — confirm the downloaded file includes `"max_score": 5` on that criterion and `"max_score": 10` on the others.
4. **Re-import the exported JSON** — confirm the draft loads with the correct `max_score` values and no validation error.
5. **Import a template JSON with no `max_score` fields** (pre-Feature-#3 format) — confirm it imports cleanly with all criteria defaulting to 10.
6. **Import a template with an invalid `max_score`** (e.g., `"max_score": 0` or `"max_score": "five"`) — confirm a clear inline error appears.
7. Upload a call using the edited template.
8. On the results page:
   - The `/5` criterion shows "X/5".
   - The `/10` criteria show "X/10".
   - The overall score shows as a sum fraction (e.g., "19/25").
9. Open History — confirm the new review's score badge shows "X/Y".
10. Open an **existing** review (pre-Feature-#3) — all scores still display as "X/10" and the overall is unchanged.
