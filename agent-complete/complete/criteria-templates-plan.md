# Plan: Review Criteria Templates

## Context

The current review system uses static `.txt` files in `/prompts/` — one per scoring category — hardcoded on disk. This makes it impossible to change review criteria from the UI. The goal is to replace this entirely with a dynamic template system: users create named templates of criteria directly on the upload page, select a template per call, and can edit/save/delete templates. Each review records a snapshot of the criteria used so history stays accurate even if templates change later.

---

## Decisions Made (grill-me session)

- Replace `/prompts/` entirely — no coexistence with old system
- 1–10 scoring retained per criteria (composite score already works)
- Templates stored as JSON in `data/templates/` (one file per template)
- Dropdown on upload page; "New Template" option in dropdown
- New template: add criteria first, name it on save
- Edit existing template inline on upload page; Save/Discard buttons
- Unsaved edits are used for the review even if not saved to template
- Template name + full criteria snapshot stored in the review record
- Inline criteria add form (two textareas, Save/Cancel)
- Delete template from upload page with confirmation popup; blocked if last template
- Rename template inline, same Save/Discard flow

---

## LLM Prompt Template (replaces all `.txt` files)

```
You are a call reviewer for financial advisors. Your current job is to analyze this call recording based on the following criteria:

Criteria: {description}

You know this has been successfully accomplished when: {success_condition}

Respond with a JSON object in this exact format:
{"score": <integer 1-10>, "feedback": "<2-3 sentences of coaching feedback>"}

Do not include anything outside the JSON object.
```

One LLM call per criteria, same pattern as before.

---

## Template Storage Schema

```json
{
  "id": "<uuid>",
  "name": "Rudimentary",
  "created_at": "<iso8601>",
  "updated_at": "<iso8601>",
  "criteria": [
    {
      "id": "<uuid>",
      "description": "...",
      "success_condition": "..."
    }
  ]
}
```

## Review Record Addition

Add a `framework` key alongside `review`:
```json
"framework": {
  "template_name": "Rudimentary",
  "template_id": "<uuid or null>",
  "criteria": [
    { "id": "...", "description": "...", "success_condition": "..." }
  ]
}
```

---

## Implementation Steps

### Backend — edit first

**Step 1: `backend/modules/templates.py` (new)**

Functions:
- `get_templates_dir() -> Path` — returns `data/templates/`, creates if missing
- `list_templates() -> list[dict]` — read all `{id}.json` files, return sorted by `created_at` desc
- `get_template(id: str) -> dict | None`
- `save_template(template: dict) -> dict` — writes `{id}.json`, sets `updated_at`
- `delete_template(id: str) -> bool` — returns False if not found
- `migrate_default_template()` — idempotent; checks if any template named "Rudimentary" exists; if not, creates one with these 4 criteria (hardcoded from existing prompt files):

  | criteria `description` | `success_condition` |
  |---|---|
  | "Rapport building: assess whether the advisor opened with a warm personalized greeting, used the prospect's name naturally, showed genuine interest in the prospect's situation before moving to business, mirrored the prospect's tone and energy, created moments of authentic connection, and listened actively before responding." | "The advisor created a genuinely comfortable and trusting atmosphere. The prospect opened up freely, there were multiple natural moments of connection, and the advisor consistently listened and acknowledged before responding. Score 9–10 for exceptional warmth; 1–2 for cold or dismissive tone with no attempt to connect." |
  | "Needs discovery: assess whether the advisor asked open-ended questions, uncovered the prospect's current financial situation (assets, accounts, income), identified the prospect's goals and desired outcomes, uncovered fears and pain points, explored timeline and urgency, listened more than they talked, and asked follow-up questions that deepened understanding." | "The advisor comprehensively uncovered the prospect's current situation, goals, fears, and timeline. The prospect felt heard. The advisor asked more questions than they made statements and dug deeper on key concerns. Score 9–10 for comprehensive discovery; 1–2 for launching into a pitch with no discovery." |
  | "Solution presentation: assess whether the advisor tied the solution directly to the needs the prospect expressed, explained it in plain language, used concrete examples or case studies, clearly articulated the value proposition for this specific prospect, avoided unexplained jargon, presented with confidence, and kept the presentation appropriately concise." | "The solution was clearly connected to the prospect's specific situation, compelling, and easy to understand. The advisor used concrete examples and tied everything back to what the prospect said they cared about. Score 9–10 for highly tailored and clear presentation; 1–2 for no real solution presented or an irrelevant one." |
  | "Objection handling: assess whether the advisor acknowledged objections before responding, asked clarifying questions to understand the root of the objection, responded with empathy and without defensiveness, provided specific relevant answers, proactively surfaced common concerns before they arose, turned objections into opportunities to reinforce value, and maintained confidence after handling an objection." | "All objections were handled with empathy, specificity, and confidence. The advisor proactively surfaced and addressed common concerns before they became objections, and turned each objection into an opportunity to reinforce value. Score 9–10 for masterful handling; 1–2 for ignored or trust-damaging responses." |

