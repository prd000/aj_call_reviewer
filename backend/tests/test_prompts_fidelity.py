"""
Golden byte-equality test: the prompt files must reproduce the exact strings
that were previously hardcoded as constants in reviewer.py.
"""
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so 'prompts' resolves correctly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from prompts import load_prompt

# --- originals captured verbatim from reviewer.py before refactor ---

_SPEAKER_ID_PROMPT = (
    "You are analyzing a financial advisor sales call transcript. "
    "Based on the content of these opening segments, identify which speaker number is the "
    "financial advisor/salesperson and which is the prospect/client. "
    "Speakers are identified by their 0-indexed speaker number. "
    "Respond with a JSON object in this exact format:\n"
    '{{"advisor": <speaker_number>, "prospect": <speaker_number>}}\n\n'
    "Do not include anything outside the JSON object."
)

_CRITERION_PROMPT_TEMPLATE = (
    "You are a call reviewer for financial advisors. Your current job is to analyze "
    "this call recording based on the following criteria:\n\n"
    "Criteria: {description}\n\n"
    "You know this has been successfully accomplished when: {success_condition}\n\n"
    "Respond with a JSON object in this exact format:\n"
    '{{"score": <integer 1-{max_score}>, "feedback": "<2-3 sentences of coaching feedback>"}}\n\n'
    "Do not include anything outside the JSON object."
)

_CHAT_SYSTEM_PROMPT_TEMPLATE = (
    "You are a call review assistant. You have been given a complete transcript of a "
    "financial advisor's sales call{framework_clause}.\n\n"
    "Your sole job is to answer questions about THIS call. You must:\n"
    "- Base all factual claims about what was said ONLY on the transcript. Do not use "
    "outside knowledge.\n"
    "- If a question cannot be answered from the transcript or the review framework, "
    'reply exactly: "I can only answer questions about this call\'s transcript."\n'
    "- Cite EVERY relevant moment with its timestamp and a short verbatim quote, "
    'e.g. 00:01:23 — "the advisor said..."\n'
    "- Timestamps must exactly match a bracketed line in the transcript below.\n"
    "- You may offer light interpretation ONLY when it is directly anchored to a "
    "cited, timestamped quote.\n"
    "- Refer to speakers by their role label (Advisor, Prospect, etc.) as shown in "
    "the transcript.\n"
    "- When a question relates to how the call was evaluated, use the review framework "
    "below for context, but still cite transcript evidence for any claim about what "
    "actually happened on the call.\n\n"
    "{framework_section}"
    "Transcript:\n{transcript}"
)

_SUMMARY_PROMPT = (
    "You are a sales coach for financial advisors. "
    "Given the following call transcript and category scores, "
    "write a 3-4 sentence overall summary of the advisor's performance. "
    "Be specific, constructive, and actionable. "
    "Return only the summary text, no JSON."
)


def test_speaker_id_system_raw():
    assert load_prompt("speaker_id.system") == _SPEAKER_ID_PROMPT


def test_speaker_id_user_formatted():
    sample = "line1\nline2"
    from_file = load_prompt("speaker_id.user").format(sample_text=sample)
    original = f"Transcript sample:\n{sample}"
    assert from_file == original


def test_criterion_system_formatted():
    args = dict(description="D", success_condition="S", max_score=10)
    from_file = load_prompt("criterion.system").format(**args)
    original = _CRITERION_PROMPT_TEMPLATE.format(**args)
    assert from_file == original


def test_criterion_user_formatted():
    t = "some transcript"
    from_file = load_prompt("criterion.user").format(transcript=t)
    original = f"Transcript:\n{t}"
    assert from_file == original


def test_chat_system_formatted():
    args = dict(framework_clause="", framework_section="", transcript="T")
    from_file = load_prompt("chat.system").format(**args)
    original = _CHAT_SYSTEM_PROMPT_TEMPLATE.format(**args)
    assert from_file == original


def test_summary_system_raw():
    assert load_prompt("summary.system") == _SUMMARY_PROMPT


def test_summary_user_formatted():
    t = "transcript text"
    s = "- cat: 8/10"
    from_file = load_prompt("summary.user").format(transcript=t, scores_text=s)
    original = f"Transcript:\n{t}\n\nCategory Scores:\n{s}"
    assert from_file == original
