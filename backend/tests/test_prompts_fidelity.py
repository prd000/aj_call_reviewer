"""
Format-contract tests: each prompt file must satisfy its API contract — the
right placeholders are substituted, the values appear in the output, and no
unfilled single-brace identifiers remain. Tests that previously used byte-
equality comparisons against old hardcoded constants have been converted here
because the prompts have evolved past those snapshots.
"""
import re
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so 'prompts' resolves correctly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from prompts import load_prompt


def test_speaker_id_system_raw():
    # speaker_id.system takes no format args. Calling .format() with no args
    # verifies there are no unfilled single-brace placeholders (double braces
    # {{ / }} are literal JSON examples and are fine).
    text = load_prompt("speaker_id.system")
    assert text
    text.format()  # raises KeyError on any unfilled {placeholder}
    assert "advisor" in text.lower()
    assert "prospect" in text.lower()


def test_speaker_id_user_formatted():
    sample = "line1\nline2"
    from_file = load_prompt("speaker_id.user").format(sample_text=sample)
    original = f"Transcript sample:\n{sample}"
    assert from_file == original


def test_criterion_system_formatted():
    # criterion.system takes {description}, {success_condition}, {max_score}.
    # After formatting, all three values appear and no single-brace identifier
    # placeholders remain (double-brace JSON examples in the prompt become
    # literal braces, which is expected).
    args = dict(description="Test criterion", success_condition="Done when X", max_score=7)
    out = load_prompt("criterion.system").format(**args)
    assert "Test criterion" in out
    assert "Done when X" in out
    assert "7" in out
    assert not re.search(r"\{[a-z_]+\}", out), "Unfilled placeholder found after format()"


def test_criterion_user_formatted():
    t = "some transcript"
    from_file = load_prompt("criterion.user").format(transcript=t)
    original = f"Transcript:\n{t}"
    assert from_file == original


def test_chat_system_formatted():
    # The chat system prompt is actively maintained (no longer byte-identical to
    # the original constant), so this guards the format CONTRACT instead: every
    # placeholder must be supplied, each source section is substituted in, and no
    # unfilled braces leak through. Keep these kwargs in sync with
    # reviewer.chat_about_transcript's load_prompt("chat.system").format(...) call.
    out = load_prompt("chat.system").format(
        framework_section="FRAMEWORK_BLOCK",
        review_section="REVIEW_BLOCK",
        transcript="TRANSCRIPT_BLOCK",
    )
    assert "FRAMEWORK_BLOCK" in out
    assert "REVIEW_BLOCK" in out
    assert "TRANSCRIPT_BLOCK" in out
    # No leftover unfilled placeholders.
    assert "{" not in out and "}" not in out


def test_summary_system_raw():
    # summary.system takes no format args. Verify it loads cleanly with no
    # unfilled placeholders and mentions "summary" as a key domain term.
    text = load_prompt("summary.system")
    assert text
    text.format()  # raises KeyError on any unfilled {placeholder}
    assert "summary" in text.lower()


def test_summary_user_formatted():
    t = "transcript text"
    s = "- cat: 8/10"
    from_file = load_prompt("summary.user").format(transcript=t, scores_text=s)
    original = f"Transcript:\n{t}\n\nCategory Scores:\n{s}"
    assert from_file == original


def test_coaching_email_system_raw():
    # coaching_email.system takes no format args (used raw). .format() with no
    # args verifies there are no unfilled single-brace placeholders, and the
    # prompt must keep its JSON output contract and core domain terms.
    text = load_prompt("coaching_email.system")
    assert text
    text.format()  # raises KeyError on any unfilled {placeholder}
    assert "email" in text.lower()
    assert "subject" in text.lower() and "body" in text.lower()


def test_coaching_email_user_formatted():
    # Guards the format CONTRACT: every placeholder must be supplied, each value
    # is substituted in, and no unfilled braces leak through. Keep these kwargs in
    # sync with reviewer.generate_coaching_email's
    # load_prompt("coaching_email.user").format(...) call.
    out = load_prompt("coaching_email.user").format(
        sign_off_name="Kyle",
        advisor_name="Jordan",
        prospect_name="Diana",
        call_outcome="follow_up_scheduled",
        review_section="REVIEW_BLOCK\n\n",
        transcript="TRANSCRIPT_BLOCK",
    )
    assert "Kyle" in out
    assert "Jordan" in out
    assert "Diana" in out
    assert "follow_up_scheduled" in out
    assert "REVIEW_BLOCK" in out
    assert "TRANSCRIPT_BLOCK" in out
    assert not re.search(r"\{[a-z_]+\}", out), "Unfilled placeholder found after format()"
