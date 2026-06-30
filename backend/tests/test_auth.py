"""
Unit-level tests for auth.py: token validation, get_current_user, require_bds_rep.

All tests are synchronous (async calls wrapped in asyncio.run). No HTTP client
needed — functions are called directly with fabricated inputs.
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

from modules.auth import (
    SUPABASE_ISSUER,
    _validate_token,
    get_current_user,
    require_bds_rep,
)

# Secret matches conftest.py's SUPABASE_JWT_SECRET seed.
_SECRET = "test-secret"


def _make_token(
    secret=_SECRET,
    exp_delta=3600,
    sub="user-uuid-1",
    aud="authenticated",
    iss=None,
    **extra,
):
    now = int(time.time())
    payload = {
        "sub": sub,
        "aud": aud,
        "iss": iss if iss is not None else SUPABASE_ISSUER,
        "exp": now + exp_delta,
        "iat": now,
        **extra,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# _validate_token
# ---------------------------------------------------------------------------

def test_valid_hs256_token_returns_sub():
    token = _make_token()
    user_id = _validate_token(token)
    assert user_id == "user-uuid-1"


def test_expired_token_raises_401():
    # exp_delta must exceed leeway=30 so jwt.decode rejects it
    token = _make_token(exp_delta=-60)
    with pytest.raises(HTTPException) as exc:
        _validate_token(token)
    assert exc.value.status_code == 401


def test_garbage_token_raises_401():
    with pytest.raises(HTTPException) as exc:
        _validate_token("this.is.garbage")
    assert exc.value.status_code == 401


def test_missing_sub_claim_raises_401():
    # Craft a token without 'sub'.
    now = int(time.time())
    payload = {
        "aud": "authenticated",
        "iss": SUPABASE_ISSUER,
        "exp": now + 3600,
    }
    token = jwt.encode(payload, _SECRET, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        _validate_token(token)
    assert exc.value.status_code == 401


def test_wrong_audience_raises_401():
    token = _make_token(aud="wrong-audience")
    with pytest.raises(HTTPException) as exc:
        _validate_token(token)
    assert exc.value.status_code == 401


def test_hs256_empty_secret_characterization(monkeypatch):
    """
    Characterization test for security finding 3.2.

    An HS256 token signed with an empty secret verifies successfully when
    SUPABASE_JWT_SECRET is also empty. This test documents the gap: if it
    passes (no exception), the vulnerability is open; if it raises HTTPException
    the code has been hardened.

    ACTION IF THIS TEST FAILS: the empty-secret hole (finding 3.2) is live.
    Set SUPABASE_JWT_SECRET to a long random value in Railway and consider adding
    an explicit empty-secret guard in _validate_token.
    """
    empty_token = jwt.encode(
        {
            "sub": "attacker",
            "aud": "authenticated",
            "iss": SUPABASE_ISSUER,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        },
        "",
        algorithm="HS256",
    )
    import modules.auth as auth_module
    monkeypatch.setattr(auth_module, "SUPABASE_JWT_SECRET", "")

    try:
        _validate_token(empty_token)
        pytest.fail(
            "SECURITY FINDING 3.2: HS256 token signed with empty secret was accepted. "
            "Set SUPABASE_JWT_SECRET to a non-empty value and/or add an explicit "
            "empty-secret rejection in _validate_token."
        )
    except HTTPException:
        pass  # Code correctly rejects empty-secret HS256 tokens


# ---------------------------------------------------------------------------
# get_current_user (async, called via asyncio.run)
# ---------------------------------------------------------------------------

def test_get_current_user_no_header_raises_401():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(authorization=None, x_api_key=None))
    assert exc.value.status_code == 401


def test_get_current_user_invalid_scheme_raises_401():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(authorization="Basic abc123", x_api_key=None))
    assert exc.value.status_code == 401


def test_get_current_user_valid_token_returns_user():
    token = _make_token(sub="user-abc")
    fake_profile = {"role": "bds_rep", "is_active": True, "firm_id": None, "name": "Test Rep"}
    with patch("modules.auth.get_profile", AsyncMock(return_value=fake_profile)):
        user = asyncio.run(get_current_user(authorization=f"Bearer {token}", x_api_key=None))
    assert user["user_id"] == "user-abc"
    assert user["role"] == "bds_rep"
    assert user["name"] == "Test Rep"


def test_get_current_user_missing_profile_raises_401():
    token = _make_token()
    with patch("modules.auth.get_profile", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user(authorization=f"Bearer {token}", x_api_key=None))
    assert exc.value.status_code == 401


def test_get_current_user_deactivated_profile_raises_403():
    token = _make_token()
    fake_profile = {"role": "financial_advisor", "is_active": False, "firm_id": "f1", "name": "Banned"}
    with patch("modules.auth.get_profile", AsyncMock(return_value=fake_profile)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user(authorization=f"Bearer {token}", x_api_key=None))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# require_bds_rep
# ---------------------------------------------------------------------------

def test_require_bds_rep_allows_bds_rep():
    bds_user = {"user_id": "u1", "role": "bds_rep", "firm_id": None, "name": "Rep"}
    result = require_bds_rep(user=bds_user)
    assert result is bds_user


def test_require_bds_rep_rejects_financial_advisor():
    fa_user = {"user_id": "u2", "role": "financial_advisor", "firm_id": "f1", "name": "FA"}
    with pytest.raises(HTTPException) as exc:
        require_bds_rep(user=fa_user)
    assert exc.value.status_code == 403
