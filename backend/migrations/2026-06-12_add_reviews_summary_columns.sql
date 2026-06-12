-- Denormalized summary columns for fast list queries without jsonb traversal.
-- overall_score / overall_max_score replace the categories jsonb scan; template_name
-- replaces the framework jsonb projection. Backfill via:
--   cd backend && py -m scripts.backfill_summary_columns
-- Apply in Supabase SQL Editor before deploying the matching backend changes.

ALTER TABLE reviews
  ADD COLUMN IF NOT EXISTS overall_score FLOAT,
  ADD COLUMN IF NOT EXISTS overall_max_score FLOAT,
  ADD COLUMN IF NOT EXISTS template_name TEXT;

-- Composite index for keyset pagination on (created_at DESC, id DESC).
CREATE INDEX IF NOT EXISTS reviews_created_at_id_desc
  ON reviews (created_at DESC, id DESC);
