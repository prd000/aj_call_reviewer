import re
import unicodedata
from datetime import datetime

from fpdf import FPDF, XPos, YPos


# ---------------------------------------------------------------------------
# Design tokens (light variant of the Binance-inspired system in context/DESIGN.md).
# The PDF mirrors the in-app call review screen using the light-mode palette so the
# document stays printer-friendly while matching the screen's layout and accents.
# ---------------------------------------------------------------------------
WHITE = (255, 255, 255)            # canvas-light / card surface
SURFACE_ELEVATED = (245, 245, 245)  # surface-strong-light (#f5f5f5) — nested boxes
HAIRLINE = (234, 236, 239)          # hairline-on-light (#eaecef) — borders / bar track
INK = (24, 26, 32)                  # ink / body-on-light (#181a20)
MUTED = (112, 122, 138)             # muted labels (#707a8a)
YELLOW = (252, 213, 53)             # primary (#fcd535) — header divider / accents

# Radii (px -> ~mm at fpdf's default mm units) and card padding.
RADIUS_CARD = 2.5   # rounded-lg (8px)
RADIUS_XL = 3.5     # rounded-xl (12px) — summary card container
CARD_PAD = 6.0      # spacing-lg (24px) card padding

# Convenience aliases for the modern fpdf2 cursor-positioning API.
_NL = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}   # move to next line
_CR = {"new_x": XPos.RIGHT,   "new_y": YPos.TOP}     # stay on same line


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


# Common Unicode punctuation -> Latin-1/ASCII equivalents so fpdf2's core
# Helvetica font renders them as readable text instead of "?".
_PUNCT_MAP = {
    "—": "-",    # em dash
    "–": "-",    # en dash
    "‒": "-",    # figure dash
    "―": "-",    # horizontal bar
    "‘": "'",    # left single quote
    "’": "'",    # right single quote / apostrophe
    "‚": "'",    # single low-9 quote
    "“": '"',    # left double quote
    "”": '"',    # right double quote
    "„": '"',    # double low-9 quote
    "…": "...",  # ellipsis
    "•": "*",    # bullet
    " ": " ",    # non-breaking space
    "​": "",     # zero-width space
    "→": "->",   # right arrow (occasionally appears in AI text)
}
_PUNCT_TABLE = str.maketrans(_PUNCT_MAP)


def _t(value) -> str:
    """Latin-1 safe text for fpdf2 core fonts.

    Transliterates common Unicode punctuation (em/en dashes, curly quotes,
    ellipsis, bullets) to ASCII so they render correctly instead of "?".
    Anything still outside Latin-1 is dropped via NFKD then replaced.
    """
    if value is None:
        return ""
    text = str(value).translate(_PUNCT_TABLE)
    # NFKC folds compatibility chars (ligatures, full-width forms) while keeping
    # accents in their precomposed Latin-1 form (e.g. "é" stays a single char).
    # Encoding to latin-1 with replace is the final safety net for anything left.
    text = unicodedata.normalize("NFKC", text)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _format_date(created_at: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except Exception:
        return created_at or ""


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def _rounded_box(pdf, x, y, w, h, fill_rgb, border_rgb=HAIRLINE, radius=RADIUS_CARD):
    """Draw a rounded, filled, hairline-bordered rectangle (a card surface)."""
    pdf.set_fill_color(*fill_rgb)
    pdf.set_draw_color(*border_rgb)
    pdf.set_line_width(0.2)
    pdf.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=radius)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)


def _pill_bar(pdf, x, y, w, h, ratio, color_rgb):
    """Pill-shaped progress bar: gray track + color-coded fill (mirrors ScoreCard)."""
    radius = h / 2
    pdf.set_draw_color(*HAIRLINE)
    pdf.set_fill_color(*HAIRLINE)
    pdf.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=radius)
    ratio = max(0.0, min(1.0, ratio))
    if ratio > 0:
        fill_w = max(w * ratio, h)  # keep the pill readable for tiny ratios
        pdf.set_draw_color(*color_rgb)
        pdf.set_fill_color(*color_rgb)
        pdf.rect(x, y, fill_w, h, style="DF", round_corners=True, corner_radius=radius)
    pdf.set_draw_color(0, 0, 0)


