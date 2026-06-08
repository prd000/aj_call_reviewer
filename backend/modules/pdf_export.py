import re
import unicodedata
from datetime import datetime

from fpdf import FPDF, XPos, YPos


def _overall_score(categories: list) -> float | None:
    if not categories:
        return None
    scored = [c for c in categories if isinstance(c.get("score"), (int, float))]
    if not scored:
        return None
    total_score = sum(c["score"] for c in scored)
    total_max = sum(c.get("max_score", 10) for c in scored)
    if total_max == 0:
        return None
    return round((total_score / total_max) * 10, 1)


def _score_color(ratio: float) -> str:
    if ratio >= 0.7:
        return "#0ecb81"
    if ratio >= 0.4:
        return "#fcd535"
    return "#f6465d"


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _t(value) -> str:
    """Latin-1 safe text for fpdf2 core fonts; replaces unsupported characters."""
    if value is None:
        return ""
    return str(value).encode("latin-1", errors="replace").decode("latin-1")


def _format_date(created_at: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except Exception:
        return created_at or ""


# Convenience aliases for the modern fpdf2 cursor-positioning API.
_NL = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}   # move to next line
_CR = {"new_x": XPos.RIGHT,   "new_y": YPos.TOP}     # stay on same line


def _section_header(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(24, 26, 32)
    pdf.set_draw_color(234, 236, 239)
    pdf.cell(0, 8, _t(title), border="B", **_NL)
    pdf.ln(3)
    pdf.set_draw_color(0, 0, 0)


def render_review_pdf(review: dict) -> bytes:
    metadata = review.get("metadata", {})
    review_data = review.get("review") or {}
    categories = review_data.get("categories", [])
    framework = review.get("framework") or {}
    framework_criteria = framework.get("criteria", [])
    summary = review_data.get("summary", "")
    overall = _overall_score(categories)

    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pw = pdf.w - pdf.l_margin - pdf.r_margin  # usable page width

    # --- HEADER ---
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(24, 26, 32)
    pdf.cell(0, 10, "Call Review", **_NL)
    # Yellow divider line
    pdf.set_fill_color(252, 213, 53)
    pdf.rect(pdf.l_margin, pdf.get_y(), pw, 2, "F")
    pdf.ln(6)

    # Metadata rows
    meta_rows = []
    if metadata.get("advisor_name"):
        meta_rows.append(("Advisor", metadata["advisor_name"]))
    if metadata.get("firm"):
        meta_rows.append(("Firm", metadata["firm"]))
    if metadata.get("prospect_name"):
        meta_rows.append(("Prospect", metadata["prospect_name"]))
    if review.get("created_at"):
        meta_rows.append(("Date", _format_date(review["created_at"])))
    if metadata.get("call_outcome"):
        meta_rows.append(("Outcome", metadata["call_outcome"]))

    lw = 32  # label column width
    for label, value in meta_rows:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(112, 122, 138)
        pdf.cell(lw, 6, _t(label), **_CR)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(24, 26, 32)
        pdf.cell(pw - lw, 6, _t(value), **_NL)

    pdf.ln(8)

    # --- OVERALL SCORE ---
    if overall is not None:
        r, g, b = _hex_to_rgb(_score_color(overall / 10))
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(112, 122, 138)
        pdf.cell(0, 6, "OVERALL SCORE", align="C", **_NL)
        pdf.set_font("Helvetica", "B", 36)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 18, f"{overall}/10", align="C", **_NL)
        pdf.ln(6)

    # --- SUMMARY ---
    if summary:
        _section_header(pdf, "Summary")
        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(24, 26, 32)
        pdf.multi_cell(0, 5, _t(summary))
        pdf.ln(6)

    # --- CATEGORY SCORES ---
    if categories:
        _section_header(pdf, "Category Scores")

        for i, cat in enumerate(categories):
            if i < len(framework_criteria):
                title = framework_criteria[i].get("title") or cat.get("name", "")
            else:
                title = cat.get("name", "")

            score = cat.get("score")
            max_score = cat.get("max_score", 10)
            feedback = cat.get("feedback", "")

            # Title
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(24, 26, 32)
            pdf.multi_cell(0, 6, _t(title))

            # Score label
            score_display = f"{score}/{max_score}" if score is not None else "N/A"
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(112, 122, 138)
            pdf.cell(0, 5, _t(score_display), **_NL)
            pdf.ln(1)

            # Score bar
            if score is not None and max_score:
                ratio = max(0.0, min(1.0, score / max_score))
                br, bg, bb = _hex_to_rgb(_score_color(ratio))
                bar_y = pdf.get_y()
                # Gray track
                pdf.set_fill_color(234, 236, 239)
                pdf.rect(pdf.l_margin, bar_y, pw, 5, "F")
                # Colored fill
                if ratio > 0:
                    pdf.set_fill_color(br, bg, bb)
                    pdf.rect(pdf.l_margin, bar_y, pw * ratio, 5, "F")
                pdf.ln(7)

            # Feedback
            if feedback:
                pdf.set_font("Helvetica", "", 11)
                pdf.set_text_color(24, 26, 32)
                pdf.multi_cell(0, 5, _t(feedback))

            pdf.ln(6)
            # Hairline separator between categories
            if i < len(categories) - 1:
                pdf.set_draw_color(230, 230, 230)
                y_line = pdf.get_y() - 3
                pdf.line(pdf.l_margin, y_line, pdf.l_margin + pw, y_line)
                pdf.set_draw_color(0, 0, 0)

    return bytes(pdf.output())


def review_pdf_filename(review: dict) -> str:
    metadata = review.get("metadata", {})
    advisor = metadata.get("advisor_name", "") or ""
    prospect = metadata.get("prospect_name", "") or ""
    created = review.get("created_at", "") or ""

    date_part = ""
    if created:
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            date_part = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    def sanitize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s)
        s = s.encode("ascii", "ignore").decode("ascii")
        s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
        return s[:30]

    parts = [p for p in [sanitize(advisor), sanitize(prospect), date_part] if p]
    name = "-".join(parts) if parts else "Review"
    return f"Call-Review-{name}.pdf"
