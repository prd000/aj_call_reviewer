"""Unit tests for reviewer._split_email_text — the plain-text coaching-email
parser that replaced the fragile JSON path (which truncated mid-email when the
model encoded a multi-paragraph body, with quoted prospect words, as JSON)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.reviewer import _split_email_text


def test_subject_prefix_and_body():
    out = _split_email_text(
        "Subject: Quick thoughts on your call with Brian\n\nTyler,\n\nGreat job.\n\nKyle"
    )
    assert out["subject"] == "Quick thoughts on your call with Brian"
    assert out["body"] == "Tyler,\n\nGreat job.\n\nKyle"


def test_subject_case_insensitive_prefix():
    out = _split_email_text("SUBJECT: Hi\n\nBody line")
    assert out["subject"] == "Hi"
    assert out["body"] == "Body line"


def test_no_subject_prefix_first_line_becomes_subject():
    out = _split_email_text("Quick thoughts on Brian\n\nTyler, nice work.")
    assert out["subject"] == "Quick thoughts on Brian"
    assert out["body"] == "Tyler, nice work."


def test_leading_blank_lines_skipped():
    out = _split_email_text("\n\nSubject: Hello\n\nThe body")
    assert out["subject"] == "Hello"
    assert out["body"] == "The body"


def test_code_fences_stripped():
    out = _split_email_text("```\nSubject: Hello\n\nThe body\n```")
    assert out["subject"] == "Hello"
    assert out["body"] == "The body"


def test_body_preserves_inner_quotes_and_paragraphs():
    raw = (
        "Subject: Quick thoughts on your call with Brian\n\n"
        'Tyler, when Brian said "I got wiped out in 2008," you moved on.\n\n'
        "**Next call: stay on the emotional beat.**\n\nKyle"
    )
    out = _split_email_text(raw)
    assert '"I got wiped out in 2008,"' in out["body"]
    assert "**Next call: stay on the emotional beat.**" in out["body"]


def test_subject_only_falls_back_to_full_text_as_body():
    # Degenerate output with no body — keep everything rather than losing content.
    out = _split_email_text("Subject: Only a subject")
    assert out["subject"] == "Only a subject"
    assert out["body"] == "Subject: Only a subject"
