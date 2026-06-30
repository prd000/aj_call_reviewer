"""
Unit-level tests for the API-key auth path.

Covers api_keys.py (hash/generate/resolve) and the dual-path get_current_user:
an API key must produce the SAME {user_id, role, firm_id, name} context as a JWT,
so role gating (require_bds_rep) and FA-visibility keep working unchanged.

Synchronous style matches test_auth.py (async calls wrapped in asyncio.run); the
Supabase client is faked so no network/DB is touched.
"""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.api_keys import (
    KEY_TAG,
    generate_api_key,
    hash_key,
    resolve_api_key,
)
from modules.auth import SUPABASE_ISSUER, get_current_user, require_bds_rep

_SECRET = "test-secret"  # matches conftest.py's SUPABASE_JWT_SECRET seed


def _make_jwt(sub="user-uuid-1", aud="authenticated"):
    now = int(time.time())
    payload = {"sub": sub, "aud": aud, "iss": SUPABASE_ISSUER, "exp": now + 3600, "iat": now}
    return jwt.encode(payload, _SECRET, algorithm="HS256")


# ── Fake Supabase client (chainable, async execute) ────────────────────────────


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    async def execute(self):
        return _FakeResult(self._data)


class _FakeClient:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return _FakeQuery(self._data)


def _patch_client(data):
    return patch("modules.api_keys.get_client", AsyncMock(return_value=_FakeClient(data)))


# ── hash_key / generate_api_key ────────────────────────────────────────────────


def test_hash_key_is_deterministic():
    assert hash_key("ak_live_abc") == hash_key("ak_live_abc")
    assert hash_key("ak_live_abc") != hash_key("ak_live_xyz")


def test_generate_api_key_shape():
    full_key, prefix, key_hash = generate_api_key()
    assert full_key.startswith(KEY_TAG)
    assert full_key.startswith(prefix)
    assert key_hash == hash_key(full_key)
    # Two generations never collide.
    assert generate_api_key()[0] != generate_api_key()[0]


# ── resolve_api_key ────────────────────────────────────────────────────────────


def test_resolve_untagged_key_returns_none_without_db():
    # A value lacking the tag is rejected before any DB call.
    assert asyncio.run(resolve_api_key("not-a-key")) is None
    assert asyncio.run(resolve_api_key("")) is None


def test_resolve_unknown_key_returns_none():
    with _patch_client([]):
        assert asyncio.run(resolve_api_key(KEY_TAG + "deadbeef")) is None


def test_resolve_active_key_returns_ids():
    with _patch_client([{"id": "key-1", "user_id": "user-1"}]):
        resolved = asyncio.run(resolve_api_key(KEY_TAG + "goodtoken"))
    assert resolved == {"user_id": "user-1", "key_id": "key-1"}


# ── get_current_user via API key (X-API-Key header) ────────────────────────────


def test_api_key_header_returns_jwt_identical_context():
    fake_profile = {"role": "bds_rep", "is_active": True, "firm_id": None, "name": "Key Rep"}
    with patch("modules.auth.resolve_api_key", AsyncMock(return_value={"user_id": "u-key1", "key_id": "k1"})), \
         patch("modules.auth.touch_last_used", AsyncMock()), \
         patch("modules.auth.get_profile", AsyncMock(return_value=fake_profile)):
        user = asyncio.run(get_current_user(authorization=None, x_api_key=KEY_TAG + "tok"))
    assert user == {"user_id": "u-key1", "role": "bds_rep", "firm_id": None, "name": "Key Rep"}


def test_api_key_via_bearer_authorization():
    fake_profile = {"role": "financial_advisor", "is_active": True, "firm_id": "f1", "name": "FA Key"}
    with patch("modules.auth.resolve_api_key", AsyncMock(return_value={"user_id": "u-key2", "key_id": "k2"})), \
         patch("modules.auth.touch_last_used", AsyncMock()), \
         patch("modules.auth.get_profile", AsyncMock(return_value=fake_profile)):
        user = asyncio.run(get_current_user(authorization=f"Bearer {KEY_TAG}tok", x_api_key=None))
    assert user["user_id"] == "u-key2"
    assert user["role"] == "financial_advisor"
    assert user["firm_id"] == "f1"


def test_invalid_api_key_raises_401():
    with patch("modules.auth.resolve_api_key", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user(authorization=None, x_api_key=KEY_TAG + "bad"))
    assert exc.value.status_code == 401


def test_deactivated_profile_via_api_key_raises_403():
    fake_profile = {"role": "bds_rep", "is_active": False, "firm_id": None, "name": "Banned"}
    with patch("modules.auth.resolve_api_key", AsyncMock(return_value={"user_id": "u-key3", "key_id": "k3"})), \
         patch("modules.auth.touch_last_used", AsyncMock()), \
         patch("modules.auth.get_profile", AsyncMock(return_value=fake_profile)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user(authorization=None, x_api_key=KEY_TAG + "tok"))
    assert exc.value.status_code == 403


# ── role inheritance (require_bds_rep over an API-key context) ──────────────────


def test_bds_rep_api_key_passes_require_bds_rep():
    fake_profile = {"role": "bds_rep", "is_active": True, "firm_id": None, "name": "Rep"}
    with patch("modules.auth.resolve_api_key", AsyncMock(return_value={"user_id": "u-key4", "key_id": "k4"})), \
         patch("modules.auth.touch_last_used", AsyncMock()), \
         patch("modules.auth.get_profile", AsyncMock(return_value=fake_profile)):
        user = asyncio.run(get_current_user(authorization=None, x_api_key=KEY_TAG + "tok"))
    assert require_bds_rep(user=user) is user


def test_fa_api_key_rejected_by_require_bds_rep():
    fake_profile = {"role": "financial_advisor", "is_active": True, "firm_id": "f1", "name": "FA"}
    with patch("modules.auth.resolve_api_key", AsyncMock(return_value={"user_id": "u-key5", "key_id": "k5"})), \
         patch("modules.auth.touch_last_used", AsyncMock()), \
         patch("modules.auth.get_profile", AsyncMock(return_value=fake_profile)):
        user = asyncio.run(get_current_user(authorization=None, x_api_key=KEY_TAG + "tok"))
    with pytest.raises(HTTPException) as exc:
        require_bds_rep(user=user)
    assert exc.value.status_code == 403
