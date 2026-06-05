# Major Feature #6 — History Chatbot (Agentic, cross-call pattern analysis)

## Context

Today the only chatbot (`ChatPanel` + `POST /reviews/{id}/chat` + `reviewer.chat_about_transcript`) answers questions about **one** call by stuffing that call's full transcript into the prompt. Feature #6 asks for a **second** chatbot that reasons across **all the calls currently visible on the History screen** — whatever the active firm/advisor/template/BDS-rep/outcome/search filters have narrowed the list to — so a manager can find patterns ("where is this firm weakest?", "are scores improving?", "which no-sale calls show the same objection?").

The original ask framed this as a **RAG pipeline** because the call corpus will outgrow any context window over years of client history. During grilling we chose a **simpler architecture that solves the same constraint**: an **agentic retrieval** loop. The agent is given a compact triage table (scores + summaries) for every scoped call up front and **reads full transcripts/feedback only on demand**, so it never loads the whole corpus at once — the same escape from the context ceiling that RAG provides, but with **no embedding provider, no pgvector, no chunking, no indexing pipeline, and no backfill of existing calls**. It also needs **no DB migration**: every datum it uses already lives on the review record.

This fits the primary use case (pattern-finding) better than RAG, because patterns live in the **structured scores**, which the agent reasons over directly.

## Decisions locked during grilling

