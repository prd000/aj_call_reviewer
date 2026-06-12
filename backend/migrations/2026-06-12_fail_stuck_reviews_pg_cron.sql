-- DB-level backstop: fail reviews stuck in in-progress statuses.
-- Runs every 2 minutes via pg_cron so the watchdog survives worker restarts,
-- deploys, and any scenario where the app-layer reaper is not running.
--
-- Thresholds are deliberately LOOSER than the app-layer reaper so the app
-- layer (richer error messages, guard_terminal race protection) wins when alive:
--   pending:      15 min  (app reaper: 5 min)
--   reviewing:    30 min  (app reaper: 12 min)
--   transcribing: 60 min  (app reaper: 35 min)
--
-- Requires the existing reviews.updated_at trigger (2026-06-09_add_reviews_updated_at.sql).
-- pg_cron is available on Supabase — enable the extension under Database → Extensions
-- if the CREATE EXTENSION line fails.

create extension if not exists pg_cron;

create or replace function fail_stuck_reviews() returns void
language plpgsql
security definer
as $$
begin
  update reviews
    set status        = 'failed',
        error_message = 'Auto-failed by DB watchdog: no progress for >15 min (was ''pending'')'
  where status = 'pending'
    and updated_at < now() - interval '15 minutes';

  update reviews
    set status        = 'failed',
        error_message = 'Auto-failed by DB watchdog: no progress for >30 min (was ''reviewing'')'
  where status = 'reviewing'
    and updated_at < now() - interval '30 minutes';

  update reviews
    set status        = 'failed',
        error_message = 'Auto-failed by DB watchdog: no progress for >60 min (was ''transcribing'')'
  where status = 'transcribing'
    and updated_at < now() - interval '60 minutes';
end;
$$;

select cron.schedule('fail-stuck-reviews', '*/2 * * * *', 'select fail_stuck_reviews()');
