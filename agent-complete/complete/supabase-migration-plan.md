# Plan: Migrate Storage from Disk to Supabase

## Context

The app is evolving from a personal local tool into a production application for the full team and eventually financial advisor clients. Local disk storage (`backend/data/`) cannot survive cloud hosting or support multiple users. This migration replaces all persistent storage with Supabase Postgres, laying the infrastructure foundation for Feature #3 (user auth) and cloud deployment.

---

## Decisions Made (grill-me session)

- Single-tenant; access control enforced in FastAPI layer only — no Row Level Security needed
- Hybrid schema: scalar metadata columns + JSONB for transcript, review results, framework
- Templates: global (all BDS reps see all templates) with `created_by` ownership (nullable until auth lands in Feature #3)
- Existing data: migrate templates only — reviews start fresh, recordings stay on disk as-is
- Rollout: hard cutover — disk storage code removed entirely, no fallback
- Client: `supabase-py` SDK with `service_role` key
- All existing public function signatures in `storage.py` and `templates.py` stay identical — no router or frontend changes needed
- `migrate_default_template()` updated: migrates disk templates to Supabase on first startup, seeds Rudimentary if absent

---

## Step 1 — Supabase Project Setup (manual)

1. Create a new project at supabase.com
2. Run this SQL in the Supabase SQL editor:

```sql
-- Reviews table (scalar metadata columns + JSONB blobs)
CREATE TABLE reviews (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    advisor_name TEXT,
    firm TEXT,
    prospect_name TEXT,
    bds_rep TEXT,
    original_filename TEXT,
    speaker_map JSONB,
    transcript JSONB,
    review_results JSONB,
    framework JSONB
);

CREATE INDEX reviews_created_at_idx ON reviews (created_at DESC);
CREATE INDEX reviews_advisor_name_idx ON reviews (advisor_name);
CREATE INDEX reviews_firm_idx ON reviews (firm);
CREATE INDEX reviews_bds_rep_idx ON reviews (bds_rep);

-- Templates table
CREATE TABLE templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    created_by TEXT,
    criteria JSONB NOT NULL
);
```

3. Copy `SUPABASE_URL` (Project URL) and `SUPABASE_KEY` (service_role secret key) from Project Settings → API
4. Add both to `.env`:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-secret-key
```

---

## Review Record Schema (disk → Supabase mapping)

The existing review dict uses a nested `metadata` key and `"review"` for results. The Supabase row flattens metadata into columns and renames `"review"` → `review_results`. `_to_row()` / `_from_row()` helpers in `storage.py` handle the translation transparently so callers see no change.

```
review dict key          → Supabase column
─────────────────────────────────────────
id                       → id (TEXT PK)
created_at               → created_at (TIMESTAMPTZ)
status                   → status (TEXT)
metadata.advisor_name    → advisor_name (TEXT)
metadata.firm            → firm (TEXT)
metadata.prospect_name   → prospect_name (TEXT)
metadata.bds_rep         → bds_rep (TEXT)
metadata.original_filename → original_filename (TEXT)
speaker_map              → speaker_map (JSONB)
transcript               → transcript (JSONB)
review                   → review_results (JSONB)
framework                → framework (JSONB)
```

---

## Implementation Steps

### Backend

**Step 2: `backend/requirements.txt` (modify)**

Add: `supabase>=2.0.0`

---

**Step 3: `.env` and `.env.example` (modify / create)**

Add to `.env`:
```
SUPABASE_URL=
SUPABASE_KEY=
```

Create `.env.example` with all keys (no values).

---

**Step 4: `backend/modules/supabase_client.py` (new)**

Lazy singleton client:
```python
import os
from supabase import create_client, Client

_client: Client | None = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
    return _client
```

---

**Step 5: `backend/modules/storage.py` (rewrite internals)**

Keep all public function signatures identical. Key changes:
- `save_review(review)` → `supabase.table("reviews").upsert(_to_row(review)).execute()`
- `get_review(review_id)` → `.select("*").eq("id", review_id).execute()` → `_from_row(data[0])` or `None`
- `list_reviews()` → `.select("*").order("created_at", desc=True).execute()`
- `delete_review(review_id)` → check exists first (raise `FileNotFoundError` if not), then `.delete().eq("id", review_id).execute()`
- `save_recording` / `delete_recording` / `RECORDINGS_DIR` — **unchanged**, remain disk-based (temp files only)
- Remove `REVIEWS_DIR` and `_ensure_dirs()`; keep `RECORDINGS_DIR` (used in `routers/reviews.py`)

---

**Step 6: `backend/modules/templates.py` (rewrite internals)**

Keep all public function signatures identical. Key changes:
- Remove `get_templates_dir()` helper entirely
- All CRUD functions use `get_client().table("templates")...`
- `migrate_default_template()` — three-phase startup migration:
  1. If Supabase already has templates → return (no-op forever after first run)
  2. Read all JSON files from both disk locations (`project_root/data/templates/` and `backend/data/templates/`), upsert each to Supabase preserving existing ids and timestamps
  3. If "Rudimentary" still absent → create it using `DEFAULT_CRITERIA`

---

**Step 7: Delete orphaned WAV files (Bug #2)**

Delete all 8 files in `backend/data/recordings/`. The recordings directory stays on disk for future temp files.

---

### No changes needed to

- `routers/upload.py`
- `routers/reviews.py`
- `routers/templates.py`
- `main.py`
- Any frontend files

---

## Critical Files

| File | Action |
|---|---|
| `backend/requirements.txt` | **MODIFY** — add `supabase>=2.0.0` |
| `.env` | **MODIFY** — add `SUPABASE_URL`, `SUPABASE_KEY` placeholders |
| `.env.example` | **CREATE** — all keys, no values |
| `backend/modules/supabase_client.py` | **CREATE** — singleton client |
| `backend/modules/storage.py` | **REWRITE INTERNALS** — Supabase for reviews, disk for recordings |
| `backend/modules/templates.py` | **REWRITE INTERNALS** — Supabase, one-time disk migration on startup |
| `backend/data/recordings/*.wav` | **DELETE** — 8 orphaned files (Bug #2) |
| `context/decisions.md` | **UPDATE** |
| `context/log.md` | **UPDATE** |
| `context/map.md` | **UPDATE** |
| `context/deferredwork.md` | **UPDATE** |

---

## Verification

1. Complete Step 1 (create Supabase project, run SQL, add credentials to `.env`)
2. Install dependencies: `py -m pip install -r backend/requirements.txt`
3. Start backend: `py -m uvicorn main:app --reload` from `backend/`
4. Check startup log — should see template migration message on first run, no-op on subsequent starts
5. `GET /api/templates` → should return the two migrated templates
6. Upload a new call end-to-end → confirm row appears in Supabase `reviews` table
7. Check history page → new review appears in list
8. Delete a review → confirm row removed from Supabase
9. Confirm no new files created in `backend/data/reviews/` (directory should not exist)
10. Confirm `backend/data/recordings/` is empty (WAV files gone)
