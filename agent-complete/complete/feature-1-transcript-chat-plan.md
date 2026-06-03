# Feature #1 — Transcript Chat (right-docked panel)

## Context

From `context/bug-corrections.md`, Major Feature #1: on a call-review screen, the user
wants to chat with an LLM about **that one call**, grounded **only** in its transcript
("did the advisor say X?", "did the prospect say Y?"). The bot must never pull from other
transcripts or outside knowledge. The user wants the chat as a **right-hand sidebar**.

Scope was locked through a grilling session. Key product decisions:

1. **Ephemeral** conversation — client-side React state only. No DB, no migration.
2. **Single request/response** JSON (no streaming).
3. **Strictly grounded** in this transcript; refuses out-of-transcript questions. Cites
   timestamps + short quotes for **every** relevant moment. Light interpretation allowed
   **only** when anchored to a quoted, timestamped line.
4. Cited timestamps are **clickable** → auto-expand the transcript panel, scroll to that
   segment, briefly highlight it.
5. **Both roles** (bds_rep + financial_advisor), gated by the existing `_fa_can_access`.
6. **Chat button top-right** of the review screen → slides open a right-docked panel.
   Context persists across panel open/close; **resets on leaving the review** (state keyed
   to review `id`). Narrow screens → full-width overlay.
7. Button **disabled + tooltip** if transcript missing/empty (defensive guard; in practice
   only `complete` reviews are reachable).
8. No LLM key → honest **"chat unavailable"** message (testing case only).
9. **Minimal** empty state — one-liner + input, no starter prompts.
10. Failure → frontend-driven **auto-retry** ("retrying…" bubble), then terminal
    "couldn't get an answer, try again later". No manual clear.

**Intended outcome:** a self-contained, faithful interrogation tool on the results screen
that adds one stateless backend endpoint and one frontend panel, with zero schema changes.

