"""
Unit tests for the MCP OAuth provider (modules/oauth_provider.py).

Uses an in-memory fake Supabase client (supporting the eq-filtered
select/insert/upsert/update/delete chain the provider issues) so the whole
authorize → code → token → verify flow runs without a database. The live
claude.ai/Cowork handshake still needs verifying on a real deploy.
"""
import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import modules.oauth_provider as op
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull


# ── in-memory fake Supabase ─────────────────────────────────────────────────────


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    _PKS = ("client_id", "token", "request_id", "code")

    def __init__(self, store, table):
        self.store, self.table = store, table
        self._filters, self._op, self._payload = [], None, None

    def select(self, *a, **k):
        self._op = "select"; return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload; return self

    def upsert(self, payload):
        self._op, self._payload = "upsert", payload; return self

    def update(self, payload):
        self._op, self._payload = "update", payload; return self

    def delete(self):
        self._op = "delete"; return self

    def eq(self, col, val):
        self._filters.append((col, val)); return self

    def _match(self, row):
        return all(row.get(c) == v for c, v in self._filters)

    async def execute(self):
        rows = self.store.setdefault(self.table, [])
        if self._op == "select":
            return _Result([dict(r) for r in rows if self._match(r)])
        if self._op == "insert":
            items = self._payload if isinstance(self._payload, list) else [self._payload]
            rows.extend(dict(i) for i in items)
            return _Result([dict(i) for i in items])
        if self._op == "upsert":
            item = self._payload
            pk = next((k for k in self._PKS if k in item), None)
            if pk:
                self.store[self.table] = [r for r in rows if r.get(pk) != item[pk]]
            self.store[self.table].append(dict(item))
            return _Result([dict(item)])
        if self._op == "update":
            matched = [r for r in rows if self._match(r)]
            for r in matched:
                r.update(self._payload)
            return _Result([dict(r) for r in matched])
        if self._op == "delete":
            keep = [r for r in rows if not self._match(r)]
            self.store[self.table] = keep
            return _Result([])
        raise AssertionError("unknown op")


class _FakeSupabase:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Query(self.store, name)


def _provider():
    fake = _FakeSupabase()
    prov = op.SupabaseOAuthProvider()
    return prov, fake, patch("modules.oauth_provider.get_client", AsyncMock(return_value=fake))


def _client():
    return OAuthClientInformationFull(
        client_id="client-1",
        redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
    )


def _iso_in(seconds):
    return datetime.fromtimestamp(time.time() + seconds, tz=timezone.utc).isoformat()


# ── clients ──────────────────────────────────────────────────────────────────


def test_register_and_get_client():
    prov, fake, ctx = _provider()
    with ctx:
        asyncio.run(prov.register_client(_client()))
        got = asyncio.run(prov.get_client("client-1"))
        assert got is not None and got.client_id == "client-1"
        assert asyncio.run(prov.get_client("missing")) is None


# ── authorize → consent → code ───────────────────────────────────────────────


def test_authorize_stores_pending_and_returns_consent_url():
    prov, fake, ctx = _provider()
    params = AuthorizationParams(
        state="st8", scopes=[op.MCP_SCOPE], code_challenge="chal",
        redirect_uri="https://claude.ai/cb", redirect_uri_provided_explicitly=True, resource=None,
    )
    with ctx:
        url = asyncio.run(prov.authorize(_client(), params))
    assert "/mcp-oauth/consent?request_id=" in url
    assert len(fake.store["oauth_pending"]) == 1


