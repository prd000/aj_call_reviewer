# SEC-001 Fix Plan — Lock down Supabase tables (RLS + grant revocation)

## Context

**Why:** SEC-001 is the only **Critical** finding in `context/security-review.md`. The entire authorization model lives in FastAPI, but the same data is reachable directly via Supabase PostgREST (`https://<proj>.supabase.co/rest/v1/<table>`) using the **public anon key** that ships in the React bundle (`frontend/src/lib/supabase.js:3-6`). With RLS disabled and Supabase's default `anon`/`authenticated` grants intact, anyone who loads the site can read/write every firm's `reviews`, `profiles`, `firms`, and `templates` — self-promote to `bds_rep`, exfiltrate transcripts/PII, delete data — all bypassing `_fa_can_access`, `require_bds_rep`, and firm scoping entirely.

**Verified during planning:**
- The frontend uses Supabase **only** for `supabase.auth.*` (`frontend/src/lib/supabaseAuth.js`). There are **zero** `.from()`, `.rpc()`, or `.storage` calls anywhere in `frontend/src` — all data and recordings flow through FastAPI (`frontend/src/services/api.js`).
- The backend uses the **service_role** key (`backend/modules/supabase_client.py:14`, `os.environ["SUPABASE_KEY"]`), which **bypasses RLS**.
- Storage I/O is entirely backend-mediated via service_role + signed URLs (`backend/modules/storage.py:134-161`).

**Outcome:** Because the browser never queries tables/storage directly, we can enable RLS in deny-all (lockdown) mode and revoke the public grants with **zero app breakage** — the service_role backend keeps working untouched. RLS becomes defense-in-depth behind the existing FastAPI authz. **Supabase Auth is unaffected** — it operates on the `auth` schema via GoTrue, not on `public`-schema grants, so login/refresh/password-reset continue to work.

**Chosen approach (confirmed with user):** Lockdown (RLS, no policies) · Blanket schema-wide · also harden the `recordings` Storage bucket.

---

## Part A — Supabase admin work (YOU run this in the Supabase SQL Editor)

This is the actual fix. It is **not** code the backend runs; you apply it once per environment in the Supabase dashboard → SQL Editor. The SQL is also committed to the repo (Part B) for version control.

### A1. Tables: revoke grants + enable RLS (blanket, schema-wide)
```sql
-- Revoke all access from the public-facing Postgres roles on existing objects.
REVOKE ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;

-- Enable RLS on every app table. With NO policies, all rows are denied to any
-- role that does not bypass RLS. service_role bypasses RLS, so the backend is unaffected.
ALTER TABLE public.profiles  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.firms     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reviews   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.templates ENABLE ROW LEVEL SECURITY;

-- Future tables: default to locked-down so a newly created table is never exposed.
-- (Default privileges apply to objects created by the running role; Supabase SQL
--  Editor runs as postgres. Include supabase_admin for dashboard-created tables.)
ALTER DEFAULT PRIVILEGES FOR ROLE postgres, supabase_admin IN SCHEMA public
  REVOKE ALL ON TABLES    FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres, supabase_admin IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres, supabase_admin IN SCHEMA public
  REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
```
> Note: `ENABLE RLS` alone already denies all rows when no policy exists; the `REVOKE` makes PostgREST return a clean permission error instead of an empty array. Doing both is the belt-and-suspenders recommendation.

### A2. Storage: verify the `recordings` bucket is private + has no public policies
Run these **read-only checks** and confirm the results:
```sql
-- Expect: recordings -> public = false
SELECT id, name, public FROM storage.buckets;

-- Expect: NO rows that grant anon/authenticated access to the recordings bucket.
SELECT polname, cmd, roles, qual FROM pg_policies WHERE schemaname = 'storage';
```
If the bucket shows `public = true`, set it to Private in dashboard → Storage → bucket settings. If any permissive `storage.objects` policy targets `anon`/`authenticated` for `recordings`, drop it. A private bucket with no such policy is already correct — backend signed URLs (`storage.py:143-152`) keep working because they're generated with service_role.

### A3. Caveat to confirm
`anon`/`authenticated` must be the only roles revoked — **do not** revoke from `service_role` or `postgres`. The backend connects as service_role; leave its grants and BYPASSRLS intact.

---

## Part B — Code/repo work (I do this)

No application logic changes are needed — the backend already routes everything through service_role. The repo work is documentation + version-controlling the SQL.

1. **New migration file** `backend/migrations/2026-06-05_enable_rls_lockdown.sql`
   - Contains the exact SQL from A1 (and the A2 verification queries as comments), with a header comment explaining intent, matching the existing migration style (`backend/migrations/2026-05-29_add_call_outcome.sql`). This records the change in git even though it's applied manually in Supabase.

2. **`context/decisions.md`** — amend the 2026-05-18 entry (`decisions.md:362`, "no RLS; access control enforced in FastAPI layer"). Add a dated 2026-06-05 update: RLS now ENABLED in deny-all lockdown mode + anon/authenticated grants revoked as defense-in-depth; FastAPI/service_role remains the authorization layer; SEC-001 resolved. Add a standing rule: **any new `public` table must be locked down** (re-run the blanket REVOKE + `ENABLE RLS`), since `ALTER DEFAULT PRIVILEGES` covers grants but `ENABLE RLS` must still be set per new table.

3. **`context/security-review.md`** — set SEC-001 `Status: Fixed (Supabase lockdown applied 2026-06-05; verify per Part C)`; add a Session Log line.

4. **`context/log.md`** — add an entry (required by CLAUDE.md on every change).

5. **`context/bug-corrections.md`** — mark the RLS item (#1) addressed, if present.

6. **`context/map.md`** — add the new migration file if migrations are catalogued there (check first; add only if the section exists).

7. **`.env.example`** (optional, minor) — the `VITE_SUPABASE_ANON_KEY` "safe to expose" comment is now actually true; leave a one-line note that exposure is safe *because* RLS lockdown is in place.

---

## Part C — Verification (we do together, after Part A is applied)

**Negative test — the exposure must be closed.** Using the public anon key (from the JS bundle / `.env`), hit PostgREST directly; each must return a permission error / `401` / `[]`, **not** data:
```bash
curl 'https://<proj>.supabase.co/rest/v1/reviews?select=*' \
  -H "apikey: <ANON_KEY>" -H "Authorization: Bearer <ANON_KEY>"
# repeat for profiles, firms, templates
# also confirm a write is rejected:
curl -X PATCH 'https://<proj>.supabase.co/rest/v1/profiles?id=eq.<any>' \
  -H "apikey: <ANON_KEY>" -H "Authorization: Bearer <ANON_KEY>" \
  -H "Content-Type: application/json" -d '{"role":"bds_rep"}'
```

**Positive test — the app must still work** (all via FastAPI/service_role):
- Log in (confirms Auth unaffected), list reviews, open a review and play its audio (signed URL), upload a call, run review chat + history chat.

**No-rotation note:** the anon key does **not** need rotating — it is designed to be public and is now safe to expose because the tables are locked down.

---

## Files touched
- **New:** `backend/migrations/2026-06-05_enable_rls_lockdown.sql`
- **Edited (docs):** `context/decisions.md`, `context/security-review.md`, `context/log.md`, `context/bug-corrections.md`, `context/map.md` (if applicable), `.env.example` (optional)
- **No application code changes.**
