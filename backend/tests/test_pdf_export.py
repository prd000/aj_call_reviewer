import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.pdf_export import _score_color, render_review_pdf, review_pdf_filename

_FULL_REVIEW = {
    "id": "test-id",
    "created_at": "2026-06-08T10:00:00Z",
    "status": "complete",
    "metadata": {
        "advisor_name": "Jane Doe",
        "firm": "Acme Financial",
        "prospect_name": "John Smith",
        "call_outcome": "Closed",
    },
    "review": {
        "summary": "A solid overall performance with room for growth.",
        "categories": [
            {"name": "Rapport Building", "score": 8, "max_score": 10, "feedback": "Great rapport."},
            {"name": "Needs Discovery", "score": 3, "max_score": 10, "feedback": "Could improve."},
        ],
    },
    "framework": {
        "template_name": "Rudimentary",
        "criteria": [
            {
                "title": "Rapport Building",
                "description": "...",
                "success_condition": "...",
                "max_score": 10,
            },
            {
                "title": "Needs Discovery",
                "description": "...",
                "success_condition": "...",
                "max_score": 10,
            },
        ],
    },
}

_MINIMAL_REVIEW = {
    "id": "min-id",
    "created_at": "2026-06-08T12:00:00Z",
    "status": "complete",
    "metadata": {},
    "review": {
        "categories": [
            {"name": "Basic Criterion", "score": 5, "max_score": 10, "feedback": "OK."},
        ],
    },
}


def test_render_returns_pdf_bytes():
    result = render_review_pdf(_FULL_REVIEW)
    assert isinstance(result, bytes)
    assert len(result) > 0
    assert result.startswith(b"%PDF")


def test_render_minimal_review_no_exception():
    result = render_review_pdf(_MINIMAL_REVIEW)
    assert result.startswith(b"%PDF")


def test_render_missing_summary_and_outcome():
    review = {
        **_FULL_REVIEW,
        "review": {
            "categories": [
                {"name": "Only Cat", "score": 7, "max_score": 10, "feedback": "Good."},
            ],
        },
        "metadata": {"advisor_name": "Alex"},
    }
    result = render_review_pdf(review)
    assert result.startswith(b"%PDF")


def test_render_no_framework_titles_falls_back_to_category_name():
    review = {
        **_FULL_REVIEW,
        "framework": {},
    }
    result = render_review_pdf(review)
    assert result.startswith(b"%PDF")


def test_filename_ascii_safe():
    name = review_pdf_filename(_FULL_REVIEW)
    assert name.endswith(".pdf")
    assert name.isascii()
    assert "Jane" in name or "Doe" in name or "Smith" in name


def test_filename_unicode_sanitized():
    review = {
        "created_at": "2026-06-08T00:00:00Z",
        "metadata": {
            "advisor_name": "Ángel García",
            "prospect_name": "François",
        },
    }
    name = review_pdf_filename(review)
    assert name.isascii()
    assert name.endswith(".pdf")


def test_filename_empty_metadata():
    review = {"created_at": "2026-06-08T00:00:00Z", "metadata": {}}
    name = review_pdf_filename(review)
    assert name.endswith(".pdf")
    assert name.isascii()


def test_score_color_green():
    assert _score_color(0.7) == "#0ecb81"
    assert _score_color(1.0) == "#0ecb81"
    assert _score_color(0.85) == "#0ecb81"


def test_score_color_yellow():
    assert _score_color(0.4) == "#fcd535"
    assert _score_color(0.5) == "#fcd535"
    assert _score_color(0.699) == "#fcd535"


def test_score_color_red():
    assert _score_color(0.0) == "#f6465d"
    assert _score_color(0.39) == "#f6465d"


def test_render_with_major_focus():
    review = {
        **_FULL_REVIEW,
        "major_focus": {
            "criterion_id": "abc",
            "criterion_title": "Needs Discovery",
            "text": "Ask deeper open-ended questions to uncover three distinct client needs before presenting solutions.",
            "is_auto": True,
        },
    }
    result = render_review_pdf(review)
    assert result.startswith(b"%PDF")


def test_render_without_major_focus_degrades_gracefully():
    review = {**_FULL_REVIEW, "major_focus": None}
    result = render_review_pdf(review)
    assert result.startswith(b"%PDF")