def test_full_code_exchange_flow():
    prov, fake, ctx = _provider()
    params = AuthorizationParams(
        state="st8", scopes=[op.MCP_SCOPE], code_challenge="chal",
        redirect_uri="https://claude.ai/cb", redirect_uri_provided_explicitly=True, resource=None,
    )
    with ctx:
        url = asyncio.run(prov.authorize(_client(), params))
        request_id = url.split("request_id=")[1]
        redirect = asyncio.run(prov.complete_authorization(request_id, "user-42"))
        assert "code=" in redirect and "state=st8" in redirect
        code = redirect.split("code=")[1].split("&")[0]
        # pending consumed
        assert fake.store["oauth_pending"] == []
        loaded = asyncio.run(prov.load_authorization_code(_client(), code))
        assert loaded is not None and loaded.client_id == "client-1"
        token = asyncio.run(prov.exchange_authorization_code(_client(), loaded))
        assert token.access_token and token.refresh_token
        # code is single-use
        assert asyncio.run(prov.load_authorization_code(_client(), code)) is None
        # issued access token verifies and maps to the user
        acc = asyncio.run(prov.load_access_token(token.access_token))
        assert acc is not None and op.MCP_SCOPE in acc.scopes
        assert asyncio.run(prov.resolve_token_user_id(token.access_token)) == "user-42"


def test_complete_authorization_unknown_request_raises():
    prov, fake, ctx = _provider()
    with ctx:
        with pytest.raises(ValueError, match="expired"):
            asyncio.run(prov.complete_authorization("nope", "user-1"))


# ── access-token verification ────────────────────────────────────────────────


def test_load_access_token_accepts_api_key():
    prov, fake, ctx = _provider()
    with ctx, patch("modules.oauth_provider.resolve_api_key",
                    AsyncMock(return_value={"user_id": "u9", "key_id": "k9"})):
        acc = asyncio.run(prov.load_access_token("ak_live_xyz"))
        assert acc is not None and acc.client_id == "api-key"
        assert asyncio.run(prov.resolve_token_user_id("ak_live_xyz")) == "u9"


def test_load_access_token_rejects_unknown_api_key():
    prov, fake, ctx = _provider()
    with ctx, patch("modules.oauth_provider.resolve_api_key", AsyncMock(return_value=None)):
        assert asyncio.run(prov.load_access_token("ak_live_bad")) is None


def test_load_access_token_rejects_unknown_revoked_expired():
    prov, fake, ctx = _provider()
    fake.store["oauth_tokens"] = [
        {"token": "cr_at_revoked", "kind": "access", "client_id": "c", "user_id": "u",
         "scopes": [op.MCP_SCOPE], "expires_at": _iso_in(3600), "revoked_at": _iso_in(-1)},
        {"token": "cr_at_expired", "kind": "access", "client_id": "c", "user_id": "u",
         "scopes": [op.MCP_SCOPE], "expires_at": _iso_in(-10), "revoked_at": None},
        {"token": "cr_at_ok", "kind": "access", "client_id": "c", "user_id": "u7",
         "scopes": [op.MCP_SCOPE], "expires_at": _iso_in(3600), "revoked_at": None},
    ]
    with ctx:
        assert asyncio.run(prov.load_access_token("cr_at_unknown")) is None
        assert asyncio.run(prov.load_access_token("cr_at_revoked")) is None
        assert asyncio.run(prov.load_access_token("cr_at_expired")) is None
        ok = asyncio.run(prov.load_access_token("cr_at_ok"))
        assert ok is not None and ok.client_id == "c"


def test_refresh_rotation_revokes_old():
    prov, fake, ctx = _provider()
    fake.store["oauth_tokens"] = [
        {"token": "cr_rt_old", "kind": "refresh", "client_id": "client-1", "user_id": "u5",
         "scopes": [op.MCP_SCOPE], "expires_at": _iso_in(99999), "revoked_at": None},
    ]
    with ctx:
        rt = asyncio.run(prov.load_refresh_token(_client(), "cr_rt_old"))
        assert rt is not None
        new = asyncio.run(prov.exchange_refresh_token(_client(), rt, [op.MCP_SCOPE]))
        assert new.access_token and new.refresh_token != "cr_rt_old"
        # old refresh token now revoked → no longer loadable
        assert asyncio.run(prov.load_refresh_token(_client(), "cr_rt_old")) is None
