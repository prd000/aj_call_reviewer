# Plan — Major Feature #2: Import/Export Review Templates as JSON

## Context

Today, the only way to author a review framework is to click "+ New Template" in `TemplateManager` and hand-type each criterion's title / description / success_condition into the UI. That is slow when the user has just iterated on a framework with an LLM in another tool — they have to retype everything by hand.

This feature lets the user import a finished framework as a JSON file and (paired addition) export an existing template back to JSON so they can workshop revisions in an LLM and re-import. Round-tripping JSON makes the framework genuinely portable.

Confirmed design choices:
- **Import behavior:** Load imported JSON into the editor as a draft (`selectedId = 'new'`, `isDirty = true`); the user reviews it and clicks the existing **Save Template** button to commit. Mistakes from LLM output can be edited inline before they go live.
- **Export:** Add a Download button so the user can pull an existing template down, refine it, and re-import.
- **Validation:** Strict — match the existing `TemplateBody` / `CriterionBody` Pydantic shape exactly. Reject unknown fields with a specific error so the schema stays documentable.

Backend needs no changes. The existing `POST /api/templates` endpoint (`backend/routers/templates.py:50-54`) already validates the right shape via `TemplateBody`; the import flow parses the file client-side and then calls the existing `createTemplate(body)` in `frontend/src/services/api.js:117-124`. Keeping the server contract unchanged means import errors and Save errors surface through one validated path.

---

## Scope

Frontend-only. Two new affordances inside `TemplateManager`:

1. **Import JSON** button → opens a hidden file picker → reads file → validates → populates the editor as a draft.
2. **Download JSON** button → exports the currently-selected template as a `.json` file.

Both are visible whenever `TemplateManager` is rendered (today: BDS-rep-only Upload page, gated by `isBds` at `frontend/src/pages/UploadPage.jsx:129`). No new routes, no new role checks.

---

## Files modified

### `frontend/src/components/TemplateManager.jsx`

Add three pieces of logic and two buttons. Reuse existing state and handlers wherever possible.

**New helper (top of file, outside the component):**

```js
const ALLOWED_TEMPLATE_KEYS = new Set(['name', 'criteria'])
const ALLOWED_CRITERION_KEYS = new Set(['id', 'title', 'description', 'success_condition'])

function validateImportedTemplate(parsed) {
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, error: 'JSON must be an object with "name" and "criteria".' }
  }
  for (const key of Object.keys(parsed)) {
    if (!ALLOWED_TEMPLATE_KEYS.has(key)) {
      return { ok: false, error: `Unknown top-level field "${key}". Allowed: name, criteria.` }
    }
  }
  if (typeof parsed.name !== 'string' || parsed.name.trim() === '') {
    return { ok: false, error: '"name" must be a non-empty string.' }
  }
  if (!Array.isArray(parsed.criteria) || parsed.criteria.length === 0) {
    return { ok: false, error: '"criteria" must be a non-empty array.' }
  }
  const criteria = []
  for (let i = 0; i < parsed.criteria.length; i++) {
    const c = parsed.criteria[i]
    if (c === null || typeof c !== 'object' || Array.isArray(c)) {
      return { ok: false, error: `criteria[${i}] must be an object.` }
    }
    for (const key of Object.keys(c)) {
      if (!ALLOWED_CRITERION_KEYS.has(key)) {
        return { ok: false, error: `criteria[${i}] has unknown field "${key}".` }
      }
    }
    if (typeof c.description !== 'string' || c.description.trim() === '') {
      return { ok: false, error: `criteria[${i}].description must be a non-empty string.` }
    }
    if (typeof c.success_condition !== 'string' || c.success_condition.trim() === '') {
      return { ok: false, error: `criteria[${i}].success_condition must be a non-empty string.` }
    }
    if (c.title !== undefined && typeof c.title !== 'string') {
      return { ok: false, error: `criteria[${i}].title must be a string if present.` }
    }
    criteria.push({
      id: crypto.randomUUID(), // ignore any incoming id; regenerate so re-imports never collide
      ...(c.title !== undefined ? { title: c.title } : {}),
      description: c.description,
      success_condition: c.success_condition,
    })
  }
  return { ok: true, template: { name: parsed.name, criteria } }
}
```

Key choices:
- Regenerate `criterion.id` on import. The backend's `_criterion_dict` (`backend/routers/templates.py:39-47`) auto-generates IDs when missing, but if an exported file is re-imported and saved, the old IDs would silently overwrite criteria in a sibling template. Fresh UUIDs per import eliminate that footgun.
- Strict key whitelist mirrors the Pydantic models exactly; the user gets the same "name + criteria" / "description + success_condition" contract whether they hit the API directly or use the UI.
- `crypto.randomUUID()` matches the convention already used in `CriteriaCard.jsx` add-mode.

**New ref + handlers (inside the component):**

```js
const fileInputRef = useRef(null)

function handleImportClick() {
  fileInputRef.current?.click()
}

async function handleFileChange(e) {
  const file = e.target.files?.[0]
  e.target.value = '' // allow re-import of the same filename later
  if (!file) return
  setError(null)
  try {
    const text = await file.text()
    let parsed
    try {
      parsed = JSON.parse(text)
    } catch (parseErr) {
      setError(`Invalid JSON: ${parseErr.message}`)
      return
    }
    const result = validateImportedTemplate(parsed)
    if (!result.ok) {
      setError(`Import failed: ${result.error}`)
      return
    }
    // Load as draft — same shape as choosing "+ New Template", but pre-populated.
    setSelectedId('new')
    setActiveName(result.template.name)
    setActiveCriteria(result.template.criteria)
    setOriginalName('')
    setOriginalCriteria([])
    setIsDirty(true)
    setDeleteConfirmOpen(false)
    setIsAddingCriteria(false)
    onCriteriaChange(result.template.criteria, result.template.name, null)
  } catch (err) {
    setError(`Could not read file: ${err.message}`)
  }
}

function handleExport() {
  // Strip transient internal fields; export only what the schema documents.
  const payload = {
    name: activeName,
    criteria: activeCriteria.map(c => ({
      ...(c.title !== undefined ? { title: c.title } : {}),
      description: c.description,
      success_condition: c.success_condition,
    })),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(activeName || 'template').replace(/[^a-z0-9_-]+/gi, '_').toLowerCase() || 'template'}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
```

