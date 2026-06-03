# Bug #2 — LLM Provider Abstraction Layer

## Context
Bug #2 requests that all LLM calls become modular: setting `LLM_PROVIDER` and `LLM_MODEL` in `.env` should change which provider and model the entire project uses — no code edits required. 

Currently, `LLM_PROVIDER` is declared in `.env.example` but never read. Both `identify_speakers()` and `review_call()` in `reviewer.py` hardcode DeepSeek's `base_url` and `DEEPSEEK_API_KEY`, violating the PRD's explicit rule: "No provider is hardcoded into application logic." The fix is a thin config module that the two call sites import.

---

## Approach

### 1. Create `backend/modules/llm_config.py` (new file)

```python
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


def get_llm(temperature: float) -> ChatOpenAI:
    provider = _get_provider_name()
    config = PROVIDER_CONFIG.get(provider)
    if config is None:
        raise KeyError(f"Unknown LLM_PROVIDER {provider!r}. Supported: {', '.join(PROVIDER_CONFIG)}")
    model_name = os.environ.get("LLM_MODEL", config["default_model"]).strip()
    api_key = os.environ.get(config["api_key_env"], "").strip()
    kwargs = {"model": model_name, "api_key": api_key, "temperature": temperature}
    if config["base_url"] is not None:
        kwargs["base_url"] = config["base_url"]
    logger.debug("Building LLM: provider=%s model=%s base_url=%s", provider, model_name, config["base_url"])
    return ChatOpenAI(**kwargs)
```

**How the API key routing works:**
- `PROVIDER_CONFIG` maps each provider name to the *name* of its env var (`api_key_env`)
- `get_llm()` reads `LLM_PROVIDER`, looks up `api_key_env` for that provider, then calls `os.environ.get(api_key_env)` to retrieve the actual key
- Switching `LLM_PROVIDER=openai` causes the code to read `OPENAI_API_KEY` instead of `DEEPSEEK_API_KEY` — no logic change, just a different dict lookup
- Both keys can coexist in `.env`; only the active provider's key is used

Other design notes:
- `base_url=None` for OpenAI means no `base_url` kwarg is passed; `ChatOpenAI` hits `api.openai.com` natively
- Unknown provider → `get_llm_api_key()` returns `""` (safe stub fallback); `get_llm()` raises `KeyError` (caught by `reviewer.py`'s broad `except`)
- Default provider remains `deepseek`, so existing deployments without `LLM_PROVIDER` set are unaffected

### 2. Update `backend/modules/reviewer.py`

Two changes per function (`identify_speakers` and `review_call`):

**Guard block** — replace:
```python
api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not api_key:
    logger.warning("DEEPSEEK_API_KEY not set; ...")
```
with:
```python
api_key = llm_config.get_llm_api_key()
if not api_key:
    logger.warning("LLM API key not set; ...")
```

**LLM instantiation** — replace the lazy imports + hardcoded `ChatOpenAI(...)` block with:
```python
llm = llm_config.get_llm(temperature=0.0)   # identify_speakers
llm = llm_config.get_llm(temperature=0.3)   # review_call
```

Move `import json as _json` and `from langchain_core.messages import ...` to module top level. Add `from modules import llm_config` at top.

Update docstrings to say "LLM API key" instead of "DEEPSEEK_API_KEY".

### 3. Update `.env.example`

Group and document the LLM section:
```
# ── LLM Provider ──────────────────────────────────────────────────────────────
# Set LLM_PROVIDER to one of: deepseek, openai
# LLM_MODEL overrides the provider's default model (optional)
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat

# API keys — only the key for the active provider is required
DEEPSEEK_API_KEY=
OPENAI_API_KEY=

# ── Transcription ─────────────────────────────────────────────────────────────
REV_AI_ACCESS_TOKEN=

# ── Storage ───────────────────────────────────────────────────────────────────
SUPABASE_URL=
SUPABASE_KEY=
```

### 4. Update context docs

- `context/map.md` — add `llm_config.py` entry under `backend/modules/`; update `reviewer.py` description
- `context/decisions.md` — append entry dated 2026-05-21 documenting the abstraction
- `context/log.md` — prepend new entry for this change
- `context/deferredwork.md` — update the `OPENAI_API_KEY` entry to reference `LLM_PROVIDER` instead

---

## File Sequence

1. `backend/modules/llm_config.py` — create first (reviewer imports it)
2. `backend/modules/reviewer.py` — update imports and both functions
3. `.env.example` — documentation update
4. `context/map.md`, `context/decisions.md`, `context/log.md`, `context/deferredwork.md` — docs, any order

No `requirements.txt` changes — `langchain-openai` is already installed.

---

## Verification

1. Start backend (`py -m uvicorn main:app --reload` from `backend/`)
2. With `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY` set — upload and process a call; confirm review generates normally
3. Change to `LLM_PROVIDER=openai` + `OPENAI_API_KEY` set — confirm it picks up the right key and hits OpenAI
4. Set `LLM_PROVIDER=unknown` — confirm logs show warning and stub review is returned (no crash)
5. Unset the active API key — confirm fallback to stub review with a clear log warning
