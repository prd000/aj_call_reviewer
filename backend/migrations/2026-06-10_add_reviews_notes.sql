-- Major feature #2: BDS-only free-text notes on a review (internal; never in PDF).
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS notes TEXT;
