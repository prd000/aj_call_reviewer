# Plan: Markdown rendering in chatbot replies (with preserved clickable timestamps)

## Context

Both chatbots — the single-call chat on the Results page and the cross-call History Analysis chat — share one component, `frontend/src/components/ChatPanel.jsx`. The LLM frequently emits Markdown (tables, headers, bullet lists, bold), but assistant replies are currently rendered as a raw string (`ChatPanel.jsx:139-141`). The result is literal `**bold**`, `|---|` pipe tables, and `#` headers showing as plain text, which reads poorly. This is feature/bug #6 in `context/bug-corrections.md`.

Goal: render assistant replies as Markdown on **both** chat surfaces, while **preserving** the existing clickable-timestamp feature (Results-page chat turns `HH:MM:SS` into buttons that jump the transcript via `onTimestampClick`). Per decision: Markdown applies to **assistant replies only**; user-typed bubbles stay verbatim plain text.

The challenge is composition: the current timestamp linkifier (`renderWithTimestamps`, `ChatPanel.jsx:7-29`) is a string-level transform, and it must continue to work *inside* rendered Markdown (a timestamp may appear in a paragraph, list item, or table cell). The clean way to do this with `react-markdown` is a small rehype plugin that turns timestamp text into a custom node, rendered by a custom component that closes over `onTimestampClick`.

No Markdown library currently exists in the frontend (confirmed — zero matches for markdown/remark/react-markdown/dangerouslySetInnerHTML).

## Approach

### 1. Add dependencies (`frontend/package.json`)
- `react-markdown` (^9) — renderer; safe by default (no raw HTML, so no XSS exposure).
- `remark-gfm` (^4) — GitHub-flavored Markdown: tables, strikethrough, task lists, autolinks.
- `unist-util-visit` (^5) — tree walker for the timestamp rehype plugin (tiny, ubiquitous).

Install with `npm install` in `frontend/` (project uses React 18.2, compatible with react-markdown 9).

