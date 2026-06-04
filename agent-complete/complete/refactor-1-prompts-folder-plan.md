# Refactor #1 — Move all LLM prompts into a dedicated `backend/prompts/` folder

## Context

`bug-corrections.md` → Refactors #1: *"I want all prompts to be in a prompts folder. The only thing we have in there right now is outdated. ANY call to the LLM should be in a prompt folder."* The user also notes that because Railway deploys with `rootDirectory: backend`, the prompt folder must live **inside** `backend/` (a root-level `/prompts/` would not ship with the backend service).

**Problem today:** Every prompt is hardcoded as a Python string inside `backend/modules/reviewer.py`, mixing prompt content with orchestration logic. A leftover root `/prompts/` folder holds 4 `.txt` rubric files that are dead (unused since the 2026-05-14 dynamic-template change) — misleadingly suggesting prompts live there.

**Outcome:** All LLM-bound text (every system prompt and human-message template for every `llm.invoke(...)` call) lives in `backend/prompts/` as plain-text files, loaded through one small loader. `reviewer.py` keeps only orchestration + formatting logic. The dead root `/prompts/` folder is deleted.

**Confirmed decisions (from the user):**
1. **Format:** plain `.txt` files + a loader module (not Python constants).
2. **Frontend:** backend only for now — the frontend makes **zero** direct LLM calls (it only POSTs message arrays to `/reviews/{id}/chat`), so a `frontend/prompts/` folder would be empty. Defer it until the frontend ever calls an LLM directly.
3. **Old files:** delete the root `/prompts/` folder and its 4 `.txt` files.

## Scope

There are exactly **3 LLM call sites**, all in `backend/modules/reviewer.py`, covering **4 distinct prompts**:

| Call site | System prompt constant | Human-message template | `.format()`? |
|---|---|---|---|
| `identify_speakers()` | `SPEAKER_ID_PROMPT` (L9–17) | `f"Transcript sample:\n{sample_text}"` (L233) | system used **raw**; user formatted |
| `review_call()` per-criterion | `CRITERION_PROMPT_TEMPLATE` (L19–27) | `f"Transcript:\n{transcript_text}"` (L310) | both formatted |
| `review_call()` summary | inline `summary_prompt` (L331–337) | `f"Transcript:\n...\n\nCategory Scores:\n{scores_text}"` (L344) | both formatted |
| `chat_about_transcript()` | `CHAT_SYSTEM_PROMPT_TEMPLATE` (L92–112) | (real user messages — no template) | system formatted |

**Stays in `reviewer.py` (logic, not prompts):** `_format_transcript`, `_format_transcript_labeled`, `_format_framework`, `STUB_REVIEW`, `MAX_CHAT_HISTORY`, the conditional `framework_clause` text, the ```` ``` ```` fence-stripping, and all `.invoke()` orchestration.

## ⚠️ Fidelity requirement (must not change what the LLM receives)

The bytes sent to the model must be **identical** before/after. Two traps:
- `SPEAKER_ID_PROMPT` contains `{{ }}` but is sent **without** `.format()` → the model currently sees literal **double** braces. Its file must keep `{{ }}` and be used **raw**.
- `CRITERION_PROMPT_TEMPLATE` contains `{{ }}` and **is** `.format()`ed → braces collapse to single. Its file keeps `{{ }}` and is used **with** `.format()`.

Rule of thumb encoded in the plan: **the loader returns raw file text; the caller decides whether to `.format()`** — preserving each prompt's current handling exactly. A golden byte-equality test (below) guards this.

## Implementation

### 1. Create `backend/prompts/` package

```
backend/prompts/
  __init__.py            # load_prompt() loader
  speaker_id.system.txt  # raw (NOT formatted) — keep {{ }} double braces verbatim
  speaker_id.user.txt    # formatted with {sample_text}
  criterion.system.txt   # formatted — keep {{ }} for literal JSON, {description}/{success_condition}/{max_score}
  criterion.user.txt     # formatted with {transcript}
  chat.system.txt        # formatted with {framework_clause}/{framework_section}/{transcript}
  summary.system.txt     # raw (no placeholders)
  summary.user.txt       # formatted with {transcript}/{scores_text}
