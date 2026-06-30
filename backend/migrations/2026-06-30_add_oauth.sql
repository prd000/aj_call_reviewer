-- OAuth 2.1 authorization-server storage for the MCP connector. Lets claude.ai /
-- Cowork connect (their connector requires OAuth + dynamic client registration).
-- The flow binds an issued bearer token to a user via an API key pasted on the
-- consent page. Persisted (not in-memory) so tokens survive Railway redeploys.
-- Apply in the Supabase SQL Editor before deploying the OAuth feature.

-- Dynamically-registered OAuth clients (RFC 7591). `data` holds the full
-- OAuthClientInformationFull model JSON (round-tripped verbatim) so the schema
-- never drifts from the SDK's client model.
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id   TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- In-flight authorize requests, held between the /authorize redirect and the
-- consent-page submit (keyed by a random request_id placed in the consent URL).
CREATE TABLE IF NOT EXISTS oauth_pending (
    request_id  TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL,
    params      JSONB NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);

-- One-time authorization codes (consumed at /token).
CREATE TABLE IF NOT EXISTS oauth_codes (
    code                            TEXT PRIMARY KEY,
    client_id                       TEXT NOT NULL,
    user_id                         TEXT NOT NULL,
    scopes                          JSONB NOT NULL DEFAULT '[]',
    code_challenge                  TEXT,
    redirect_uri                    TEXT NOT NULL,
    redirect_uri_provided_explicitly BOOLEAN NOT NULL DEFAULT TRUE,
    resource                        TEXT,
    expires_at                      TIMESTAMPTZ NOT NULL
);

-- Issued access + refresh tokens (opaque; looked up on every MCP request).
CREATE TABLE IF NOT EXISTS oauth_tokens (
    token       TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,          -- 'access' | 'refresh'
    client_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    scopes      JSONB NOT NULL DEFAULT '[]',
    expires_at  TIMESTAMPTZ,            -- NULL = no expiry
    revoked_at  TIMESTAMPTZ             -- NULL = active
);
CREATE INDEX IF NOT EXISTS oauth_tokens_user_id_idx ON oauth_tokens (user_id);

ALTER TABLE oauth_clients ENABLE ROW LEVEL SECURITY;   -- deny-all; backend uses service_role
ALTER TABLE oauth_pending ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_codes   ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens  ENABLE ROW LEVEL SECURITY;
