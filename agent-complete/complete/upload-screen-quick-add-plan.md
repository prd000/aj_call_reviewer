# Add firm/advisor from the upload screen (+ promote advisor-only later)

## Context

Today, a BDS rep wanting to review a call for a not-yet-existing firm or advisor has to leave the upload page, go to **Management → Firms**, create the firm, open Firm Detail, add the advisor, and only then go back to upload. That's three pages of friction for a flow that should be one. This was raised as Feature #6 in `context/bug-corrections.md`.

The desired flow: a small **+ New** affordance next to the **Firm** and **Advisor** dropdowns on the upload screen. Click it, type a name, click Add — the new entry is created and auto-selected in the dropdown. For advisors, the entry is **advisor-only** by default (shadow auth user, no invite email, `is_platform_user: False`) — matching the architecture established in `context/decisions.md` (2026-05-26 entry).

The user also asked for a way to **promote** an advisor-only entry into a full platform user later (e.g. "John Smith was a placeholder for months, now I want to invite him"). Today the Firm Detail page only offers **Delete** on advisor-only rows. We'll add an **Invite as user** action that updates the existing auth row in place — same `id`, same linked reviews — so historical data stays intact.

## Scope

1. **Upload screen — "+ New" on Firm and Advisor dropdowns** (BDS-rep mode only).
2. **Firm Detail — "Invite as user" button on advisor-only rows**, converting in place.

Both pieces reuse existing backend behavior where possible. The promotion path needs one new backend function + endpoint.

## Decisions locked in from clarifying questions

- **Add Firm**: name only. Template and BDS rep stay null; BDS rep can set those later in Firm Detail.
- **Add Advisor**: strictly advisor-only on this screen — single name field, no email, no invite toggle. The full invite flow stays on Firm Detail.
- **UI**: Small `+ New` button to the right of each field's label. Clicking reveals a one-row inline form below the dropdown (name input + **Add** button); the same button toggles back to **Cancel**. This mirrors the existing FA-add pattern in `FirmDetailPage.jsx:289–341`.
- **Auto-select**: After successful create, the new firm/advisor becomes the dropdown's selected value. Creating a firm auto-fires `onFirmChange`, which refreshes the advisor list for that firm (will be empty — that's fine and expected).

## Backend changes

### 1. `backend/modules/user_profiles.py` — add `promote_advisor_to_user`

```python
async def promote_advisor_to_user(user_id: str, email: str) -> dict
```

- Fetch the profile; raise if missing or if `is_platform_user` is already `True`.
- Check no other profile already uses `email` (same uniqueness guard as `create_user`, line 30–32).
- `client.auth.admin.update_user_by_id(user_id, {"email": email, "email_confirm": True})` — replace the `advisor-{uuid}@noreply.internal` placeholder with the real address; keep email confirmed so the user is not blocked on a separate confirm step.
- Send a password-set email so the user can choose a password and log in. Reuse the same `redirect_to: {VITE_APP_URL}/set-password` pattern from `create_user` (line 35–36). The simplest mechanism: `client.auth.admin.generate_link({"type": "recovery", "email": email, "options": {"redirect_to": ...}})` and rely on Supabase to dispatch it; fall back to `client.auth.reset_password_for_email(email, {redirect_to})` if the admin link call isn't viable in this SDK version.
- Update the `profiles` row: `email`, `is_platform_user = True`, `updated_at = now`.
- Return the refreshed profile dict.

### 2. `backend/routers/management.py` — add `POST /users/{id}/promote`

- New body model: `class PromoteUserBody(BaseModel): email: str`.
- Route: `POST /users/{user_id}/promote`, gated by `require_bds_rep`.
- Calls `promote_advisor_to_user(user_id, body.email)`; wraps `ValueError` → `HTTPException(400)` like the existing `create_new_user` handler (line 106–125).

The existing `POST /firms` and `POST /users` (with `send_invite: false`) already cover the upload-screen create flows — no other backend work needed there.

## Frontend changes

### 3. `frontend/src/services/api.js` — add `promoteAdvisor`

```js
export async function promoteAdvisor(userId, email)
```

POST to `/api/users/{userId}/promote` with `{ email }`, following the same `authHeaders` + `handleResponse` pattern as `createUser` (line 213–221).

### 4. `frontend/src/components/UploadForm.jsx` + `UploadForm.css` — "+ New" toggles + inline add rows

In BDS-rep mode only (`isBds` branch, line 89–130):

- Add state: `showAddFirm`, `newFirmName`, `isCreatingFirm`, `firmAddError` — and mirrored advisor variants.
- Render label as a row: `<label>` + flexed-right `<button type="button" class="upload-form__inline-add">+ New</button>` (or **Cancel** when expanded).
- When `showAddFirm` is true, render an `upload-form__add-row` directly below the firm dropdown: a name `<input>` styled with the existing `.upload-form__input` class + a yellow **Add** button. Submission calls a new prop `onCreateFirm(name)`.
- Same shape for advisor: only enabled when `selectedFirmId` is set (re-use the existing "Select a firm first" gating).
- On the form's `onSubmit`, ignore inline-add inputs — the **Add** button has `type="button"` and its own handler.
- CSS: add `.upload-form__field-header` (flex row, space-between for label + + New button), `.upload-form__inline-add` (small ghost link-style button), `.upload-form__add-row` (flex row, input grows, Add button fixed width, margin-top: var(--space-xs)). Reuse existing input/button tokens — no new colors.

