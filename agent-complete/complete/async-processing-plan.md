# Major Feature #1 — Async Processing with Celery + Redis

## Context
The app currently processes call reviews synchronously — upload triggers transcription + LLM review in a single blocking HTTP request, freezing the UI and preventing concurrent jobs. This plan adds Celery + Redis for async job processing, Supabase Storage for file handling (required for Railway's multi-service deployment where web and worker don't share a filesystem), and updates the history page to show real-time job status via polling.

Target scale: 300 clients, hundreds of eventual users on Railway Hobby plan.

---

## Decisions
- **Task queue**: Celery + Redis — 3 Railway services: FastAPI web, Celery worker, Redis plugin
- **Status storage**: Supabase reviews table — add `error_message`, `storage_path`, `celery_task_id` columns (`status` already exists)
- **Status states**: `pending → transcribing → reviewing → complete → failed`
- **File storage**: Supabase Storage bucket `recordings` (private) — upload on ingest, pass signed URL to Rev.ai, delete on complete/failed
- **Post-upload redirect**: straight to `/history`; `ProcessingPage` removed entirely
- **Polling**: history page only, every 5s; stops when no in-progress rows remain
- **In-progress rows**: status badge + spinner replacing score; not clickable
- **Failed rows**: red "Failed" badge + delete button; deletes row + Supabase Storage file; user re-uploads
- **Celery task**: single end-to-end task, 2 auto-retries before `failed`
- **Template**: pass `template_id` in upload form data; Celery task fetches criteria from Supabase at runtime
- **LLM**: use existing `get_llm()` from `backend/modules/llm_config.py` — never reference any provider directly

---

## Critical Files

### New files
- `backend/celery_app.py` — Celery app instance (reads `REDIS_URL` from env)
- `backend/tasks.py` — `process_review_task`: full transcribe → review pipeline with status updates
- `Procfile` — Railway process definitions for web and worker

### Backend modifications
- `backend/modules/storage.py` — add Supabase Storage functions; extend `_to_row`/`_from_row` for new columns
- `backend/routers/upload.py` — accept `template_id`; upload to Supabase Storage; enqueue task; return immediately
- `backend/routers/reviews.py` — DELETE cleans up Supabase Storage; remove `/process` endpoint; rename `error` → `failed`
- `requirements.txt` — add `celery[redis]`
- `.env.example` — add `REDIS_URL`

### Frontend modifications
- `frontend/src/pages/UploadPage.jsx` — append `template_id` to formData; remove `processReview` call; navigate to `/history`
- `frontend/src/pages/HistoryPage.jsx` — add 5s polling interval; stop when no in-progress rows
- `frontend/src/components/ReviewList.jsx` — status badges, spinners, non-clickable in-progress rows, delete button for failed
- `frontend/src/services/api.js` — remove `processReview` export
- `frontend/src/App.jsx` — remove `/processing/:id` route

### Files to delete
- `frontend/src/pages/ProcessingPage.jsx`
- `frontend/src/pages/ProcessingPage.css`

### Supabase (manual steps before implementation)
Run in Supabase SQL editor:
```sql
ALTER TABLE reviews
  ADD COLUMN IF NOT EXISTS error_message text,
  ADD COLUMN IF NOT EXISTS storage_path text,
  ADD COLUMN IF NOT EXISTS celery_task_id text;
```
Create a private `recordings` storage bucket in the Supabase Storage dashboard.

---

## Implementation Steps

### 1. Supabase schema + storage bucket
- Run the SQL migration above
- Create `recordings` bucket (private) in Supabase Storage dashboard

### 2. `backend/celery_app.py` (new)
```python
import os
from celery import Celery

app = Celery(
    "call_reviewer",
    broker=os.environ["REDIS_URL"],
    backend=None,  # Supabase is the source of truth; no Celery result backend
    include=["tasks"],
)
```

### 3. `backend/modules/storage.py`
Extend `_to_row` and `_from_row` to include `error_message`, `storage_path`, `celery_task_id`.

Add functions:
- `upload_recording_to_storage(review_id, file_bytes, filename) -> str` — uploads to `recordings/` bucket, returns storage path
- `delete_recording_from_storage(storage_path: str) -> None` — deletes from bucket, silent if missing
- `get_recording_signed_url(storage_path: str) -> str` — returns a signed URL valid for 1 hour (for passing to Rev.ai)
- `update_review_status(review_id, status, *, error_message=None, celery_task_id=None)` — partial upsert helper

Keep existing disk-based `save_recording`/`delete_recording` but they will no longer be called by the upload flow.

