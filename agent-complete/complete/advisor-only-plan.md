# Plan: Advisor-Only Records (No Invite Email)

## Context
A BDS rep cannot review a call unless the advisor has been invited as a platform user. The fix allows adding an advisor to a firm with just a name — no email, no invite sent — so calls can be reviewed immediately without waiting for the advisor to join the platform. These advisor-only profiles appear in the upload form's advisor dropdown like any other advisor.

## Database Migration (manual — run in Supabase SQL editor)
```sql
ALTER TABLE profiles
  ADD COLUMN is_platform_user boolean NOT NULL DEFAULT true;
```
No backfill needed — all existing rows correctly default to `true`.

## Backend Changes

### 1. `backend/modules/user_profiles.py`
Add `create_advisor_only(name: str, firm_id: str) -> dict` after `create_user`:
- Add `import secrets` and `from uuid import uuid4` at the top
- Generate `placeholder_email = f"advisor-{uuid4()}@noreply.internal"`
- Create a shadow auth user with no email sent:
  ```python
  user_resp = await client.auth.admin.create_user({
      "email": placeholder_email,
      "password": secrets.token_urlsafe(32),
      "email_confirm": True,
  })
  user_id = str(user_resp.user.id)
  ```
- Insert profile row with `is_platform_user: False`, `email: placeholder_email`, `name`, `firm_id`, `role: "financial_advisor"`, `is_active: True`
- `delete_user` and `set_active` require no changes — the shadow auth user is a real `auth.users` row

### 2. `backend/routers/management.py`
Update `UserBody` model (make email optional, add `send_invite` flag):
```python
class UserBody(BaseModel):
    email: str | None = None
    name: str
    role: str
    firm_id: str | None = None
    send_invite: bool = True
```

Update `create_new_user` handler with branching logic:
- If `send_invite=True`: require email, call existing `create_user()`
- If `send_invite=False`: require `firm_id`, require `role == "financial_advisor"`, call new `create_advisor_only()`
- Add `create_advisor_only` to the import from `modules.user_profiles`

## Frontend Changes

### 3. `frontend/src/pages/FirmDetailPage.jsx`

**State**: Add `const [sendInvite, setSendInvite] = useState(true)`. Reset to `true` on cancel.

**Updated `handleAddFa`**:
- Validate: name always required; email required only when `sendInvite=true`
- Build payload: `{name, role, firm_id, send_invite: sendInvite, ...(sendInvite ? {email} : {})}`
- Call `createUser(payload)` (api.js passes through all fields)
- Reset `sendInvite` to `true` on success

**Updated add-FA form JSX**:
- Email input rendered only when `sendInvite` is true
- Add checkbox below the input row:
  ```jsx
  <label className="firm-detail-page__invite-toggle">
    <input type="checkbox" checked={sendInvite}
      onChange={(e) => { setSendInvite(e.target.checked); setFaError(null) }} />
    Send platform invitation
  </label>
  ```

**Updated `UserRow` component** — branch on `user.is_platform_user`:
- When `is_platform_user === false`: hide email, hide Deactivate/Reactivate button, show `"Advisor"` badge with class `user-row__status--advisor-only`
- When `is_platform_user !== false`: existing behavior unchanged (email, Active/Inactive badge, Deactivate button)

Note: `services/api.js` requires no changes — `createUser()` already passes through any object fields.

### 4. `frontend/src/pages/FirmDetailPage.css`
Add two new rules:
```css
.user-row__status--advisor-only {
  background-color: rgba(252, 213, 53, 0.12);
  color: var(--color-primary);
}

.firm-detail-page__invite-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: 13px;
  color: var(--color-muted);
  margin-top: var(--space-xs);
  cursor: pointer;
  user-select: none;
}

.firm-detail-page__invite-toggle input[type="checkbox"] {
  accent-color: var(--color-primary);
  cursor: pointer;
}
```

## Execution Order
1. Run SQL migration in Supabase
2. Edit `user_profiles.py` — add `create_advisor_only`
3. Edit `management.py` — update `UserBody` and handler
4. Edit `FirmDetailPage.jsx` — state, validation, form JSX, `UserRow` branching
5. Edit `FirmDetailPage.css` — badge + toggle CSS
6. Update `context/log.md`, `context/map.md`, `context/decisions.md`

## Verification
1. Add advisor-only: uncheck "Send platform invitation", enter name only → row appears with yellow "Advisor" badge, no email, no Deactivate button
2. Upload regression: advisor-only record appears in upload form advisor dropdown; submitting a call with them succeeds (`get_profile()` finds the shadow profile row)
3. Invite regression: check "Send platform invitation" (default) → existing invite flow works; row shows email + Active + Deactivate
4. Delete works: delete button on advisor-only row works; `delete_user` deletes both the shadow auth user and the profile row
5. Existing rows unaffected: all existing FA/BDS rep rows have `is_platform_user = true` by default; `UserRow` appearance unchanged
