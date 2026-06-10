"""Tests for LLM timeout + retry config (Bug #3 fix — Part A)."""
import os
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helper: build a ChatOpenAI via get_llm() with a dummy key so the lazy
# constructor doesn't reach the network.
# ---------------------------------------------------------------------------

def _make_llm(env_overrides=None):
    """Return a ChatOpenAI built by get_llm() under the given env overrides."""
    base_env = {
        "LLM_PROVIDER": "deepseek",
        "DEEPSEEK_API_KEY": "dummy-key",
    }
    if env_overrides:
        base_env.update(env_overrides)
    with patch.dict(os.environ, base_env, clear=False):
        # Re-import helpers each time so env is read fresh.
        import importlib
        import modules.llm_config as llm_config
        importlib.reload(llm_config)
        return llm_config.get_llm(temperature=0.0)


# ---------------------------------------------------------------------------
# (a) Defaults: timeout == 120.0, max_retries == 1
# ---------------------------------------------------------------------------

def test_llm_default_timeout_and_retries():
    with patch.dict(os.environ, {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "k"}, clear=False):
        # Remove overrides if set
        for var in ("LLM_REQUEST_TIMEOUT", "LLM_MAX_RETRIES"):
            os.environ.pop(var, None)

        import importlib
        import modules.llm_config as llm_config
        importlib.reload(llm_config)

        llm = llm_config.get_llm(temperature=0.0)
        assert llm.request_timeout == 120.0
        assert llm.max_retries == 1


# ---------------------------------------------------------------------------
# (b) Env overrides are honored
# ---------------------------------------------------------------------------

def test_llm_env_override_timeout():
    env = {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "k", "LLM_REQUEST_TIMEOUT": "45"}
    with patch.dict(os.environ, env, clear=False):
        import importlib
        import modules.llm_config as llm_config
        importlib.reload(llm_config)
        llm = llm_config.get_llm(temperature=0.0)
        assert llm.request_timeout == 45.0


def test_llm_env_override_max_retries():
    env = {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "k", "LLM_MAX_RETRIES": "0"}
    with patch.dict(os.environ, env, clear=False):
        import importlib
        import modules.llm_config as llm_config
        importlib.reload(llm_config)
        llm = llm_config.get_llm(temperature=0.0)
        assert llm.max_retries == 0


# ---------------------------------------------------------------------------
# (c) Invalid / "0" / empty values → safe default (never 0 / no-timeout)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_val", ["0", "-5", "not_a_number", ""])
def test_llm_invalid_timeout_falls_back_to_default(bad_val):
    env = {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "k", "LLM_REQUEST_TIMEOUT": bad_val}
    with patch.dict(os.environ, env, clear=False):
        import importlib
        import modules.llm_config as llm_config
        importlib.reload(llm_config)
        timeout = llm_config._get_request_timeout()
        assert timeout == llm_config._DEFAULT_LLM_REQUEST_TIMEOUT
        assert timeout > 0, "A zero/negative timeout would disable the timeout entirely"


@pytest.mark.parametrize("bad_val", ["not_a_number", "-1"])
def test_llm_invalid_max_retries_falls_back(bad_val):
    env = {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "k", "LLM_MAX_RETRIES": bad_val}
    with patch.dict(os.environ, env, clear=False):
        import importlib
        import modules.llm_config as llm_config
        importlib.reload(llm_config)
        val = llm_config._get_max_retries()
        # invalid string → default; negative → clamped to 0
        assert val >= 0
