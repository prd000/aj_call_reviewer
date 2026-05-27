-- 2026-05-26: Force password set for new invitees regardless of role.
--
-- Adds a flag we flip to TRUE only after the user successfully sets their own
-- password on /set-password. Existing users are backfilled to TRUE so they
-- aren't interrupted on next login.

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS has_set_password BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE profiles
SET has_set_password = TRUE
WHERE has_set_password = FALSE;
