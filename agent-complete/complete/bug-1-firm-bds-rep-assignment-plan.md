# Bug #1 — Assign BDS rep on firm creation

## Problem
The `firms` table has a `bds_rep_id` column ("the assigned BDS rep", per the 2026-05-25 auth
decision), and `FirmDetailPage` can reassign it on an existing firm. But it is **never set at
creation time**, so every new firm starts unassigned until someone opens firm detail and picks a rep.

Both creation paths omit the field:
- **Quick add on upload screen** — `UploadPage.handleCreateFirm` → `createFirm({ name })`.
- **Management add-firm form** — `FirmsTab.handleAdd` → `createFirm({ name, template_id })`.

`POST /firms` (`management.py`) calls `save_firm(body.model_dump())`; `FirmBody.bds_rep_id`
defaults to `None`, so the firm row is created with `bds_rep_id = null`.

## Desired behavior
A firm created by a BDS rep is assigned to **that** rep — resolved server-side from the
authenticated user (`require_bds_rep` exposes `user["user_id"]`), not trusted from the client.
Decision (confirmed with user): **always assign the creator** when none is specified; reassignment
stays on the firm detail page. No new picker on the creation forms.

## Changes

### Backend (only) — `backend/routers/management.py`, `create_firm`
Default `bds_rep_id` to the creating user when the request doesn't carry one. `POST /firms` is only
ever called by the two creation forms (neither sends a rep); `FirmDetailPage` uses `PUT`, so a simple
falsy-check is sufficient and readable:

```python
@router.post("/firms")
async def create_firm(body: FirmBody, user: dict = Depends(require_bds_rep)):
    data = body.model_dump()
    if not data.get("bds_rep_id"):
        data["bds_rep_id"] = user["user_id"]
    return await save_firm(data)
```

`save_firm` needs no change — it upserts whatever dict it's handed.

### Frontend
No changes. Both creation paths already omit `bds_rep_id`, so the backend default applies.

## Testing (CLAUDE.md robust-testing guidance)
- Backend test: `POST /firms` with no `bds_rep_id` stores the caller's `user_id`; with an explicit
  `bds_rep_id` stores that value verbatim (guards against the default clobbering a real choice).
  Run with `py -m pytest`.
- Manual: create a firm via upload quick-add and via the management form → firm detail shows the
  creating rep as Assigned BDS Rep.

## Docs
- `context/log.md` — change entry.
- `context/decisions.md` — note: firm creation defaults `bds_rep_id` to the creator when
  unspecified (extends the 2026-05-25 firm-ownership model).
- `context/map.md` — update the `POST /firms` description under `routers/management.py`.
- No `deferredwork.md` items (no env vars / dummy data) and remove Bug #1 from `bug-corrections.md`
  once shipped.
