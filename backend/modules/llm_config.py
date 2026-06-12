import os
import logging
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

PROVIDER_CONFIG: dict[str, dict] = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
        "default_model": "gpt-4o",
    },
}

_DEFAULT_PROVIDER = "deepseek"
_DEFAULT_LLM_REQUEST_TIMEOUT = 120.0
_DEFAULT_LLM_MAX_RETRIES = 1


def _get_provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", _DEFAULT_PROVIDER).strip().lower()


def _get_request_timeout() -> float:
    raw = os.environ.get("LLM_REQUEST_TIMEOUT", "").strip()
    try:
        val = float(raw) if raw else _DEFAULT_LLM_REQUEST_TIMEOUT
    except ValueError:
        val = _DEFAULT_LLM_REQUEST_TIMEOUT
    # httpx treats 0 as no timeout — clamp to default to avoid reintroducing the bug
    return val if val > 0 else _DEFAULT_LLM_REQUEST_TIMEOUT


def _get_max_retries() -> int:
    raw = os.environ.get("LLM_MAX_RETRIES", "").strip()
    try:
        val = int(raw) if raw else _DEFAULT_LLM_MAX_RETRIES
    except ValueError:
        val = _DEFAULT_LLM_MAX_RETRIES
    return max(0, val)


def get_llm_api_key() -> str:
    provider = _get_provider_name()
    config = PROVIDER_CONFIG.get(provider)
    if config is None:
        logger.warning("Unknown LLM_PROVIDER %r. Supported: %s", provider, ", ".join(PROVIDER_CONFIG))
        return ""
    return os.environ.get(config["api_key_env"], "").strip()


def get_llm(
    temperature: float,
    role: str | None = None,
    json_mode: bool = False,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    provider = _get_provider_name()
    config = PROVIDER_CONFIG.get(provider)
    if config is None:
        raise KeyError(f"Unknown LLM_PROVIDER {provider!r}. Supported: {', '.join(PROVIDER_CONFIG)}")
    if role == "history_chat":
        # CHAT_AGENT_MODEL takes precedence for the history chat agent;
        # falls back to LLM_MODEL then the provider default.
        model_name = (
            os.environ.get("CHAT_AGENT_MODEL", "").strip()
            or os.environ.get("LLM_MODEL", "").strip()
            or config["default_model"]
        )
    else:
        model_name = os.environ.get("LLM_MODEL", config["default_model"]).strip()
    api_key = os.environ.get(config["api_key_env"], "").strip()
    kwargs: dict = {"model": model_name, "api_key": api_key, "temperature": temperature}
    if config["base_url"] is not None:
        kwargs["base_url"] = config["base_url"]
    kwargs["timeout"] = _get_request_timeout()
    kwargs["max_retries"] = _get_max_retries()
    if max_tokens is not None:
        # Explicit completion cap; prevents long free-text outputs (e.g. coaching
        # emails) from being silently truncated at the provider's default limit.
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        # Both DeepSeek and OpenAI honor this; DeepSeek additionally requires "json"
        # somewhere in the prompt (criterion.system.txt already satisfies this).
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    logger.debug(
        "Building LLM: provider=%s model=%s base_url=%s role=%s timeout=%.1fs max_retries=%d",
        provider, model_name, config["base_url"], role,
        kwargs["timeout"], kwargs["max_retries"],
    )
    return ChatOpenAI(**kwargs)