**Step 2: `backend/routers/templates.py` (new)**

Endpoints:
- `GET /templates` → `list_templates()` — returns list of `{id, name, criteria_count, updated_at}`
- `POST /templates` → body `{name, criteria}` → `save_template(new_record)` → 201
- `GET /templates/{id}` → `get_template(id)` or 404
- `PUT /templates/{id}` → body `{name?, criteria?}` → merge + `save_template()` → 200
- `DELETE /templates/{id}` → check `len(list_templates()) > 1` first (else 409 "Cannot delete the only remaining template"); then `delete_template(id)` → 204

**Step 3: `backend/modules/reviewer.py` (modify)**

- Remove `load_prompts()` function
- Add `CRITERION_PROMPT_TEMPLATE` constant (the template string above)
- Change `review_call(transcript, prompts_dir)` → `review_call(transcript, criteria)` where `criteria` is `list[dict]` with keys `description` and `success_condition`
- For each criterion, format `CRITERION_PROMPT_TEMPLATE`, call LLM, parse JSON
- Category `name` in output = `criterion["description"][:60]` (truncated for ScoreCard display)
- Stub falls back when `not api_key` or `not criteria`

**Step 4: `backend/routers/reviews.py` (modify)**

- Remove `PROMPTS_DIR` constant
- Add Pydantic model:
  ```python
  class ProcessRequestBody(BaseModel):
      criteria: list[dict]
      template_name: str = ""
      template_id: str | None = None
  ```
- Change `process_review(review_id: str)` → `process_review(review_id: str, body: ProcessRequestBody)`
- Pass `body.criteria` to `review_call(review["transcript"], body.criteria)`
- Before `save_review()` on success, attach:
  ```python
  review["framework"] = {
      "template_name": body.template_name,
      "template_id": body.template_id,
      "criteria": body.criteria,
  }
  ```

**Step 5: `backend/main.py` (modify)**

- Add lifespan context manager (FastAPI `lifespan` pattern):
  ```python
  from contextlib import asynccontextmanager
  from modules.templates import migrate_default_template

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      migrate_default_template()
      yield

  app = FastAPI(title="Call Reviewer API", version="0.1.0", lifespan=lifespan)
  ```
- Import and register `templates` router: `app.include_router(templates.router)`

---

### Frontend — wire up after backend

**Step 6: `frontend/src/services/api.js` (modify)**

Add functions:
```javascript
export async function listTemplates()              // GET /templates
export async function getTemplate(id)              // GET /templates/{id}
export async function createTemplate(body)         // POST /templates
export async function updateTemplate(id, body)     // PUT /templates/{id}
export async function deleteTemplate(id)           // DELETE /templates/{id} — 204 returns undefined
```

Update `processReview`:
```javascript
export async function processReview(id, body)      // POST /reviews/{id}/process with JSON body
```

`deleteTemplate` must handle 204 (no body) without calling `response.json()`.

**Step 7: `frontend/src/components/CriteriaCard.jsx` (new)**

Two modes via props:
- **Display mode** (`criterion` object, `onUpdate`, `onDelete`): shows description + "Success when: …" + trash icon. Trash icon: `color: var(--color-muted)`, hover `var(--color-trading-down)`.
- **Add mode** (`criterion: null`, `onSave`, `onCancel`): starts in edit state, two textareas, Save (disabled until both fields filled) / Cancel.

Clicking an existing criteria card puts it into edit mode (inline edit on the card).

Companion `CriteriaCard.css`. Card bg: `surface-elevated-dark`; border: `1px solid var(--color-hairline-on-dark)`; border-radius: `var(--rounded-lg)`.

**Step 8: `frontend/src/components/TemplateManager.jsx` (new)**

State:
```javascript
templates, selectedId, activeName, activeCriteria,
originalName, originalCriteria, isDirty,
isAddingCriteria, deleteConfirmOpen, isLoading, error
```

`isDirty` = deep-compare `activeCriteria` vs `originalCriteria` OR `activeName !== originalName`.

