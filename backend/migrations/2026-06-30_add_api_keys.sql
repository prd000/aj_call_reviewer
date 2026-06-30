-- API keys: programmatic credentials so non-browser clients (a Claude Skill / MCP
-- server) can call the API without a Supabase login. A key links to a profile and
-- inherits that profile's role at verification time. Only the sha256 hash of the
-- secret is stored; the raw key is shown to the user exactly once at creation.
-- Apply in the Supabase SQL Editor before deploying the API-key feature.
CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,        -- FK-by-convention to profiles.id (no hard FK, matches existing style)
    label        TEXT NOT NULL,
    key_prefix   TEXT NOT NULL,        -- leading chars of the full key, for display only
    key_hash     TEXT NOT NULL,        -- sha256 hex of the full secret; NEVER the raw key
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ           -- NULL = active
);
-- Lookups resolve a presented key by the hash of its secret.
CREATE UNIQUE INDEX IF NOT EXISTS api_keys_key_hash_uniq ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS api_keys_user_id_idx ON api_keys (user_id);
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;  -- deny-all, matches SEC-001 lockdown posture
