-- 2026-05-29: Track the outcome of each call (Feature #4).
--
-- Adds a nullable column holding the canonical outcome label for a review
-- (e.g. "Follow-up Booked", "Closed"). NULL means "no outcome set" — the
-- legacy / in-progress state, so no backfill is needed.
--
-- Intentionally NO CHECK constraint: the allowed values are validated in the
-- FastAPI layer and single-sourced in modules/ingestion.py (CALL_OUTCOMES).
-- Keeping validation in the app means relabeling outcomes later needs no
-- second migration.

ALTER TABLE reviews
  ADD COLUMN IF NOT EXISTS call_outcome TEXT;
