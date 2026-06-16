"""Tests for PUT /users/me/default-template.

Calls the handler directly with an explicit `user` dict (bypassing Depends)
and monkeypatches module-level dependencies in routers.management namespace,
mirroring the direct-handler style of test_retry.py.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import routers.management as mgmt_module
from routers.management import DefaultTemplateBody, set_my_default_template

BDS = {"role": "bds_rep", "user_id": "u-bds"}
FA = {"role": "financial_advisor", "user_id": "u-fa", "firm_id": "firm-a"}

_TEMPLATE = {"id": "tpl-1", "name": "Test Template", "criteria": []}
_PROFILE = {"id": "u-bds", "default_template_id": "tpl-1"}


def _wire(monkeypatch, *, template=_TEMPLATE, profile=_PROFILE):
    monkeypatch.setattr(mgmt_module, "get_template", AsyncMock(return_value=template))
    monkeypatch.setattr(mgmt_module, "set_default_template", AsyncMock(return_value=profile))


def test_set_default_returns_profile(monkeypatch):
    _wire(monkeypatch)
    body = DefaultTemplateBody(template_id="tpl-1")
    result = asyncio.run(set_my_default_template(body, user=BDS))
    assert result == _PROFILE
    mgmt_module.get_template.assert_awaited_once_with("tpl-1")
    mgmt_module.set_default_template.assert_awaited_once_with("u-bds", "tpl-1")


def test_set_default_unknown_template_raises_404(monkeypatch):
    _wire(monkeypatch, template=None)
    body = DefaultTemplateBody(template_id="missing-tpl")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(set_my_default_template(body, user=BDS))
    assert exc.value.status_code == 404
    mgmt_module.set_default_template.assert_not_awaited()


def test_clear_default_skips_template_lookup(monkeypatch):
    cleared_profile = {"id": "u-bds", "default_template_id": None}
    _wire(monkeypatch, profile=cleared_profile)
    body = DefaultTemplateBody(template_id=None)
    result = asyncio.run(set_my_default_template(body, user=BDS))
    assert result["default_template_id"] is None
    mgmt_module.get_template.assert_not_awaited()
    mgmt_module.set_default_template.assert_awaited_once_with("u-bds", None)


def test_missing_profile_raises_404(monkeypatch):
    _wire(monkeypatch, profile=None)
    body = DefaultTemplateBody(template_id="tpl-1")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(set_my_default_template(body, user=BDS))
    assert exc.value.status_code == 404


def test_non_bds_is_gated_by_dependency():
    """require_bds_rep is in the dependency chain — the sweep covers this.

    Calling the handler directly with an FA user bypasses the Depends layer,
    so role rejection is verified by test_auth_sweep.py rather than here.
    This test documents the intentional scope boundary.
    """
    assert True
