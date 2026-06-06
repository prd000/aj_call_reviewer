-- 2026-06-05: Lock down Supabase tables — RLS deny-all + revoke public grants (SEC-001).
--
-- WHY: The browser ships the public Supabase anon key (VITE_SUPABASE_ANON_KEY) in
-- the React bundle. With RLS disabled and Supabase's default anon/authenticated
-- grants intact, anyone who loads the site can read/write every firm's reviews,
-- profiles, firms, and templates directly via PostgREST
-- (https://<proj>.supabase.co/rest/v1/<table>) — bypassing all FastAPI authz
-- (_fa_can_access, require_bds_rep, firm scoping). This is SEC-001 (Critical) in
-- context/security-review.md.
--
-- SAFE TO APPLY WITH ZERO APP BREAKAGE: the frontend uses Supabase ONLY for
-- supabase.auth.* (login/refresh/password-reset, which run on the `auth` schema
-- via GoTrue and are unaffected by `public`-schema grants). There are zero
-- .from()/.rpc()/.storage calls in frontend/src — all data + recordings flow
-- through FastAPI, which connects with the service_role key and BYPASSES RLS.
-- So enabling RLS in deny-all (no-policy) mode locks out the anon key while the
-- backend keeps working untouched. RLS becomes defense-in-depth behind FastAPI.
--
-- NOTE: This is applied MANUALLY in the Supabase dashboard → SQL Editor (once per
-- environment). It is committed here for version control / auditability only; the
-- backend does not run migrations automatically.
--
-- CAVEAT: Revoke ONLY from anon/authenticated. Do NOT revoke from service_role or
-- postgres — the backend connects as service_role and relies on its grants +
-- BYPASSRLS.

-- ── A1. Tables: revoke grants + enable RLS (blanket, schema-wide) ───────────────

-- Revoke all access from the public-facing Postgres roles on existing objects.
-- ENABLE RLS alone already denies all rows when no policy exists; the REVOKE makes
-- PostgREST return a clean permission error instead of an empty array. Belt + braces.
REVOKE ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;

-- Enable RLS on every app table. With NO policies, all rows are denied to any role
-- that does not bypass RLS. service_role bypasses RLS, so the backend is unaffected.
ALTER TABLE public.profiles  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.firms     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reviews   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.templates ENABLE ROW LEVEL SECURITY;

-- Future tables: default to locked-down so a newly created table is never exposed.
-- Default privileges apply to objects created by the named role. The Supabase SQL
-- Editor and the dashboard Table Editor both run as `postgres`, so FOR ROLE postgres
-- covers tables you create there.
-- NOTE: we intentionally do NOT include `supabase_admin` here — `postgres` is not a
-- member of it, so `ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin` raises
-- "permission denied to change default privileges" and rolls back the whole script.
-- NOTE: ALTER DEFAULT PRIVILEGES only covers GRANTS on future tables — it does NOT
-- auto-enable RLS. Any NEW public table must still get its own `ENABLE ROW LEVEL
-- SECURITY` (see the standing rule in context/decisions.md, 2026-06-05).
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON TABLES    FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

-- ── A2. Storage: verify the `recordings` bucket is private (READ-ONLY checks) ───
-- Run these and confirm the results; they make no changes.
--
--   -- Expect: recordings -> public = false
--   SELECT id, name, public FROM storage.buckets;
--
--   -- Expect: NO rows that grant anon/authenticated access to the recordings bucket.
--   -- (pg_policies is the VIEW — its column is `policyname`, not the catalog's `polname`.)
--   SELECT policyname, cmd, roles, qual FROM pg_policies WHERE schemaname = 'storage';
--
-- If the bucket shows public = true, set it to Private in dashboard → Storage →
-- bucket settings. If any permissive storage.objects policy targets anon/
-- authenticated for `recordings`, drop it. A private bucket with no such policy is
-- already correct — backend signed URLs (modules/storage.py) keep working because
-- they're generated with service_role.

-- ── Verification (negative test) ───────────────────────────────────────────────
-- With the public anon key, each of these must return a permission error / 401 / [],
-- NOT data:
--   curl 'https://<proj>.supabase.co/rest/v1/reviews?select=*' \
--     -H "apikey: <ANON_KEY>" -H "Authorization: Bearer <ANON_KEY>"
--   (repeat for profiles, firms, templates; confirm a PATCH write is rejected too.)
