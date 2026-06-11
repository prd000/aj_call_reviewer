-- Major feature #1: BDS-only tagging of reviews.
-- A global tags vocabulary (reusable across calls) + a denormalized tag_ids array
-- on each review for cheap History filtering. Apply in Supabase SQL Editor before deploy.
CREATE TABLE IF NOT EXISTS tags (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Case-insensitive uniqueness so "Follow-up" and "follow-up" don't both get created.
CREATE UNIQUE INDEX IF NOT EXISTS tags_name_lower_key ON tags (lower(name));
ALTER TABLE tags ENABLE ROW LEVEL SECURITY;  -- deny-all, matches SEC-001 lockdown posture

ALTER TABLE reviews ADD COLUMN IF NOT EXISTS tag_ids JSONB NOT NULL DEFAULT '[]';
