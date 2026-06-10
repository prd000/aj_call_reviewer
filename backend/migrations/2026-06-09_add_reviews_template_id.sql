-- Retry feature: persist the template a review was processed with, so a FAILED
-- review (whose `framework` snapshot is null until completion) can be re-enqueued
-- with its original template instead of forcing a re-upload.
-- Apply manually in Supabase SQL Editor before deploying the matching backend changes.
-- Nullable, no backfill: legacy pre-migration failed reviews have no recoverable
-- template_id and fall back to their framework snapshot (complete reviews only) or
-- must be re-uploaded.

ALTER TABLE reviews ADD COLUMN IF NOT EXISTS template_id TEXT;