### 2. New component: `frontend/src/components/MarkdownMessage.jsx`
A focused wrapper around `<ReactMarkdown>` that:
- Applies `remarkPlugins={[remarkGfm]}`.
- Conditionally applies a custom **rehype timestamp plugin** only when `onTimestampClick` is provided (so History chat, which omits the prop, gets plain rendering and never produces dead buttons).
- Defines a `components` map (memoized via `useMemo` so it isn't recreated each render) for:
  - `timestamp` (the custom element emitted by the plugin) → renders the existing `.chat-panel__ts` button, calling `onTimestampClick(value)`. This *replaces* the role of `renderWithTimestamps` while keeping identical button markup/class.
  - `a` → force `target="_blank" rel="noopener noreferrer"`.
- Wraps output in a `<div className="chat-panel__markdown">` for CSS scoping.

**Rehype timestamp plugin** (same file or a small `frontend/src/lib/rehypeTimestamps.js`):
- Uses `unist-util-visit` to visit HAST `text` nodes whose value matches `/\b(\d{2}:\d{2}:\d{2})\b/g` (reuse the exact regex from `renderWithTimestamps`).
- Splits each matching text node into a sequence of text nodes + custom `element` nodes `{ tagName: 'timestamp', properties: { value: ts } }`, replacing the original node's place in its parent's `children`.
- Skip nodes already inside `<a>`/`<code>`/`<pre>` to avoid mangling links and code samples.

### 3. Wire into `ChatPanel.jsx`
- Import `MarkdownMessage`; remove the now-superseded `renderWithTimestamps` helper (its regex moves into the rehype plugin).
- Replace the assistant branch (`ChatPanel.jsx:139-141`) with:
  - assistant → `<MarkdownMessage content={msg.content} onTimestampClick={onTimestampClick} />`
  - user → `{msg.content}` (unchanged, plain text).
- No prop-signature changes to `ChatPanel`; both `ResultsPage.jsx` and `HistoryPage.jsx` keep their existing usage. `onTimestampClick` continues to be passed only by `ResultsPage` (`ResultsPage.jsx:153-160`); `HistoryPage` continues to omit it (`HistoryPage.jsx:325-335`).

### 4. Markdown CSS (`frontend/src/components/ChatPanel.css`)
Scope everything under `.chat-panel__markdown` so styles never leak outside assistant bubbles. Reuse design tokens from `styles/tokens.css`; follow `context/DESIGN.md` (flat surfaces, hairline borders, yellow accent used sparingly, no drop shadows).
- **Whitespace fix:** the bubble currently sets `white-space: pre-wrap`; override to `white-space: normal` inside `.chat-panel__markdown` (Markdown now produces real block elements, so `pre-wrap` would inject spurious blank lines).
- **Margin reset:** `p, ul, ol, h1–h6, table, pre, blockquote` get tight vertical rhythm; first-child `margin-top:0` / last-child `margin-bottom:0` so bubble padding isn't doubled.
- **Tables:** hairline borders (`--color-hairline`), bold header row, `--space-xxs/--space-xs` cell padding; wrap in `overflow-x:auto` so wide tables scroll horizontally rather than break the fixed 420px panel.
- **Lists:** restore `padding-left` (~`--space-md`) and list markers.
- **Code:** inline `code` → subtle background (`--color-surface`/`--color-canvas`) + `'Courier New', Courier, monospace` (same stack as `.chat-panel__ts`); `pre` block → padded background box with `overflow-x:auto`.
- **Links:** `--color-primary`, no underline default, underline on hover (matches DESIGN.md text-link rule).
- **Headers:** scaled down to fit the 13px bubble (e.g. h1≈16px → h3≈13px bold), modest top margin.
- **Blockquote:** left border (`--color-hairline` or a thin `--color-primary` accent), muted text, left padding.

### 5. Docs (per CLAUDE.md)
- `context/log.md` — add a dated entry: Markdown rendering for assistant chat replies via react-markdown + remark-gfm; timestamps preserved through a rehype plugin.
- `context/map.md` — add `MarkdownMessage.jsx` (and `lib/rehypeTimestamps.js` if split out) under `frontend/src/components`; update the `ChatPanel.jsx` entry to note assistant replies render Markdown and that `renderWithTimestamps` was replaced by the rehype-plugin path.
- `context/deferredwork.md` — no entry needed (no new API keys or external config).

## Files touched
- `frontend/package.json` (+ lockfile) — new deps
- `frontend/src/components/MarkdownMessage.jsx` — **new**
- `frontend/src/lib/rehypeTimestamps.js` — **new** (optional split; otherwise colocated in MarkdownMessage.jsx)
- `frontend/src/components/ChatPanel.jsx` — swap render path, drop old helper
- `frontend/src/components/ChatPanel.css` — `.chat-panel__markdown` styles
- `context/log.md`, `context/map.md` — docs

## Verification
1. `cd frontend; npm install` then run app (`start.ps1`, or `npm run dev` + backend `py -m uvicorn`).
2. **Results chat (single call):** open a call with a transcript, ask something that elicits a table + bullets + bold (e.g. "summarize the scores as a table"). Confirm the table, list, and bold render properly inside the bubble and the panel doesn't break; wide table scrolls horizontally.
3. **Timestamp preservation:** ask a question whose answer cites a moment (e.g. "when did they mention fees?") so the reply contains `HH:MM:SS`. Confirm it renders as a clickable yellow button — including when it lands inside a list item or table cell — and clicking jumps the transcript (`transcriptRef.jumpTo`).
4. **History chat:** open History Analysis, ask for a cross-call comparison table. Confirm Markdown renders; confirm any `HH:MM:SS` appears as plain text (no button, no console error) since `onTimestampClick` is absent.
5. **User bubbles:** type a message containing `**stars**` and a `| pipe |`; confirm it stays verbatim (no Markdown interpretation).
6. **Safety/layout:** confirm links open in a new tab with `rel="noopener noreferrer"`; check mobile width (≤768px, panel full-width) still lays out cleanly; run `npm run lint`.