### 4. `backend/tasks.py` (new)
```python
from celery_app import app
from modules import storage, transcriber, reviewer
from modules.templates import get_template

@app.task(bind=True, max_retries=2, default_retry_delay=10)
def process_review_task(self, review_id: str, template_id: str):
    try:
        storage.update_review_status(review_id, "pending", celery_task_id=self.request.id)

        template = get_template(template_id)
        criteria = template["criteria"]

        storage.update_review_status(review_id, "transcribing")
        review = storage.get_review(review_id)
        signed_url = storage.get_recording_signed_url(review["storage_path"])
        transcript = transcriber.transcribe(signed_url)  # Rev.ai accepts URLs
        speaker_map = reviewer.identify_speakers(transcript)

        storage.update_review_status(review_id, "reviewing")
        review_data = reviewer.review_call(transcript, criteria)

        review["transcript"] = transcript
        review["speaker_map"] = {str(k): v for k, v in speaker_map.items()}
        review["review"] = review_data
        review["framework"] = {
            "template_name": template.get("name", ""),
            "template_id": template_id,
            "criteria": criteria,
        }
        review["status"] = "complete"
        storage.save_review(review)
        storage.delete_recording_from_storage(review["storage_path"])

    except Exception as exc:
        try:
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            storage.update_review_status(review_id, "failed", error_message=str(exc))
            try:
                r = storage.get_review(review_id)
                if r and r.get("storage_path"):
                    storage.delete_recording_from_storage(r["storage_path"])
            except Exception:
                pass
```

### 5. `backend/routers/upload.py`
- Add `template_id: str = Form(...)` parameter
- Read file bytes; call `storage.upload_recording_to_storage(record["id"], file_bytes, file.filename)`
- Set `record["storage_path"] = storage_path` before `save_review(record)`
- Call `process_review_task.delay(record["id"], template_id)` after saving
- Remove disk `save_recording` call
- Return `{"id": record["id"], "status": "pending"}` immediately

### 6. `backend/routers/reviews.py`
- `DELETE /reviews/{id}`: after `delete_review(review_id)`, call `delete_recording_from_storage(review["storage_path"])` if `storage_path` is set
- Remove `POST /reviews/{id}/process` endpoint and `ProcessRequestBody` model
- Remove `transcribe`, `identify_speakers`, `review_call`, `RECORDINGS_DIR` imports
- Rename any `"error"` status references to `"failed"`

### 7. `requirements.txt`
Add: `celery[redis]`

### 8. `.env.example`
Add: `REDIS_URL=redis://localhost:6379/0`

### 9. `frontend/src/pages/UploadPage.jsx`
- In `handleSubmit`: append `template_id` (`activeTemplateId`) to `formData` before `uploadCall`
- Remove `processReview` import and call entirely
- Change `navigate(`/processing/${reviewId}`)` → `navigate('/history')`

### 10. `frontend/src/pages/HistoryPage.jsx`
- After initial fetch, start a 5s polling interval if any review has status `pending`, `transcribing`, or `reviewing`
- Each poll calls `listReviews()` and updates state in place
- Clear interval when all rows are `complete` or `failed`, or on component unmount

### 11. `frontend/src/components/ReviewList.jsx`
For each review row:
- **In-progress** (`pending`/`transcribing`/`reviewing`): replace score with spinner + status label; `pointer-events: none`; no click handler
- **Failed**: red "Failed" badge + delete button (calls existing `onDelete`); no navigation on click
- **Complete**: existing clickable behavior unchanged

### 12. `frontend/src/services/api.js`
- Remove `processReview` function

### 13. `frontend/src/App.jsx`
- Remove `<Route path="/processing/:id" element={<ProcessingPage />} />`
- Remove `ProcessingPage` import

### 14. Delete ProcessingPage
- `frontend/src/pages/ProcessingPage.jsx`
- `frontend/src/pages/ProcessingPage.css`

### 15. `Procfile` (new, repo root)
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
worker: celery -A celery_app worker --loglevel=info
```

### 16. Context docs
- `context/log.md` — add entry for this feature
- `context/map.md` — add `celery_app.py`, `tasks.py`; note `ProcessingPage` removed
- `context/decisions.md` — add async processing decision

---

## Verification

1. Run Supabase SQL migration; create `recordings` bucket
2. Start Redis: `redis-server`
3. Start Celery worker: `py -m celery -A celery_app worker --loglevel=info` (from `backend/`)
4. Start FastAPI: `py -m uvicorn main:app --reload` (from `backend/`)
5. Upload a recording with a template selected → verify immediate redirect to `/history`
6. Verify row appears instantly with `pending` badge + spinner
7. Watch status badge update: `transcribing` → `reviewing` → `complete` without page refresh
8. Click completed row → verify `/results/{id}` loads with full review
9. Test failure: set invalid API key → verify `failed` badge appears after retries
10. Click delete on failed row → verify row removed and Supabase Storage file deleted
11. Verify no regression on existing complete rows (still clickable, score displays correctly)
