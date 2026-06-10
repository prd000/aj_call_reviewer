-- Bug #3 fix: add updated_at heartbeat to reviews for stuck-review detection.
-- Apply manually in Supabase SQL Editor before deploying the matching backend changes.

ALTER TABLE reviews ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill existing rows before the trigger exists, so it isn't immediately overwritten.
UPDATE reviews SET updated_at = created_at WHERE updated_at IS NULL OR updated_at = now();

-- Trigger function: bumps updated_at on every row update.
CREATE OR REPLACE FUNCTION set_reviews_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- Fire before every UPDATE on reviews so every status write (transcribing →
-- checkpoint → reviewing → complete) keeps updated_at fresh.  A row that
-- makes no progress goes stale and the reaper picks it up.
DROP TRIGGER IF EXISTS reviews_set_updated_at ON reviews;
CREATE TRIGGER reviews_set_updated_at
    BEFORE UPDATE ON reviews
    FOR EACH ROW EXECUTE FUNCTION set_reviews_updated_at();