**UI changes (inside the controls/header area):**

Add Import and Download buttons next to the existing dropdown + delete button. The hidden `<input type="file">` lives near the controls and is triggered programmatically — matches the pattern used in `UploadForm.jsx`'s drag-and-drop file zone (avoid duplicating the dropzone here; the JSON import is one-click).

```jsx
<input
  ref={fileInputRef}
  type="file"
  accept="application/json,.json"
  onChange={handleFileChange}
  style={{ display: 'none' }}
/>
<button
  className="template-manager__btn template-manager__btn--secondary"
  onClick={handleImportClick}
>
  Import JSON
</button>
<button
  className="template-manager__btn template-manager__btn--secondary"
  onClick={handleExport}
  disabled={selectedId === 'new' || activeCriteria.length === 0}
  title="Download this template as JSON"
>
  Download JSON
</button>
```

Add the buttons either inside `template-manager__controls` or alongside the existing actions row — pick the location that keeps the dropdown + name + delete row from getting cramped. Disable Download when nothing is loaded (`selectedId === 'new'` with empty criteria) so the user doesn't export an empty file.

Add `import { useRef } from 'react'` to the existing import.

### `frontend/src/components/TemplateManager.css`

No new variant classes needed — both buttons reuse `template-manager__btn--secondary`. If the new row visually crowds the existing controls, add a `.template-manager__io` flex container (gap + margin matching the existing `__actions` row) and group the two new buttons there. Otherwise no CSS changes.

### `context/log.md`

Append a new dated entry (top of file) summarizing the feature, files touched, and the strict-schema decision. Follow the existing entry format.

### `context/map.md`

Update the `TemplateManager` line under `frontend/src/components/` to mention "JSON import (loads as draft) and JSON export (downloads current template)".

### `context/decisions.md`

Append a short entry: "Template JSON import/export — strict schema, import lands as draft, IDs regenerated on import to prevent overwrite". Captures the rationale future-you will need when feature #3 (per-criterion scoring config) extends the schema and the import validator has to change.

---

## What is explicitly NOT in scope

- **No backend changes.** Reuses `POST /api/templates`. If we later want server-side import validation (e.g., for a CLI or API client), we add a thin router endpoint then; not now.
- **No new route or page.** The buttons live inside the existing `TemplateManager` instance on `/` (Upload page), where templates are already authored.
- **No backend role check on `/api/templates`.** The router is currently un-gated (`backend/routers/templates.py` has no `Depends(get_current_user)`); adding auth to template endpoints is bug-corrections.md item #4 (RLS / safety) and shouldn't be conflated with this feature. Frontend gating via `isBds` in `UploadPage.jsx:129` continues to be the only access control, same as today.
- **No example/schema download.** If a user needs a template, they hit Download on an existing one (e.g., "Rudimentary"). That doubles as the canonical schema example.
- **No `id` round-tripping.** Export strips `id`; import regenerates `id`. Stable IDs are an internal concern.

---

## Verification

Manual (the only practical way to verify a UI-driven flow):

1. `py -m uvicorn main:app --reload` from `backend/`; `npm run dev` from `frontend/`.
2. Log in as a BDS rep. Navigate to `/` (Upload page). Confirm `TemplateManager` renders with the new **Import JSON** and **Download JSON** buttons.
3. **Export round-trip:**
   - Select an existing template (e.g., "Rudimentary"). Click **Download JSON**. Confirm a file named `rudimentary.json` downloads.
   - Open the file. Confirm the shape is `{ name, criteria: [{ title?, description, success_condition }] }` — no `id`, no extra fields.
4. **Happy-path import:**
   - Edit the downloaded JSON: change `name` to "Imported Test" and tweak one criterion.
   - Click **Import JSON**, pick the file.
   - Editor should switch to draft mode: name field shows "Imported Test", criteria list shows the edited criteria, **Save Template** is enabled, **Discard Changes** is hidden (because `selectedId === 'new'`).
   - Click **Save Template**. Confirm the new template appears in the dropdown and is selected.
5. **Validation errors** — for each, paste content into a `.json` file and import; confirm a clear inline error appears under the controls and no state changes:
   - Malformed JSON: `{ "name":` (truncated).
   - Missing `criteria`: `{ "name": "x" }`.
   - Empty `criteria`: `{ "name": "x", "criteria": [] }`.
   - Missing `success_condition` on a criterion.
   - Unknown top-level field: `{ "name": "x", "criteria": [...], "version": 1 }`.
6. **Re-import the same filename twice in a row** — confirm the file picker reopens correctly (the `e.target.value = ''` reset works).
7. **End-to-end pipeline check** — upload a short call recording using the newly imported template; confirm on `/history` that the review completes (`complete` status) and that the criteria from the imported template appear on the results page. This validates that imported criteria are accepted by the Celery pipeline at `backend/tasks.py` and the reviewer at `backend/modules/reviewer.py:145-205` (which reads `description` and `success_condition`).