| Branch | Decision |
|---|---|
| Architecture | Agentic retrieval, **no embeddings / no RAG infra / no migration** |
| Up-front context (all scoped calls) | metadata (advisor, firm, date, outcome, template) + overall & per-criterion **scores** + the call **summary** |
| On-demand tools | `get_feedback(call_id)` (per-criterion feedback prose), `read_transcript(call_id)` (full transcript) — both **restricted to the scoped IDs** |
| Reads | Inline into the orchestrator context (no sub-agents), bounded by a max-reads / max-iterations guard |
| Model | Configurable per-role via new `CHAT_AGENT_MODEL` env var, **default to the stronger model** (DeepSeek "Pro"); flip to Flash via env to A/B |
| Scope | The History page's **currently-visible review IDs**, sent on every message; scope follows the filters per-message |
| Scale guard | Token-budgeted: load summaries newest-first; if over budget, include scores-only for overflow and tell the agent "showing summaries for N of M most recent calls" |
| Access | **Both roles**, bounded by the existing `_fa_can_access` rule (FA only ever sees own firm's FA-uploaded calls) |
| Latency UX | **Single-shot** POST→JSON, mirror the existing `…` pending bubble (`ChatPanel.jsx:139-148`); only change is a longer client timeout (~90s) so the slow loop doesn't false-fail |
| Citations | v1: agent refers to calls by advisor + date in prose (no clickable call links yet — future enhancement) |
| Scope inclusion | Only `complete` reviews with scored categories enter the working set; pending/failed are excluded (no scores to reason over) |

## Backend changes

Edit backend first, then wire the frontend (per CLAUDE.md).

### 1. `backend/modules/llm_config.py` — per-role model override
- Add an optional `role` arg: `get_llm(temperature: float, role: str | None = None) -> ChatOpenAI`.
- When `role == "history_chat"`, prefer `CHAT_AGENT_MODEL` over `LLM_MODEL`/`default_model` (env-first, no hardcoding). Existing callers unaffected (default `role=None`).
- Add `CHAT_AGENT_MODEL` to `.env.example` (commented, with note that it defaults to the provider's default model).

### 2. `backend/modules/history_chat.py` — new module (the agent loop)
- `chat_over_reviews(scoped_reviews: list[dict], messages: list[dict]) -> str`.
  - Raises `LLMUnavailableError` (reuse from `reviewer.py`) when no API key — same 503 path as the single-call chat.
  - Builds the **triage table** from each review's already-loaded fields: `metadata` (advisor_name, firm, created_at/date, call_outcome, framework.template_name), `overall_score`, and per-criterion `{name, score, max_score}` from `review["review"]["categories"]`, plus `review["review"]["summary"]`. Assign each call a short stable handle (e.g. `C1`, `C2`) mapped to its real review id so the model references calls without leaking UUIDs.
  - **Tools** via `llm.bind_tools([...])`:
    - `get_feedback(call)` → the `feedback` strings from that call's categories.
    - `read_transcript(call)` → `_format_transcript_labeled` (reuse from `reviewer.py`) of that call's transcript + speaker_map.
    - Both validate `call` is in the scoped set; out-of-scope → return an error string (defense in depth — the agent can only touch what was passed in).
  - **Loop**: hand-rolled tool-calling loop (no LangGraph) — invoke, if the response has `tool_calls` execute them, append `ToolMessage`s, re-invoke; stop on a plain text answer. Caps: `MAX_ITERATIONS` (~12) and `MAX_TRANSCRIPT_READS` (~10); when a cap is hit, force a final answer and note the limitation.
  - Model: `get_llm(temperature=0.2, role="history_chat")`.
- New prompt file `backend/prompts/history_chat.system.txt` (externalized per the prompts decision; loaded via `load_prompt`). Instructs: you analyze a SET of calls to find patterns; the triage table is your map; use `get_feedback`/`read_transcript` to dig into the "why" or exact quotes; reason over the scores for aggregate/trend questions; refer to calls by advisor + date; do not invent calls or data.

### 3. `backend/routers/reviews.py` — new endpoint
- `POST /reviews/history-chat` with body `{ review_ids: list[str], messages: list[ChatMessage] }` (reuse the existing `ChatMessage` model; add a `HistoryChatBody`).
- Resolve scope safely server-side:
  - For each id, `get_review(id)`; drop any not found, not `complete`, or (for FA) failing `_fa_can_access`. **Never trust the client's list blindly** — re-apply visibility.
  - Apply the newest-first token-budget trim (helper in `history_chat.py`).
- Validate last message is from the user (mirror existing chat).
- Call `history_chat.chat_over_reviews(scoped, [m.model_dump() ...])`; return `{ answer }`.
- Error classification identical to the single-call chat: 503 `LLMUnavailableError`, 502 catch-all, 400 bad/empty messages, plus a friendly answer when **zero** calls are in scope (return `{answer: "No completed calls match the current filters…"}` rather than an error).

### 4. `backend/main.py`
- No new router needed — the endpoint lives on the existing `reviews.router`. (If preferred, a `routers/history_chat.py` registered like the others in `main.py:34-37`; default is to keep it on `reviews.router`.)

## Frontend changes

### 5. `frontend/src/services/api.js`
- Add `CHAT_AGENT_TIMEOUT_MS = 90_000`.
- Add `chatOverHistory(reviewIds, messages)` — POST `/reviews/history-chat`, body `{ review_ids, messages }`, the longer timeout, same `handleResponse` / `err.status` plumbing as `chatAboutReview` (`api.js:120-128`).

### 6. Lift filtering from `ReviewList` to `HistoryPage` (enables scope)
- Move the `reviews.filter(...)` block (`ReviewList.jsx:183-206`) into a `useMemo` in `HistoryPage.jsx`, producing `visibleReviews`. Pass `visibleReviews` down to `ReviewList` for rendering (ReviewList keeps only its sort + render), and derive `visibleIds = visibleReviews.map(r => r.id)`.
- This is the minimal refactor that gives the chat panel exactly "what's on screen." Keep behavior identical — same predicates, same `NO_OUTCOME` handling, same free-text search fields.

### 7. New `HistoryChatPanel` + FAB on `HistoryPage`
- Reuse the `ChatPanel` shell/CSS (`ChatPanel.css` — `position:fixed; top:64px; right:0; width:420px`, `--open` transform, mobile full-width). Either generalize `ChatPanel` to accept an injected `send` function + header title, or fork a `HistoryChatPanel` that copies its status/`…`-pending/retry logic (`ChatPanel.jsx:59-96, 139-148`) but calls `chatOverHistory(visibleIds, msgs)` and renders plain text (no timestamp linkify). Prefer generalizing to avoid duplication.
- Replicate the `ResultsPage` FAB pattern (`ResultsPage.jsx:142-162`): own `isHistoryChatOpen` + `historyChatMessages` in `HistoryPage`; reuse the `RobotIcon` SVG; `--hidden` while open.
- **Scope header** in the panel: "Asking about {visibleIds.length} call{s} matching your filters" so the user always knows the scope. Disable the FAB when `visibleIds.length === 0`.
- Conversation is **ephemeral client-side** (HistoryPage state), like the single-call chat. It is **not** auto-reset when filters change — each message re-sends the current `visibleIds`, so the scope naturally follows the filters; the live header communicates the change.

## Reuse (do not reinvent)
- `reviewer._format_transcript_labeled`, `reviewer.LLMUnavailableError`, `prompts.load_prompt`.
- `reviews._fa_can_access` for FA scope enforcement; `storage.get_review` for per-id loads.
- `ChatPanel` send/retry/`…`-pending UI and `ChatPanel.css`; `ResultsPage` FAB + `RobotIcon`.
- `llm_config.get_llm` (extended, not replaced).

## Docs to update (per CLAUDE.md)
- `context/log.md` — feature entry.
- `context/map.md` — new `history_chat.py`, `history_chat.system.txt`, new endpoint, `chatOverHistory`, `HistoryChatPanel`, lifted filtering in `HistoryPage`/`ReviewList`, `get_llm(role=...)`.
- `context/decisions.md` — "Feature #6 — Agentic history chatbot (no RAG/embeddings, no migration; triage table + on-demand tools; configurable CHAT_AGENT_MODEL; visibility-scoped both roles)."
- `context/deferredwork.md` — note `CHAT_AGENT_MODEL` is optional (defaults to provider default); no new required key.

## Verification
- **Backend unit**: a `history_chat` test with stubbed `get_llm` — assert the triage table is built from `review["review"]` correctly, tools reject out-of-scope ids, the loop honors `MAX_TRANSCRIPT_READS`, and zero-scope returns the friendly message. Follow the `backend/tests` style.
- **Backend integration** (manual, `py -m uvicorn`): `POST /api/reviews/history-chat` as a BDS rep with a set of complete review ids → pattern question returns an answer; as an FA, pass ids from another firm → they're silently dropped (visibility). No-provider env → 503.
- **End-to-end** (`start.ps1`): on `/history`, filter to a firm, open the robot FAB, confirm the header count matches the visible rows, ask "where is this firm weakest?" → answer cites advisors/dates; change the firm filter and confirm the next answer re-scopes. Verify the `…` pending bubble shows during the (longer) wait and a ~40s answer does not time out.
- Confirm Flash override: set `CHAT_AGENT_MODEL` to the Flash model and re-ask to sanity-check tool-calling reliability vs. Pro.
