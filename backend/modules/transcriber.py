import os
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 5
_POLL_MAX_ATTEMPTS = 360  # 30-minute ceiling

STUB_TRANSCRIPT = [
    {"timestamp": "00:00:05", "text": "Hi there, thanks for making time today. How are you doing?", "speaker": 0},
    {"timestamp": "00:00:12", "text": "I'm doing well, thank you. I appreciate you reaching out.", "speaker": 1},
    {"timestamp": "00:00:18", "text": "Of course. I wanted to talk with you today about your retirement planning goals and see if we can be of service.", "speaker": 0},
    {"timestamp": "00:00:30", "text": "That sounds good. I've been thinking about this for a while actually.", "speaker": 1},
    {"timestamp": "00:00:38", "text": "Great. Can you tell me a bit about where you are today? Do you have any existing retirement accounts?", "speaker": 0},
    {"timestamp": "00:00:50", "text": "Yes, I have a 401k from my current employer and an old IRA from a previous job.", "speaker": 1},
    {"timestamp": "00:01:02", "text": "That's a solid starting point. Do you have a sense of what your target retirement age is?", "speaker": 0},
    {"timestamp": "00:01:14", "text": "Ideally somewhere around 62, maybe 65 at the latest.", "speaker": 1},
    {"timestamp": "00:01:22", "text": "That gives us a good runway. One of the things I'd like to explore with you is a comprehensive income strategy that bridges any gap between retirement and Social Security.", "speaker": 0},
    {"timestamp": "00:01:40", "text": "That's actually something I've been worried about. I don't fully understand how Social Security will fit in.", "speaker": 1},
    {"timestamp": "00:01:52", "text": "That's a very common concern and one we can absolutely address. We have a planning process specifically for that.", "speaker": 0},
    {"timestamp": "00:02:05", "text": "That would be reassuring to understand better.", "speaker": 1},
    {"timestamp": "00:02:12", "text": "Absolutely. Based on what you've shared, I think there are a few options we should walk through. Can we schedule a follow-up for next week?", "speaker": 0},
    {"timestamp": "00:02:25", "text": "Yes, that works for me. Thursday afternoon would be best.", "speaker": 1},
    {"timestamp": "00:02:32", "text": "Perfect. I'll send a calendar invite. Looking forward to diving deeper with you.", "speaker": 0},
]


def _seconds_to_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _parse_monologues(monologues) -> list[dict]:
    segments = []
    for monologue in monologues:
        start_ts = next(
            (e.timestamp for e in monologue.elements
             if e.type_ == "text" and e.timestamp is not None),
            None,
        )
        if start_ts is None:
            continue
        text = "".join(e.value for e in monologue.elements).strip()
        if not text:
            continue
        segments.append({
            "timestamp": _seconds_to_timestamp(start_ts),
            "text": text,
            "speaker": monologue.speaker,
        })
    return segments


def transcribe(source: Path | str) -> list[dict]:
    """
    Transcribe an audio/video file using the Rev.ai API with speaker diarization.

    Accepts either a local file Path or an HTTP/HTTPS URL (e.g. a Supabase signed URL).
    Returns a list of dicts with keys: 'timestamp' (HH:MM:SS), 'text', and
    'speaker' (int, 0-indexed). One segment is produced per speaker turn.

    If REV_AI_ACCESS_TOKEN is not set in the environment, returns stub transcript
    data so the application remains functional during development.
    """
    access_token = os.environ.get("REV_AI_ACCESS_TOKEN", "").strip()

    if not access_token:
        logger.warning(
            "REV_AI_ACCESS_TOKEN is not set. Returning stub transcript for development."
        )
        return STUB_TRANSCRIPT

    try:
        from rev_ai import apiclient
        from rev_ai.models import JobStatus

        client = apiclient.RevAiAPIClient(access_token)

        is_url = isinstance(source, str) and source.startswith(("http://", "https://"))
        if is_url:
            logger.info("Submitting transcription job to Rev.ai for URL (first 60 chars): %s", str(source)[:60])
            job = client.submit_job_url(str(source))
        else:
            logger.info("Submitting transcription job to Rev.ai for file: %s", source)
            job = client.submit_job_local_file(str(source))
        job_id = job.id
        logger.info("Rev.ai job submitted. Job ID: %s", job_id)

        for attempt in range(1, _POLL_MAX_ATTEMPTS + 1):
            time.sleep(_POLL_INTERVAL_SECONDS)
            job = client.get_job_details(job_id)

            if job.status == JobStatus.TRANSCRIBED:
                logger.info("Rev.ai job %s completed after %d poll(s).", job_id, attempt)
                break
            elif job.status == JobStatus.FAILED:
                failure_detail = getattr(job, "failure_detail", "unknown")
                raise RuntimeError(
                    f"Rev.ai transcription job {job_id} failed: {failure_detail}"
                )
            else:
                logger.debug(
                    "Rev.ai job %s status: %s (poll %d/%d)",
                    job_id, job.status, attempt, _POLL_MAX_ATTEMPTS,
                )
        else:
            raise TimeoutError(
                f"Rev.ai job {job_id} did not complete within "
                f"{_POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SECONDS} seconds."
            )

        transcript_obj = client.get_transcript_object(job_id)
        segments = _parse_monologues(transcript_obj.monologues)

        logger.info(
            "Transcription complete. %d segment(s) parsed from Rev.ai job %s.",
            len(segments), job_id,
        )
        return segments

    except Exception as exc:
        logger.error("Transcription failed: %s", exc, exc_info=True)
        raise
