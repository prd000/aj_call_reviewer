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


def _get_provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", _DEFAULT_PROVIDER).strip().lower()


def get_llm_api_key() -> str:
    provider = _get_provider_name()
    config = PROVIDER_CONFIG.get(provider)
    if config is None:
        logger.warning("Unknown LLM_PROVIDER %r. Supported: %s", provider, ", ".join(PROVIDER_CONFIG))
        return ""
    return os.environ.get(config["api_key_env"], "").strip()


def get_llm(temperature: float, role: str | None = None) -> ChatOpenAI:
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
    logger.debug(
        "Building LLM: provider=%s model=%s base_url=%s role=%s",
        provider, model_name, config["base_url"], role,
    )
    return ChatOpenAI(**kwargs)
