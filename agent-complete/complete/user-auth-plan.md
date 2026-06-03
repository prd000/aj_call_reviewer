# Plan: User Authentication — BDS Reps & Financial Advisors

## Context

The call review app is transitioning from a single-tenant internal tool to a multi-user product serving two distinct audiences: BDS reps (sales coaches who upload and review calls) and financial advisors (clients who upload their own calls and view their firm's reviews). This plan implements Supabase Auth-based login with role-based access control, a Management section for user/firm administration, and a firms table that anchors data ownership.

**Key access rules decided:**
- BDS reps see ALL reviews (both their own uploads and FA uploads)
- FAs see only FA-uploaded reviews for their own firm (not BDS rep uploads)
- Firm association controls what FAs can see; uploader role controls BDS visibility exclusion
- FAs cannot pick a template; the firm's assigned template is applied automatically
- BDS reps manage everything (firms, users) from a new Management section

---

## Decisions Made (grill-me session)

- **Auth provider**: Supabase Auth (JWT); frontend uses `@supabase/supabase-js`, backend validates JWTs via `supabase.auth.get_user(token)`
- **Account creation**: In-app by BDS reps only; user gets a password-reset email to set their own password on first login
- **Roles**: `bds_rep` and `financial_advisor`; stored in a `profiles` table alongside `firm_id`, `name`, `is_active`
- **Firms table**: Explicit table (no auto-derive from free-text); each firm has `name`, `template_id`, `bds_rep_id` (assigned BDS rep); one BDS rep can be assigned to many firms; many firms can share one template
- **Upload form — FA**: Advisor name + firm pre-filled (read-only from profile); prospect name free text; template auto-applied from firm; BDS rep field removed
- **Upload form — BDS rep**: Firm dropdown → advisor dropdown (FAs at that firm) → prospect name free text; Template Manager shown; BDS rep field removed
- **Visibility rule**: Reviews store `uploaded_by` (user UUID) and `uploader_role`; FA queries filter `firm_id = user.firm_id AND uploader_role = 'financial_advisor'`; BDS queries return all
- **Existing reviews**: Left as-is (no `firm_id`, no `uploaded_by`); BDS reps still see them; FAs start fresh and cannot see pre-auth reviews
- **Routing post-login**: Both roles land on `/` (Upload page)
- **Nav**: BDS gets Upload + History + Management; FA gets Upload + History only
- **Management section (BDS-only)**:
  - *Firms tab*: list all firms → click → firm detail (edit name, template, assigned BDS rep; manage FA users at this firm)
  - *BDS Reps tab*: list BDS rep users; create, deactivate, delete
  - FA users are created and managed within their firm's detail view
- **Firm deletion**: Confirmation dialog required → auto-deactivate all FA users at that firm → reviews stay permanently
- **User deactivation**: Uses Supabase `ban_duration` ("876600h" = effectively permanent; "none" to reactivate)
- **Password reset**: "Forgot password?" link on login page → Supabase sends email
- **User profile editing**: BDS reps only, in Management section

---

## Step 1 — Supabase Schema Changes (manual SQL)

Run in Supabase SQL editor:

```sql
-- Firms table
CREATE TABLE firms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    template_id TEXT REFERENCES templates(id) ON DELETE SET NULL,
    bds_rep_id UUID,  -- FK to auth.users; nullable (can be unassigned)
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX firms_name_idx ON firms (name);

-- User profiles table (extends Supabase auth.users)
CREATE TABLE profiles (
    id UUID PRIMARY KEY,  -- matches auth.users.id
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('bds_rep', 'financial_advisor')),
    firm_id TEXT REFERENCES firms(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX profiles_role_idx ON profiles (role);
CREATE INDEX profiles_firm_id_idx ON profiles (firm_id);

-- Add auth columns to reviews
ALTER TABLE reviews
    ADD COLUMN firm_id TEXT REFERENCES firms(id) ON DELETE SET NULL,
    ADD COLUMN uploaded_by UUID,  -- auth.users.id of uploader
    ADD COLUMN uploader_role TEXT; -- 'bds_rep' or 'financial_advisor'

CREATE INDEX reviews_firm_id_idx ON reviews (firm_id);
CREATE INDEX reviews_uploaded_by_idx ON reviews (uploaded_by);
CREATE INDEX reviews_uploader_role_idx ON reviews (uploader_role);
```

---

## Step 2 — Backend: Auth Dependency

**New file: `backend/modules/auth.py`**

FastAPI dependency that extracts and validates the Supabase JWT from the `Authorization: Bearer <token>` header. Returns a dict with `user_id`, `role`, `firm_id`, `name`, `is_active`.

```python
from fastapi import Depends, HTTPException, Header
from modules.supabase_client import get_client

async def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401)
    token = authorization.removeprefix("Bearer ")
    try:
        resp = get_client().auth.get_user(token)
        auth_user = resp.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    profile = get_client().table("profiles").select("*").eq("id", str(auth_user.id)).execute()
    if not profile.data:
        raise HTTPException(status_code=401, detail="No profile found")
    p = profile.data[0]
    if not p["is_active"]:
        raise HTTPException(status_code=403, detail="Account deactivated")
    return {"user_id": str(auth_user.id), "role": p["role"],
            "firm_id": p.get("firm_id"), "name": p["name"]}

def require_bds_rep(user=Depends(get_current_user)):
    if user["role"] != "bds_rep":
        raise HTTPException(status_code=403, detail="BDS reps only")
    return user
```

---

## Step 3 — Backend: Firms Module

**New file: `backend/modules/firms.py`**

CRUD following the same supabase-py pattern as `templates.py`:
- `list_firms()` → all firms with template name joined; `.select("*, templates(name)")`
- `get_firm(firm_id)` → single firm row or None
- `get_firm_users(firm_id)` → all profiles where `firm_id = firm_id`
- `save_firm(firm)` → upsert; UUID + timestamps managed in Python
- `delete_firm(firm_id)` → deactivate all FA profiles at this firm first (batch `update().eq("firm_id", ...).eq("role", "financial_advisor")`), then delete firm row; reviews untouched

---

## Step 4 — Backend: User Profiles Module

**New file: `backend/modules/user_profiles.py`**

- `list_bds_reps()` → profiles where role = 'bds_rep'
- `get_profile(user_id)` → single profile or None
- `create_user(email, name, role, firm_id)`:
  1. `get_client().auth.admin.create_user({"email": email, "email_confirm": True})` — creates auth user
  2. Generate password reset link: `get_client().auth.admin.generate_link({"type": "recovery", "email": email})` — Supabase emails the user a set-password link
  3. Insert profile row with returned `user.id`
- `update_profile(user_id, data)` → update name, firm_id; upsert profile row
- `set_active(user_id, active: bool)`:
  - Deactivate: `auth.admin.update_user_by_id(user_id, {"ban_duration": "876600h"})`
  - Reactivate: `auth.admin.update_user_by_id(user_id, {"ban_duration": "none"})`
  - Update `is_active` in profiles table to match
- `delete_user(user_id)` → `auth.admin.delete_user(user_id)`, delete profile row

---

## Step 5 — Backend: Management Router

**New file: `backend/routers/management.py`**

All endpoints require `require_bds_rep` dependency. Register under `/api` prefix in `main.py`.

```
GET    /api/firms                        → list_firms()
POST   /api/firms                        → save_firm()
GET    /api/firms/{firm_id}              → get_firm() + get_firm_users()
PUT    /api/firms/{firm_id}              → save_firm() (update)
DELETE /api/firms/{firm_id}              → delete_firm() (confirm on frontend)

GET    /api/users/me                     → get_profile() for calling user (any role)
GET    /api/users/bds-reps               → list_bds_reps()
POST   /api/users                        → create_user()
PUT    /api/users/{user_id}              → update_profile()
PATCH  /api/users/{user_id}/active       → set_active()
DELETE /api/users/{user_id}              → delete_user()
```

---

## Step 6 — Backend: Update Upload Router

**Modify: `backend/routers/upload.py`**

Add `get_current_user` dependency to the upload endpoint.

Changes:
- Remove `bds_rep` form field
- Add `firm_id` and `uploader_role` to the review record before saving:
  - **FA**: `firm_id = user["firm_id"]`; `advisor_name` pulled from `user["name"]`; `template_id` looked up from `firms.get_firm(user["firm_id"])["template_id"]`; `uploader_role = "financial_advisor"`
  - **BDS rep**: `firm_id` from form field (selected firm); `advisor_name` from selected FA user's profile; `template_id` from form (TemplateManager); `uploader_role = "bds_rep"`
- Add `uploaded_by = user["user_id"]` to all reviews

---

## Step 7 — Backend: Update Reviews Router

**Modify: `backend/routers/reviews.py`**

Add `get_current_user` dependency to all endpoints.

Visibility filtering in `list_reviews()` call:
```python
# BDS rep: no filter — sees all reviews
# FA: filter by firm + uploader_role
if user["role"] == "financial_advisor":
    reviews = storage.list_reviews(
        firm_id=user["firm_id"],
        uploader_role="financial_advisor"
    )
else:
    reviews = storage.list_reviews()
```

**Modify: `backend/modules/storage.py`**
- Add optional `firm_id` and `uploader_role` params to `list_reviews()`; apply `.eq()` filters when set
- Update `_to_row()` / `_from_row()` to include `firm_id`, `uploaded_by`, `uploader_role`
- Remove `bds_rep` from `_to_row()` mapping

---

## Step 8 — Frontend: Supabase Client + AuthContext

**New file: `frontend/src/lib/supabase.js`**

```js
import { createClient } from '@supabase/supabase-js'
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
)
```

**New file: `frontend/src/context/AuthContext.jsx`**

React context providing:
- `user` state: `{ id, name, role, firm_id }` or null
- `session` state: Supabase session (contains JWT)
- `login(email, password)` → `supabase.auth.signInWithPassword()`; fetches profile from `/api/users/me`
- `logout()` → `supabase.auth.signOut()`; clear user state
- `forgotPassword(email)` → `supabase.auth.resetPasswordForEmail(email)`
- On mount: `supabase.auth.getSession()` to restore session across page refreshes
- `supabase.auth.onAuthStateChange()` listener to sync session changes

**Install**: `npm install @supabase/supabase-js` in `frontend/`

**New env vars** in `.env` (and `.env.example`):
```
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=   # public anon key (safe to expose in frontend)
```

---

## Step 9 — Frontend: API Layer Auth Headers

**Modify: `frontend/src/services/api.js`**

Add a helper that injects the JWT into every request:

```js
import { supabase } from '../lib/supabase'

async function authHeaders() {
  const { data: { session } } = await supabase.auth.getSession()
  return session ? { Authorization: `Bearer ${session.access_token}` } : {}
}
```

Update every `fetch()` call to `await authHeaders()` and merge into headers. Add 401 handling in `handleResponse()` that calls `supabase.auth.signOut()` and redirects to `/login`.

Also add new API functions:
- `listFirms()`, `createFirm(data)`, `updateFirm(id, data)`, `deleteFirm(id)`
- `getFirmDetail(id)` (firm + its users)
- `listBdsReps()`, `createUser(data)`, `updateUser(id, data)`, `setUserActive(id, active)`, `deleteUser(id)`
- `getCurrentUserProfile()` → `GET /api/users/me`

---

## Step 10 — Frontend: Login Page

**New files: `frontend/src/pages/LoginPage.jsx` / `LoginPage.css`**

Design: centered card on dark canvas (`--color-surface`), matching existing card style.
- Email + password inputs using existing `.upload-form__input` CSS class pattern
- "Sign In" primary button (yellow, full width)
- "Forgot password?" text link below button → calls `forgotPassword(email)`; shows success message
- Errors displayed using existing `.upload-form__error` pattern
- On successful login: `navigate('/')` (Upload page)
- If already authenticated on mount: redirect to `/`

---

## Step 11 — Frontend: Protected Routes + App Routing

**Modify: `frontend/src/App.jsx`**

```jsx
// New route structure:
<Route path="/login" element={<LoginPage />} />
<Route element={<ProtectedRoute />}>
  <Route path="/" element={<UploadPage />} />
  <Route path="/results/:id" element={<ResultsPage />} />
  <Route path="/history" element={<HistoryPage />} />
  <Route element={<BdsRepRoute />}>  {/* requires bds_rep role */}
    <Route path="/management" element={<ManagementPage />} />
    <Route path="/management/firms/:id" element={<FirmDetailPage />} />
  </Route>
</Route>
```

**New file: `frontend/src/components/ProtectedRoute.jsx`**

Checks `AuthContext` — if no session, redirects to `/login`. If session exists, renders `<Outlet />`.

**New file: `frontend/src/components/BdsRepRoute.jsx`**

Checks `user.role === 'bds_rep'` — if not, redirects to `/`. Renders `<Outlet />` if authorized.

---

## Step 12 — Frontend: TopNav Updates

**Modify: `frontend/src/components/TopNav.jsx` / `TopNav.css`**

- Add `Management` NavLink (only rendered when `user.role === 'bds_rep'`)
- Add right-side user section: display `user.name`, a `Logout` button
- Logout button calls `logout()` from AuthContext, then `navigate('/login')`
- If no user session: show nothing (login page handles itself outside the nav)

---

## Step 13 — Frontend: UploadForm Role-Based Fields

**Modify: `frontend/src/components/UploadForm.jsx` / `UploadForm.css`**

The component receives a `userRole`, `userName`, `userFirmName`, `firms[]`, and `firmAdvisors[]` (populated after firm selection) as props.

**FA mode** (`userRole === 'financial_advisor'`):
- Advisor Name: read-only input pre-filled with `userName`
- Firm Name: read-only input pre-filled with `userFirmName`
- Prospect Name: free text (required)
- BDS Rep field: removed
- No template selector

**BDS rep mode**:
- Firm: `<select>` populated from `firms` prop; on change triggers `onFirmChange` callback to fetch advisors
- Advisor Name: `<select>` populated from `firmAdvisors` (FA users at selected firm)
- Prospect Name: free text (required)
- BDS Rep field: removed
- Template Manager stays (unchanged)

**Modify: `frontend/src/pages/UploadPage.jsx`**

- Read `user` from AuthContext
- For BDS rep: fetch firms on mount; fetch firm advisors when firm selection changes
- For FA: fetch firm name from profile
- Pass role-specific props down to UploadForm
- For FA upload: append `firm_id` (from user profile) to FormData instead of text `firm`
- For BDS upload: append selected `firm_id` and `advisor_user_id` (instead of free-text advisor name)
- Hide `<TemplateManager>` when `userRole === 'financial_advisor'`

---

## Step 14 — Frontend: History Page Updates

**Modify: `frontend/src/pages/HistoryPage.jsx`**

- Backend now handles FA filtering server-side; frontend receives only visible reviews
- Firm dropdown filter: for BDS reps, populate from `listFirms()` API (not derived from review records); for FAs it's irrelevant (all their reviews are same firm)
- Advisor dropdown: still derived from review records (no change needed)
- BDS Rep filter: remove (field no longer exists on reviews)

---

## Step 15 — Frontend: Management Section

**New files: `frontend/src/pages/ManagementPage.jsx` / `ManagementPage.css`**

Two-tab layout (Firms | BDS Reps) using the existing card/surface design tokens.

**New files: `frontend/src/components/FirmsTab.jsx` / `FirmsTab.css`**
- Table/list of all firms: name, assigned BDS rep, assigned template
- "Add Firm" button → inline form: firm name, template dropdown, BDS rep dropdown
- Click a firm → navigate to `/management/firms/:id`

**New files: `frontend/src/pages/FirmDetailPage.jsx` / `FirmDetailPage.css`**

Route: `/management/firms/:id`

Shows:
- Editable firm name (text input + Save button)
- Template selector (dropdown of all templates)
- Assigned BDS rep selector (dropdown of all BDS rep users)
- List of FA users: name, email, active status; deactivate/reactivate toggle; delete button
- "Add Financial Advisor" button → inline form: name + email → calls `createUser()` with role=financial_advisor
- "Delete Firm" button → confirmation dialog ("This will deactivate X users. Continue?") → `deleteFirm()`

**New files: `frontend/src/components/BdsRepsTab.jsx` / `BdsRepsTab.css`**
- Table of BDS rep users: name, email, active status
- "Add BDS Rep" button → inline form: name + email → calls `createUser()` with role=bds_rep
- Per-row: deactivate/reactivate toggle; delete button (with confirmation)

---

## Critical Files Summary

| File | Action |
|---|---|
| Supabase SQL editor | **RUN** — create `firms`, `profiles` tables; alter `reviews` |
| `backend/modules/auth.py` | **CREATE** — `get_current_user`, `require_bds_rep` dependencies |
| `backend/modules/firms.py` | **CREATE** — firms CRUD |
| `backend/modules/user_profiles.py` | **CREATE** — profiles CRUD + Supabase admin user management |
| `backend/routers/management.py` | **CREATE** — firms + users management endpoints |
| `backend/routers/upload.py` | **MODIFY** — auth dependency, role-based field handling, firm_id/uploader_role |
| `backend/routers/reviews.py` | **MODIFY** — auth dependency, FA visibility filtering |
| `backend/modules/storage.py` | **MODIFY** — `list_reviews()` filter params, `_to_row`/`_from_row` updates |
| `backend/main.py` | **MODIFY** — register management router |
| `frontend/package.json` | **MODIFY** — add `@supabase/supabase-js` |
| `frontend/src/lib/supabase.js` | **CREATE** — Supabase client |
| `frontend/src/context/AuthContext.jsx` | **CREATE** — auth state, login, logout, forgotPassword |
| `frontend/src/pages/LoginPage.jsx` + `.css` | **CREATE** |
| `frontend/src/components/ProtectedRoute.jsx` | **CREATE** |
| `frontend/src/components/BdsRepRoute.jsx` | **CREATE** |
| `frontend/src/App.jsx` | **MODIFY** — new routes, protected route wrappers |
| `frontend/src/components/TopNav.jsx` + `.css` | **MODIFY** — Management link (BDS only), user name, logout |
| `frontend/src/services/api.js` | **MODIFY** — auth headers, 401 handling, new management API functions |
| `frontend/src/components/UploadForm.jsx` + `.css` | **MODIFY** — role-based fields |
| `frontend/src/pages/UploadPage.jsx` | **MODIFY** — role-based props, firm/advisor fetching |
| `frontend/src/pages/HistoryPage.jsx` | **MODIFY** — firm filter from API, remove BDS rep filter |
| `frontend/src/pages/ManagementPage.jsx` + `.css` | **CREATE** |
| `frontend/src/components/FirmsTab.jsx` + `.css` | **CREATE** |
| `frontend/src/pages/FirmDetailPage.jsx` + `.css` | **CREATE** |
| `frontend/src/components/BdsRepsTab.jsx` + `.css` | **CREATE** |
| `.env` / `.env.example` | **MODIFY** — add `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` |
| `context/decisions.md` | **UPDATE** |
| `context/log.md` | **UPDATE** |
| `context/map.md` | **UPDATE** |

---

## Existing Patterns to Reuse

- **Supabase CRUD pattern** (`templates.py`): `get_client().table(...).select().eq().execute()` — use identically in `firms.py` and `user_profiles.py`
- **`_to_row()` / `_from_row()` pattern** (`storage.py`): extend with new columns rather than replacing
- **CSS token classes**: `.upload-form__input`, `.upload-form__label`, `.upload-form__error` — reuse on login page and management forms
- **Card surface style** (`--color-surface`, `--color-surface-elevated`): reuse for management cards and firm detail view
- **Confirmation pattern**: inline confirmation already exists in `ReviewList.jsx` for delete — mirror this for firm delete and user delete

---

## Verification

1. **Schema**: Open Supabase dashboard → Table Editor → confirm `firms`, `profiles`, and new `reviews` columns exist
2. **Backend auth**: Start backend; call `GET /api/reviews` without a token → expect `422` (missing header); call with invalid token → expect `401`
3. **Login**: Open frontend → navigate to `/` → should redirect to `/login`; enter valid credentials → should land on Upload page
4. **Role routing**: Log in as BDS rep → Management link visible in nav; log in as FA → Management link absent
5. **FA upload**: Log in as FA → upload form shows read-only advisor/firm, free-text prospect; submit → review appears in History filtered to their firm
6. **BDS rep upload**: Log in as BDS rep → form shows firm dropdown, advisor dropdown populates after firm selection; submit → review visible in History
7. **Visibility**: BDS rep sees all reviews; FA sees only FA-uploaded reviews from their firm
8. **Management — Firms**: BDS rep creates a firm, assigns template and BDS rep; firm appears in upload dropdown
9. **Management — FA users**: BDS rep creates FA user from firm detail; user receives password-set email; FA logs in successfully
10. **Management — BDS Reps**: BDS rep creates another BDS rep; logs in as new rep → full access confirmed
11. **Firm delete**: Create firm with FAs → delete firm → confirm dialog → FAs deactivated → reviews still in DB; deactivated FA cannot log in
12. **Forgot password**: On login page, enter email → Supabase sends reset email; follow link → set new password → login succeeds
