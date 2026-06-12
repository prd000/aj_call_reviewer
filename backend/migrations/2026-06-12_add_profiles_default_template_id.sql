-- 2026-06-12: Per-BDS-rep default review template
-- Adds nullable default_template_id to profiles.
-- No FK constraint — dangling refs (deleted template) resolve gracefully on the client
-- (falls back to most-recent template), mirroring the reviews.template_id pattern.
-- Apply manually in Supabase SQL Editor before deploying.

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS default_template_id TEXT;