### 5. `frontend/src/pages/UploadPage.jsx` — wire up create handlers

- Add two handlers:
  - `handleCreateFirm(name)` → `await createFirm({ name })` → push the returned firm into `firms` state (the returned dict has `id` + `name`, which is all the dropdown needs) → `setSelectedFirmId(firm.id)` (via a setter exposed by UploadForm, or by passing the new id back through a `selectedFirmId` controlled prop — see note below) → call `handleFirmChange(firm.id)` to refresh `firmAdvisors`.
  - `handleCreateAdvisor(name, firmId)` → `await createUser({ name, role: 'financial_advisor', firm_id: firmId, send_invite: false })` → push into `firmAdvisors` state → auto-select.
- **Selection state ownership**: today `selectedFirmId` and `selectedAdvisorId` live inside `UploadForm`. To auto-select from the parent's create callback, the cleanest path is to lift those two pieces of state up to `UploadPage`, passing them down as controlled props (`selectedFirmId`, `selectedAdvisorId`, `onSelectFirm`, `onSelectAdvisor`). This is a small refactor inside `UploadForm.jsx:24–26` — keep all other state local.
- Pass `onCreateFirm` and `onCreateAdvisor` props to `UploadForm`.

### 6. `frontend/src/pages/FirmDetailPage.jsx` + `.css` — "Invite as user" on advisor-only rows

In `UserRow` (line 16–95):

- When `isAdvisorOnly` is true, render an **Invite as user** button alongside the existing Delete button (replacing the absence of the Deactivate button for these rows).
- Clicking it reveals an inline `<input type="email" placeholder="Email address">` + **Send invite** button, in the same style as the existing inline delete-confirm UI (line 67–91).
- Successful invite calls `promoteAdvisor(user.id, email)` via a new `onPromote` callback passed from `FirmDetailPage`.
- After success, update the row's state: `is_platform_user: true`, replace placeholder email with the real one. The row will then render normally (email visible, "Active" status badge, Deactivate button) on next render because the existing conditionals key off `isAdvisorOnly = is_platform_user === false`.
- `FirmDetailPage`'s `handlePromote` updates the relevant entry in `users` state with the returned profile.

## Files NOT changing

- `backend/modules/firms.py` — `save_firm` already creates a firm from `{name}` alone (id/timestamps auto-fill).
- `backend/routers/upload.py` — same payload shape; the new firm/advisor IDs flow through the existing form fields.
- `backend/modules/auth.py`, `tasks.py`, anything in `reviews.py` — none touched.

## Context-folder updates (per CLAUDE.md)

- `context/log.md` — chronological entry for this feature.
- `context/map.md` — note `promoteAdvisor` in `api.js`; note new handlers in `UploadPage`/`UploadForm`; note `promote_advisor_to_user` in `user_profiles.py` and the new POST route in `management.py`.
- `context/decisions.md` — extend the 2026-05-26 "Advisor-only profiles" entry with a short addendum: "advisor-only rows can be promoted in place via `POST /users/{id}/promote`; same auth `id`, so historical reviews stay linked."

## Verification

End-to-end manual flow (the user is the BDS rep `pdineen6@gmail.com`):

1. **Start the app**: `py -m uvicorn main:app --reload` from `backend/`; `npm run dev` from `frontend/` (or run `start.ps1` from repo root).
2. **Add firm from upload**: log in as BDS rep → on Upload page click `+ New` next to **Firm** → type `Test Firm A` → **Add**. Confirm: new firm appears as the selected option in the dropdown; advisor dropdown shows "No advisors at this firm".
3. **Add advisor from upload**: click `+ New` next to **Advisor** → type `Test Advisor X` → **Add**. Confirm: new advisor is the selected option. Fill out prospect name + file and submit a real review; confirm it processes and the resulting review record is linked to that firm/advisor (visible in History).
4. **Promote advisor-only → user**: navigate to Management → Test Firm A → on the Test Advisor X row, click **Invite as user** → enter a real email (use a `+tag` alias of your own Gmail) → **Send invite**. Confirm: the row immediately renders with email visible and an Active badge; check your inbox for the password-set email; click through the link and confirm `/set-password` works and the advisor can log in.
5. **Regression check**: as the now-promoted advisor, log in and confirm History shows the review you generated against the placeholder record in step 3 (same `user_id` survived the promotion).
6. **Error paths**: try creating a firm with an empty name (should show inline validation); try promoting using an email that already belongs to another user (backend returns 400, frontend should surface the message).

Backend smoke test, if a quick non-UI sanity check is wanted before wiring the UI:

```
curl -X POST http://localhost:8000/api/users/<advisor-only-user-id>/promote \
  -H "Authorization: Bearer <BDS-rep-JWT>" \
  -H "Content-Type: application/json" \
  -d '{"email":"someone@example.com"}'
```
