---
name: call-reviewer
description: Upload sales call recordings to the Call Reviewer app for AI scoring and coaching, then retrieve the PDF report and a draft coaching email, tag and search past calls, and run cross-call coaching analysis (e.g. "which criterion does this advisor consistently score low on"). Use when the user wants to review or coach a sales call, pull a call's PDF/email, organize calls with tags, or analyze advisor performance across multiple calls.
---

# Call Reviewer

Drive the Call Reviewer app from chat: upload a recording, wait for the AI review, download the PDF, draft a coaching email, tag/search calls, and analyze patterns across many calls. Everything goes through one script, `scripts/review_call.py` (Python 3, standard library only — no installs).

## Configuration (required)

The script authenticates with an **API key** (the app's "API keys" screen mints one; it inherits your role). Provide it either way:

- Environment: `CALL_REVIEWER_API_URL` (e.g. `https://your-app.up.railway.app`) and `CALL_REVIEWER_API_KEY` (`ak_live_...`).
- Or per-call flags: `--api-url` and `--api-key`.

Never print the API key back to the user.

## Workflow

Run subcommands with `python scripts/review_call.py <command> ...`. Each prints a JSON result on the last line; read it and summarize for the user. Use `--help` on any command.

### 1. Review a call (`review`)
Upload → poll until done → download PDF → (optionally) draft the coaching email.
```
python scripts/review_call.py review \
  --file "/path/to/recording.mp3" \
  --prospect "Jane Prospect" \
  --advisor "John Advisor" \
  --firm "Acme Wealth" \
  [--template "Discovery Call"] [--outcome "Booked follow-up"] \
  [--out-dir .] [--no-email]
```
- The user attaches the audio to the conversation; use its path as `--file` (mp3/mp4/m4a/wav, up to 200 MB).
- `--advisor`/`--firm` are required when your key is a BDS-rep key; the script resolves names to IDs for you. If a name is ambiguous, it lists the matches so you can re-run with an exact one.
- Template defaults to your per-rep default if `--template` is omitted.
- Output: the saved PDF path and the `{subject, body}` email draft. Present the email to the user for review; do not send it.

### 2. Search past calls (`search`)
```
python scripts/review_call.py search [--advisor NAME] [--firm NAME] \
  [--outcome NAME] [--template NAME] [--tag NAME] \
  [--status complete] [--min-score 0] [--max-score 10] [--limit 500]
```
Prints matching calls (id, advisor, firm, date, score, tags). Filters are case-insensitive substring matches.

### 3. Tag a call (`tag`)
```
python scripts/review_call.py tag --review-id <id> --tags "Objection,Follow-up" [--replace]
```
Creates any missing tags, then assigns them (merges with existing tags unless `--replace`). BDS-rep key required.

### 4. Cross-call analysis (`analyze`)
Ask a question across a filtered set of calls — the app's agent reads the scores, feedback, and transcripts and answers.
```
python scripts/review_call.py analyze \
  --question "Which criterion are they consistently scoring lowest on, with examples?" \
  [--advisor NAME] [--firm NAME] [--tag NAME] [--template NAME] [--outcome NAME] \
  [--review-ids id1,id2,...]
```
Supply either filters (the script selects the matching calls, newest 200) or an explicit `--review-ids` list. Prints the agent's answer. Example: *"across all of ABC Advisor's calls at XYZ firm, where do they consistently score low?"* → `--advisor "ABC" --firm "XYZ"`.

## Notes
- Only `complete` reviews can produce a PDF, email, or enter analysis; the script surfaces `pending`/`transcribing`/`reviewing`/`failed` clearly.
- All commands exit non-zero and print an `error` JSON on failure (bad key → 401, wrong role → 403, file too big → 413).
