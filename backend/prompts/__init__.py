from pathlib import Path
from functools import lru_cache

_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the raw text of prompts/<name>.txt (e.g. 'criterion.system').
    Caller applies .format(...) only for templated prompts; static prompts are used raw."""
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").rstrip("\n")