Behavior:
- On mount: `listTemplates()` → auto-select first template → load into active + original state
- Dropdown: all template names + `"+ New Template"` (value `"new"`)
- Selecting existing template: load via `getTemplate(id)`, reset dirty
- Selecting "New Template": clear name + criteria, mark dirty immediately
- Inline name `<input>` next to dropdown (always editable, marks dirty on change)
- Delete button (trash) next to name input; disabled if `templates.length === 1`; clicking sets `deleteConfirmOpen = true`; confirm dialog renders inline below name row ("Are you sure? [Delete] [Cancel]")
- On delete confirm: `deleteTemplate(selectedId)` → reload templates → auto-select first remaining
- Criteria list: `activeCriteria.map(c => <CriteriaCard .../>)`
- `isAddingCriteria` → append `<CriteriaCard criterion={null} onSave={handleAdd} onCancel={...}/>`
- "+" button: sets `isAddingCriteria = true`
- Save Template button (visible when `isDirty && activeName.trim() && activeCriteria.length > 0`):
  - If `selectedId === "new"`: `createTemplate({name, criteria})` → reload → select new id → reset dirty
  - Else: `updateTemplate(selectedId, {name, criteria})` → reload → reset dirty
- Discard Changes button (visible when `isDirty && selectedId !== "new"`): reset active state to original, clear dirty
- Calls `onCriteriaChange(activeCriteria, activeName, selectedId === "new" ? null : selectedId)` on every relevant state change

Props: `{ onCriteriaChange }` callback.

Companion `TemplateManager.css`. Save button: `button-primary` (yellow). Discard + Add buttons: `button-secondary-on-dark`.

**Step 9: `frontend/src/pages/UploadPage.jsx` (modify)**

Add state:
```javascript
const [activeCriteria, setActiveCriteria] = useState([])
const [activeTemplateName, setActiveTemplateName] = useState('')
const [activeTemplateId, setActiveTemplateId] = useState(null)
```

Add handler:
```javascript
function handleCriteriaChange(criteria, templateName, templateId) {
  setActiveCriteria(criteria)
  setActiveTemplateName(templateName)
  setActiveTemplateId(templateId)
}
```

Update `handleSubmit`:
- Guard: if `activeCriteria.length === 0`, set error "Please add at least one review criterion before uploading." and return
- Change `processReview(reviewId)` → `processReview(reviewId, { criteria: activeCriteria, template_name: activeTemplateName, template_id: activeTemplateId })`

Add `<TemplateManager onCriteriaChange={handleCriteriaChange} />` above the form card in JSX. Add `.upload-page__template-section { margin-bottom: var(--spacing-lg); }` to `UploadPage.css`.

---

## Critical Files

| File | Action |
|---|---|
| `backend/modules/templates.py` | **CREATE** |
| `backend/routers/templates.py` | **CREATE** |
| `backend/modules/reviewer.py` | **MODIFY** — replace `load_prompts` + `prompts_dir` param |
| `backend/routers/reviews.py` | **MODIFY** — add `ProcessRequestBody`, update process endpoint |
| `backend/main.py` | **MODIFY** — lifespan + templates router |
| `frontend/src/services/api.js` | **MODIFY** — add template CRUD, update processReview |
| `frontend/src/components/CriteriaCard.jsx` | **CREATE** |
| `frontend/src/components/CriteriaCard.css` | **CREATE** |
| `frontend/src/components/TemplateManager.jsx` | **CREATE** |
| `frontend/src/components/TemplateManager.css` | **CREATE** |
| `frontend/src/pages/UploadPage.jsx` | **MODIFY** — add template section + criteria guard |
| `frontend/src/pages/UploadPage.css` | **MODIFY** — add `.upload-page__template-section` |
| `context/log.md` | **UPDATE** |
| `context/map.md` | **UPDATE** — add new files, update modified files |
| `context/decisions.md` | **UPDATE** — record template system decision |
| `context/deferredwork.md` | **UPDATE** — note criteria `name` field UX improvement |

---

## Context Doc Updates

- **`decisions.md`**: Record replacement of `/prompts/` with template system; snapshot-on-review pattern; criteria-in-process-body pattern
- **`deferredwork.md`**: Criteria currently display their `description[:60]` as the ScoreCard name — a dedicated `name` field per criterion would improve readability in the results view
- **`map.md`**: Add `data/templates/`, new backend modules/routers, new frontend components
- **`log.md`**: Entry for all created/modified files

---

## Verification

1. Start backend: `py -m uvicorn main:app --reload` from `backend/`
2. `GET /api/templates` → should return the "Rudimentary" template with 4 criteria
3. Start frontend: `npm run dev` from `frontend/`
4. Upload page shows template dropdown with "Rudimentary" pre-selected and its 4 criteria listed
5. Add a new criterion inline, verify it appears, mark dirty → Save Template
6. Select "New Template", add 2 criteria, type a name, save → verify it appears in dropdown
7. Edit a template name inline → Discard → verify name reverts
8. Delete a template with only 2 remaining → confirm dialog → deleted → auto-selects remaining
9. Submit a call with criteria selected → ProcessingPage polls → ResultsPage shows categories matching the criteria descriptions
10. Check `data/reviews/{id}.json` on disk — confirm `framework` key is present with `template_name`, `template_id`, and `criteria` snapshot
