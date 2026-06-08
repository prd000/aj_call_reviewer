import html
import io
import re
import unicodedata
from datetime import datetime

from xhtml2pdf import pisa


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


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _format_date(created_at: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except Exception:
        return created_at or ""


def _build_html(review: dict) -> str:
    metadata = review.get("metadata", {})
    review_data = review.get("review") or {}
    categories = review_data.get("categories", [])
    framework = review.get("framework") or {}
    framework_criteria = framework.get("criteria", [])
    summary = review_data.get("summary", "")

    overall = _overall_score(categories)
    overall_color = _score_color(overall / 10) if overall is not None else "#707a8a"
    overall_display = f"{overall}/10" if overall is not None else "—"

    # Metadata table rows
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

    meta_html = "".join(
        f'<tr><td class="label">{_esc(label)}</td><td>{_esc(value)}</td></tr>'
        for label, value in meta_rows
    )

    summary_html = ""
    if summary:
        summary_html = f"""
        <div class="section">
          <h2>Summary</h2>
          <p class="summary-text">{_esc(summary)}</p>
        </div>"""

    # Per-category sections
    cat_items = []
    for i, cat in enumerate(categories):
        # Prefer the framework criterion title; fall back to the stored category name
        if i < len(framework_criteria):
            title = framework_criteria[i].get("title") or cat.get("name", "")
        else:
            title = cat.get("name", "")

        score = cat.get("score")
        max_score = cat.get("max_score", 10)
        feedback = cat.get("feedback", "")

        if score is not None and max_score:
            ratio = score / max_score
            bar_color = _score_color(ratio)
            bar_pct = max(0, min(100, round(ratio * 100)))
        else:
            bar_color = "#707a8a"
            bar_pct = 0

        score_display = f"{score}/{max_score}" if score is not None else "—"

        # Use a two-cell table for the bar so xhtml2pdf renders it reliably
        if bar_pct == 0:
            bar_cells = '<td style="height:8px; background-color:#eaecef;"></td>'
        elif bar_pct == 100:
            bar_cells = f'<td style="height:8px; background-color:{bar_color};"></td>'
        else:
            bar_cells = (
                f'<td style="height:8px; width:{bar_pct}%; background-color:{bar_color};"></td>'
                f'<td style="height:8px; background-color:#eaecef;"></td>'
            )

        cat_items.append(f"""
        <div class="category">
          <div class="cat-title">{_esc(title)}</div>
          <div class="cat-score">{_esc(score_display)}</div>
          <table style="width:100%; border-collapse:collapse; margin-bottom:6px;"
                 cellspacing="0" cellpadding="0">
            <tr>{bar_cells}</tr>
          </table>
          <div class="cat-feedback">{_esc(feedback)}</div>
        </div>""")

    categories_html = ""
    if cat_items:
        categories_html = f"""
        <div class="section">
          <h2>Category Scores</h2>
          {"".join(cat_items)}
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<style>
  @page {{ margin: 1.5cm 2cm; }}
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: 13px; color: #181a20; margin: 0; padding: 0; }}
  h1 {{ font-size: 22px; font-weight: bold; color: #181a20; margin: 0 0 12px 0; }}
  h2 {{ font-size: 14px; font-weight: bold; color: #181a20; margin: 0 0 8px 0;
       border-bottom: 1px solid #eaecef; padding-bottom: 4px; }}
  .header-band {{ border-bottom: 3px solid #fcd535; padding-bottom: 14px; margin-bottom: 20px; }}
  .meta-table {{ width: 100%; }}
  .meta-table td {{ padding: 2px 0; font-size: 12px; }}
  .label {{ color: #707a8a; font-weight: bold; width: 110px; }}
  .score-card {{ text-align: center; padding: 12px; margin-bottom: 20px;
                border: 1px solid #eaecef; }}
  .score-label-text {{ font-size: 11px; color: #707a8a; }}
  .score-number {{ font-size: 40px; font-weight: bold; }}
  .section {{ margin-bottom: 20px; }}
  .summary-text {{ font-size: 13px; color: #181a20; }}
  .category {{ margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid #f5f5f5; }}
  .cat-title {{ font-size: 13px; font-weight: bold; margin-bottom: 2px; }}
  .cat-score {{ font-size: 12px; color: #707a8a; margin-bottom: 4px; }}
  .cat-feedback {{ font-size: 12px; color: #181a20; margin-top: 4px; }}
</style>
</head>
<body>
  <div class="header-band">
    <h1>Call Review</h1>
    <table class="meta-table" cellspacing="0" cellpadding="0">
      {meta_html}
    </table>
  </div>

  <div class="score-card">
    <div class="score-label-text">OVERALL SCORE</div>
    <div class="score-number" style="color:{overall_color};">{_esc(overall_display)}</div>
  </div>

  {summary_html}

  {categories_html}
</body>
</html>"""


def render_review_pdf(review: dict) -> bytes:
    html_content = _build_html(review)
    buf = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=buf)
    if pisa_status.err:
        raise RuntimeError(f"PDF generation failed with {pisa_status.err} error(s)")
    return buf.getvalue()


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