```

Importable as `from prompts import load_prompt` (the backend runs with `backend/` on `sys.path`, like `from modules.*` / `from routers.*`).

`__init__.py` loader (lazy, cached, fail-fast on missing file):

```python
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
```

Each `.txt` file's content is copied **verbatim** from the corresponding string in `reviewer.py` (preserving `{{ }}` exactly as listed above). `rstrip("\n")` tolerates a trailing editor newline without altering content; do not strip leading/internal whitespace.

### 2. Rewire `backend/modules/reviewer.py`

- Delete the 4 prompt constants/inline strings (L9–17, L19–27, L92–112, L331–337).
- Add `from prompts import load_prompt`.
- At each call site, source text from the loader, preserving raw-vs-format handling:

```python
# identify_speakers — system used RAW (double braces preserved), user formatted
SystemMessage(content=load_prompt("speaker_id.system")),
HumanMessage(content=load_prompt("speaker_id.user").format(sample_text=sample_text)),

# review_call criterion — both formatted
system_prompt = load_prompt("criterion.system").format(
    description=criterion["description"],
    success_condition=criterion["success_condition"],
    max_score=max_score,
)
HumanMessage(content=load_prompt("criterion.user").format(transcript=transcript_text))

# review_call summary — system raw, user formatted
SystemMessage(content=load_prompt("summary.system")),
HumanMessage(content=load_prompt("summary.user").format(transcript=transcript_text, scores_text=scores_text)),

# chat_about_transcript — system formatted (framework_clause/section/transcript unchanged)
system_prompt = load_prompt("chat.system").format(
    framework_clause=framework_clause,
    framework_section=framework_section,
    transcript=transcript_text,
)
```

Keep all helper formatters and the `framework_clause` conditional exactly as-is — they produce the values fed into `.format()`.

### 3. Delete the dead root folder

Remove `C:\Users\Admin\Documents\GitHub\call_reviewer\prompts\` and its 4 files (`needs_discovery.txt`, `rapport_building.txt`, `objection_handling.txt`, `solution_presentation.txt`). Nothing imports them.

### 4. Update context docs (required by CLAUDE.md)

- **map.md** — add the `backend/prompts/` section (loader + the 7 `.txt` files, one line each); update the `reviewer.py` entry to note prompts are now externalized and loaded via `prompts.load_prompt`; the root `/prompts/` is gone so no map entry needed for it.
- **log.md** — add a dated entry summarizing the refactor.
- **decisions.md** — add a short decision: *prompts externalized to `backend/prompts/` as plain-text files loaded via `load_prompt`; lives inside `backend/` (not repo root) for Railway `rootDirectory: backend`; loader returns raw text and callers format, preserving exact LLM-input bytes; frontend prompts folder deferred until the frontend makes a direct LLM call.*
- **deferredwork.md** — no change (no new keys/dummy data introduced).

## Verification

1. **Golden byte-equality test (the real safety net).** Before editing `reviewer.py`, capture the exact strings the four prompts currently produce; after the refactor, assert the loader + `.format()` reproduce them byte-for-byte. Concretely, add a throwaway/permanent test under `backend/` that pins:
   - `load_prompt("speaker_id.system")` == the old `SPEAKER_ID_PROMPT` (double braces intact).
   - `load_prompt("criterion.system").format(description="D", success_condition="S", max_score=10)` == the old `CRITERION_PROMPT_TEMPLATE.format(...)` with the same args.
   - `load_prompt("chat.system").format(framework_clause="", framework_section="", transcript="T")` == old `CHAT_SYSTEM_PROMPT_TEMPLATE.format(...)`.
   - `load_prompt("summary.system")` == the old inline summary string.
   - The three user templates `.format(...)` == the old `f"..."` outputs.
   Run with `py -m pytest backend/...` (per machine convention, Python tools use the `py -m` prefix).
2. **Import smoke test:** `py -c "from prompts import load_prompt; print(load_prompt('criterion.system')[:40])"` from inside `backend/` confirms the package resolves and a file loads.
3. **End-to-end (real pipeline):** start backend + worker + frontend (`start.ps1`), upload a short call as a BDS rep, and confirm: speaker identification, per-criterion scores, and overall summary all generate (review reaches `complete`), then open the result and use **Ask AI** to confirm the chat endpoint still answers grounded in the transcript. This exercises all 3 call sites against the new loader.
4. **Confirm cleanup:** verify the root `/prompts/` folder is gone and nothing in `backend/` still references the deleted constants (grep for `SPEAKER_ID_PROMPT`, `CRITERION_PROMPT_TEMPLATE`, `CHAT_SYSTEM_PROMPT_TEMPLATE`).

## Out of scope / future
- A `frontend/prompts/` folder (create only when the frontend gains a direct LLM call).
- Migrating prompts to LangChain `PromptTemplate` objects or a richer templating engine — `.txt` + `.format()` is sufficient and matches the approved format.