The plan must also be saved to `C:\Users\Admin\Documents\GitHub\call_reviewer\agent\` per
`bug-corrections.md` (`agent/feature-1-transcript-chat-plan.md`), and `context/log.md` +
`context/map.md` updated per `CLAUDE.md`.

---

## Approach (backend-first, then frontend — project convention)

Router is already mounted at `/api` (`backend/main.py:34-37`) — no `main.py` change.

### A. Backend

**A1. `backend/modules/reviewer.py`**
- Add `AIMessage` to the existing import:
  `from langchain_core.messages import AIMessage, HumanMessage, SystemMessage`.
- Add `_format_transcript_labeled(transcript, speaker_map)` — like the existing
  `_format_transcript` (reviewer.py:140) but **with speaker labels + timestamps**, one line
  per segment: `[HH:MM:SS] Advisor: ...`. **Coerce speaker key to str** —
  `speaker_map.get(str(spk))` (map keys are strings `{"0":"Advisor"}`, `segment["speaker"]`
  is an int), fallback `Speaker {spk+1}` to mirror `TranscriptPanel`.
- Add `class LLMUnavailableError(RuntimeError)`.
- Add `CHAT_SYSTEM_PROMPT_TEMPLATE` enforcing: use ONLY the transcript; if unanswerable,
  reply exactly `"I can only answer questions about this call's transcript."`; cite **every**
  relevant moment as `HH:MM:SS` + short verbatim quote; quotes verbatim, timestamps must
  match a bracketed line; interpretation only when anchored to a citation; refer to speakers
  by role label.
- Add `chat_about_transcript(transcript, speaker_map, messages) -> str`:
  - `messages`: `[{"role":"user"|"assistant","content":str}, ...]` chronological, last is
    the new user turn.
  - Raise `LLMUnavailableError` if `get_llm_api_key()` is falsy.
  - Build `[SystemMessage(system_prompt)] + mapped turns` via
    `{"user":HumanMessage,"assistant":AIMessage}`; **system message is server-built, never
    accepted from the client** (prompt-injection guard).
  - `get_llm(temperature=0.0)` (verbatim extraction, not coaching) → `.invoke(...).content.strip()`.
  - Cap chat history sent to the model to the last ~8 turns (transcript carries grounding).

**A2. `backend/routers/reviews.py`** — new models + endpoint, reusing the existing
`get_review` + `_fa_can_access` gate (same pattern as reviews.py:69-105):
- `ChatMessage{role: Literal["user","assistant"], content: str}`, `ChatBody{messages: list[ChatMessage]}`,
  `ChatResponse{answer: str}`.
- `POST /reviews/{review_id}/chat`:
  - 404 if review missing; 404 if FA and not `_fa_can_access` (both roles otherwise allowed).
  - 400 if transcript empty, or if `messages[-1].role != "user"`.
  - Call `chat_about_transcript(transcript, review.get("speaker_map", {}), [m.model_dump()...])`.
  - `except LLMUnavailableError` → **503** "Chat is unavailable: no AI provider is configured."
    (client treats as permanent, no retry).
  - `except Exception` → log with `exc_info=True`, **502** "Couldn't get an answer…"
    (client retries this).

### B. Frontend

**B1. `frontend/src/services/api.js`**
- In `handleResponse` non-OK branch, attach status before throw:
  `const err = new Error(errorMessage); err.status = response.status; throw err`
  (backward compatible — existing callers ignore `.status`).
- Add `const CHAT_TIMEOUT_MS = 30_000` and
  `chatAboutReview(id, messages)` mirroring `updateReviewOutcome` (api.js:107-115), POSTing
  `{messages}` to `/reviews/${id}/chat` with the longer timeout. Returns `{ answer }`.

**B2. `frontend/src/pages/ResultsPage.jsx`** — owns chat state (lowest common ancestor of
chat + transcript):
- `const [isChatOpen, setIsChatOpen] = useState(false)`,
  `const [chatMessages, setChatMessages] = useState([])`,
  `const transcriptRef = useRef(null)`.
- In the existing `[id]` effect (ResultsPage.jsx:38-65) also reset
  `setChatMessages([]); setIsChatOpen(false)` → satisfies "resets on leaving the review".
- Make `results-page__header` a flex row: `<h1>` left, **Chat button** right
  (`onClick={() => setIsChatOpen(true)}`; disabled + `title` tooltip when
  `!review.transcript?.length`).
- Render `<ChatPanel>` as a **sibling of `<ReviewResults>`, inside `results-page` but
  outside `page-container`** so the fixed dock doesn't fight the centered container.
  Props: `reviewId={id}`, `messages={chatMessages}`, `setMessages={setChatMessages}`,
  `isOpen={isChatOpen}`, `onClose={() => setIsChatOpen(false)}`,
  `onTimestampClick={(ts) => transcriptRef.current?.jumpTo(ts)}`.
- Pass `transcriptRef` into `<ReviewResults>`.

**B3. `frontend/src/components/ChatPanel.jsx` (+ `ChatPanel.css`)** — new:
- Props `{ reviewId, messages, setMessages, isOpen, onClose, onTimestampClick }`.
- Internal `status: 'idle'|'sending'|'retrying'|'unavailable'|'failed'`, `retryAttempt`,
  `input`, `bottomRef` (auto-scroll).
- Render: minimal empty state (one-liner + input, no starter prompts); message thread
  (user right / assistant left, assistant text via `renderWithTimestamps`); pending bubble
  (`sending`→"…", `retrying`→"retrying… (attempt N)"); terminal `failed` bubble;
  `unavailable` inline notice with input disabled.
- `send(text)` appends the user turn to shared state immediately (survives close/reopen),
  then loops up to `MAX_ATTEMPTS=3` with backoff `[600,1500]ms`:
  `503 → unavailable` (no retry); `401 → failed` (api.js already redirected); other errors
  retried, else `failed`. Assistant answer appended only on success. Disable input while
  `sending`/`retrying`.
- `renderWithTimestamps(text, onTimestampClick)`: regex constructed **inside the function**
  (avoid stale `lastIndex`) `/\b(\d{2}:\d{2}:\d{2})\b/g`; each match → a
  `<button className="chat-panel__ts" onClick={() => onTimestampClick(ts)}>`.

**B4. `frontend/src/components/TranscriptPanel.jsx`** — add imperative jump:
- Convert to `forwardRef` + `useImperativeHandle(ref, () => ({ jumpTo }))`.
- Index-keyed `segmentRefs` array (`ref={(el)=>(segmentRefs.current[i]=el)}`), `highlightIdx`
  state, conditional `transcript-panel__segment--highlight` class.
- `jumpTo(ts)`: `setIsOpen(true)`; resolve index via **exact match then nearest-by-seconds**
  (`resolveIndex`); in `requestAnimationFrame` (content is unmounted while collapsed)
  `scrollIntoView({block:'center', behavior:'smooth'})` (scrolls within the
  `max-height:400px` content container), set `highlightIdx`, clear after ~1.6s. Double-RAF if
  the single frame proves flaky on expand-from-closed.
- Highlight CSS flash reusing tokens (`--color-primary-disabled` → transparent).

**B5. `frontend/src/components/ReviewResults.jsx`** — accept and forward `transcriptRef` to
`<TranscriptPanel ref={transcriptRef} ... />` (currently ReviewResults.jsx:134).

**B6. `ChatPanel.css` layout** — `position:fixed; top:64px; right:0; bottom:0; width:420px;
z-index:90` (clears the sticky 64px `.top-nav` at z-index:100). Slide via
`transform: translateX(100%)`→`translateX(0)` with `--transition-base`, `pointer-events:none`
when closed. Flat surfaces per DESIGN.md (`--color-surface`, `1px solid --color-hairline`,
no heavy shadow). Bottom-pinned input row; send button yellow `--color-primary` with **black
text `--color-on-primary`**. `@media (max-width:768px){ width:100% }`. `.chat-panel__ts`
inline, `--color-primary`, underline on hover (echoes `.transcript-panel__timestamp`).

### Docs (per CLAUDE.md)
- Save this plan to `agent/feature-1-transcript-chat-plan.md`.
- Update `context/log.md` (new dated entry) and `context/map.md` (new `ChatPanel.jsx/.css`,
  the `reviewer.py` chat function, the `POST /reviews/{id}/chat` endpoint + `api.js` wrapper,
  the `TranscriptPanel` imperative `jumpTo`).
- Add a decision note to `context/decisions.md` (ephemeral client-side chat; strictly grounded;
  clickable-timestamp coordination via imperative handle).

---

## Critical files
- `backend/modules/reviewer.py` — chat function, labeled formatter, system prompt, error type
- `backend/routers/reviews.py` — models + `POST /reviews/{id}/chat`
- `frontend/src/services/api.js` — `chatAboutReview`, `.status` on errors, chat timeout
- `frontend/src/pages/ResultsPage.jsx` — chat state ownership, button, panel mount, reset-on-id
- `frontend/src/components/ChatPanel.jsx` (+ `.css`) — the panel (new)
- `frontend/src/components/TranscriptPanel.jsx` — `forwardRef` + `jumpTo`
- `frontend/src/components/ReviewResults.jsx` — forward `transcriptRef`

## Risks / mitigations
- **Token budget** (full transcript resent each turn): keep full transcript (completeness is
  the product value), cap history to last ~8 turns, soft-log oversize transcripts. RAG/chunking
  is an explicit follow-up if real transcripts exceed the model window.
- **Hallucinated/off-by-a-second timestamps**: `resolveIndex` nearest-by-seconds + temp 0 +
  strict prompt.
- **401 during retry**: treated as terminal (api.js already refreshes/redirects).
- **Timestamp collisions**: jump to first occurrence — acceptable.

## Verification (end-to-end)
1. Start app: `start.ps1` (backend uvicorn :8000, frontend :5173). Python via `py -m`.
2. **No-key path:** with `DEEPSEEK_API_KEY` unset, open a complete review → click Chat → send
   a message → expect inline "Chat is unavailable…" (503), no retry loop.
3. **Happy path:** with the key set, ask "Did the advisor mention fees?" → grounded answer
   citing `HH:MM:SS` + quotes for **all** matching moments; an out-of-transcript question
   ("what's a good withdrawal rate?") → the exact refusal sentence.
4. **Clickable timestamp:** collapse the transcript, click a cited timestamp in an answer →
   transcript auto-expands, scrolls to that segment, briefly highlights it.
5. **Context lifecycle:** close/reopen the panel within a review → conversation persists;
   navigate to a different review → conversation is empty.
6. **Failure/retry:** simulate an LLM error (e.g. temporarily break the provider) → "retrying…"
   bubble cycles, then terminal "couldn't get an answer, try again later".
7. **Access control:** confirm an FA can chat on their own firm's FA-uploaded review and gets
   404 on a review they can't access (reuses `_fa_can_access`).
8. **Responsive:** narrow the viewport < 768px → panel becomes a full-width overlay.