def _draw_card(pdf, content_fn, *, pad=CARD_PAD, radius=RADIUS_CARD, fill=WHITE):
    """
    Render a card whose height is unknown until its content is laid out.

    Measures `content_fn` via offset_rendering, paginates so the card never splits
    across pages, draws the rounded background box, then renders the content on top.
    `content_fn(pdf, x, w)` lays out content top-down from the current cursor.
    """
    pw = pdf.w - pdf.l_margin - pdf.r_margin
    x = pdf.l_margin
    inner_x = x + pad
    inner_w = pw - 2 * pad

    prev_apb = pdf.auto_page_break
    pdf.set_auto_page_break(False)

    start_y = pdf.get_y()
    with pdf.offset_rendering() as rec:
        rec.set_xy(inner_x, start_y + pad)
        content_fn(rec, inner_x, inner_w)
        content_h = rec.get_y() - (start_y + pad)
    card_h = content_h + 2 * pad

    # Page-break before the card if it would overflow the page.
    if start_y + card_h > pdf.h - pdf.b_margin:
        pdf.set_auto_page_break(prev_apb)
        pdf.add_page()
        pdf.set_auto_page_break(False)
        start_y = pdf.get_y()

    _rounded_box(pdf, x, start_y, pw, card_h, fill, HAIRLINE, radius)

    pdf.set_xy(inner_x, start_y + pad)
    content_fn(pdf, inner_x, inner_w)

    pdf.set_xy(pdf.l_margin, start_y + card_h)
    pdf.set_auto_page_break(prev_apb)


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
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, "Call Review", **_NL)
    # Yellow divider line
    pdf.set_fill_color(*YELLOW)
    pdf.rect(pdf.l_margin, pdf.get_y(), pw, 2, "F")
    pdf.ln(8)

    # --- SUMMARY CARD (metadata + overall score + summary) ---
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

    def _summary_card(p, x, w):
        # Metadata: 2-column grid, label (muted uppercase) above value (ink).
        col_gap = 6.0
        col_w = (w - col_gap) / 2
        for i in range(0, len(meta_rows), 2):
            row_y = p.get_y()
            for j in (0, 1):
                idx = i + j
                if idx >= len(meta_rows):
                    break
                label, value = meta_rows[idx]
                cx = x + j * (col_w + col_gap)
                p.set_xy(cx, row_y)
                p.set_font("Helvetica", "B", 8)
                p.set_text_color(*MUTED)
                p.cell(col_w, 4, _t(label.upper()))
                p.set_xy(cx, row_y + 4)
                p.set_font("Helvetica", "", 11)
                p.set_text_color(*INK)
                p.cell(col_w, 5, _t(value))
            p.set_xy(x, row_y + 4 + 5 + 5)  # label + value + row gap

        # Overall score: elevated box, muted label left + big color-coded number right.
        if overall is not None:
            box_h = 16.0
            box_y = p.get_y()
            _rounded_box(p, x, box_y, w, box_h, SURFACE_ELEVATED, SURFACE_ELEVATED, RADIUS_CARD)
            p.set_xy(x + 4, box_y)
            p.set_font("Helvetica", "B", 9)
            p.set_text_color(*MUTED)
            p.cell(w / 2, box_h, "OVERALL SCORE")
            r, g, b = _hex_to_rgb(_score_color(overall / 10))
            p.set_xy(x, box_y)
            p.set_font("Helvetica", "B", 26)
            p.set_text_color(r, g, b)
            p.cell(w - 4, box_h, f"{overall}/10", align="R")
            p.set_xy(x, box_y + box_h + 6)

        # Summary text.
        if summary:
            p.set_x(x)
            p.set_font("Helvetica", "B", 8)
            p.set_text_color(*MUTED)
            p.cell(w, 4, "SUMMARY", **_NL)
            p.set_x(x)
            p.set_font("Helvetica", "", 11)
            p.set_text_color(*INK)
            p.multi_cell(w, 5, _t(summary), align="L", **_NL)

        # Major Focus block (directly after summary).
        major_focus = review.get("major_focus") or {}
        focus_text = major_focus.get("text", "")
        if focus_text:
            p.ln(3)
            p.set_x(x)
            focus_criterion = major_focus.get("criterion_title", "")
            focus_label = "MAJOR FOCUS"
            if focus_criterion:
                focus_label = f"MAJOR FOCUS - {focus_criterion.upper()}"
            p.set_font("Helvetica", "B", 8)
            p.set_text_color(*MUTED)
            p.cell(w, 4, _t(focus_label), **_NL)
            p.set_x(x)
            p.set_font("Helvetica", "", 11)
            p.set_text_color(*INK)
            p.multi_cell(w, 5, _t(focus_text), align="L", **_NL)

    if meta_rows or overall is not None or summary:
        _draw_card(pdf, _summary_card, radius=RADIUS_XL)
        pdf.ln(6)

    # --- CATEGORY SCORES ---
    if categories:
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*INK)
        pdf.cell(0, 8, "Category Scores", **_NL)
        pdf.ln(2)

        for i, cat in enumerate(categories):
            if i < len(framework_criteria):
                title = framework_criteria[i].get("title") or cat.get("name", "")
            else:
                title = cat.get("name", "")

            score = cat.get("score")
            max_score = cat.get("max_score", 10)
            feedback = cat.get("feedback", "")
            score_display = f"{score}/{max_score}" if score is not None else "N/A"
            ratio = (score / max_score) if (score is not None and max_score) else None

            def _score_card(p, x, w, title=title, score=score, feedback=feedback,
                            score_display=score_display, ratio=ratio):
                # Header row: name (left) + color-coded score badge (right).
                row_y = p.get_y()
                p.set_font("Helvetica", "B", 16)
                badge_w = p.get_string_width(_t(score_display)) + 1
                name_w = w - badge_w - 3
                p.set_xy(x, row_y)
                p.set_font("Helvetica", "B", 11)
                p.set_text_color(*INK)
                name_h = p.multi_cell(name_w, 5, _t(title), align="L", dry_run=True, output="HEIGHT")
                row_h = max(name_h, 6.5)
                p.set_xy(x, row_y)
                p.multi_cell(name_w, 5, _t(title), align="L", new_x=XPos.LMARGIN, new_y=YPos.TOP)
                if ratio is not None:
                    r, g, b = _hex_to_rgb(_score_color(ratio))
                else:
                    r, g, b = MUTED
                p.set_xy(x + w - badge_w, row_y)
                p.set_font("Helvetica", "B", 16)
                p.set_text_color(r, g, b)
                p.cell(badge_w, 6.5, _t(score_display), align="R")
                p.set_xy(x, row_y + row_h + 2.5)

                # Pill progress bar.
                if ratio is not None:
                    bar_y = p.get_y()
                    p.set_xy(x, bar_y)
                    _pill_bar(p, x, bar_y, w, 1.6, ratio, (r, g, b))
                    p.set_xy(x, bar_y + 1.6 + 3)

                # Feedback.
                if feedback:
                    p.set_x(x)
                    p.set_font("Helvetica", "", 10)
                    p.set_text_color(*INK)
                    p.multi_cell(w, 4.5, _t(feedback), align="L", **_NL)
                else:
                    # trim trailing gap when there's no feedback
                    p.set_xy(x, p.get_y() - 1)

            _draw_card(pdf, _score_card, pad=5.0)
            pdf.ln(4)

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
