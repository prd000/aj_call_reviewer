#!/usr/bin/env python3
"""Call Reviewer CLI — drive the app from a Claude chat via its HTTP API.

Standard library only (urllib), so it runs in any sandbox with no installs.
Auth is an API key (``ak_live_...``) sent as the ``X-API-Key`` header; the key
inherits the role of the user it was minted for. Commands: review, search, tag,
analyze. Each prints a single-line JSON result (prefixed ``RESULT: ``) last.
"""
import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

SUPPORTED_EXTS = {".mp3", ".mp4", ".m4a", ".wav"}
POLL_INTERVAL_SECONDS = 5
DEFAULT_POLL_TIMEOUT_SECONDS = 1800  # transcription can take a while
HISTORY_CHAT_MAX_IDS = 200


# ── HTTP plumbing ──────────────────────────────────────────────────────────────


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def _base_url(args):
    url = args.api_url or os.environ.get("CALL_REVIEWER_API_URL", "")
    if not url:
        raise SystemExit("Missing API URL: set CALL_REVIEWER_API_URL or pass --api-url")
    return url.rstrip("/")


def _api_key(args):
    key = args.api_key or os.environ.get("CALL_REVIEWER_API_KEY", "")
    if not key:
        raise SystemExit("Missing API key: set CALL_REVIEWER_API_KEY or pass --api-key")
    return key


def _request(args, method, path, *, json_body=None, body=None, content_type=None, raw=False):
    """Perform an HTTP request. Returns parsed JSON, or (bytes, headers) when raw."""
    url = _base_url(args) + path
    headers = {"X-API-Key": _api_key(args), "Accept": "*/*"}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif body is not None:
        data = body
        if content_type:
            headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
            if raw:
                return payload, dict(resp.headers)
            if not payload:
                return None
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except Exception:
            pass
        raise ApiError(e.code, detail)
    except urllib.error.URLError as e:
        raise ApiError(0, f"connection failed: {e.reason}")


def _encode_multipart(fields, file_field, filename, file_bytes, file_content_type):
    """Build a multipart/form-data body. ``fields`` values that are None are skipped."""
    boundary = "----CallReviewer" + uuid.uuid4().hex
    bnd = boundary.encode()
    crlf = b"\r\n"
    parts = []
    for name, value in fields.items():
        if value is None:
            continue
        parts.append(b"--" + bnd)
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
        parts.append(b"")
        parts.append(str(value).encode("utf-8"))
    parts.append(b"--" + bnd)
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"'.encode("utf-8")
    )
    parts.append(f"Content-Type: {file_content_type}".encode("utf-8"))
    parts.append(b"")
    # join already terminates the final "Content-Type" line with CRLF (via the
    # trailing empty element); add one more CRLF to form the blank line, then body.
    head = crlf.join(parts)
    body = head + crlf + file_bytes + crlf + b"--" + bnd + b"--" + crlf
    return body, f"multipart/form-data; boundary={boundary}"


def _emit(result):
    """Print the machine-readable result line for Claude to read."""
    print("RESULT: " + json.dumps(result, ensure_ascii=False))


# ── shared helpers ───────────────────────────────────────────────────────────


def _get_me(args):
    return _request(args, "GET", "/api/users/me")


def _ci_match(haystack, needle):
    return needle.lower() in (haystack or "").lower()


def _iter_all_reviews(args, page_limit=200):
    """Yield every review summary the key can see, paging through the cursor."""
    cursor = None
    while True:
        path = f"/api/reviews?limit={page_limit}"
        if cursor:
            path += "&cursor=" + urllib.parse.quote(cursor)
        page = _request(args, "GET", path)
        for item in page.get("items", []):
            yield item
        cursor = page.get("next_cursor")
        if not cursor:
            break


def _filter_reviews(args, items):
    out = []
    for r in items:
        meta = r.get("metadata", {}) or {}
        if args.status and (r.get("status") or "") != args.status:
            continue
        if args.advisor and not _ci_match(meta.get("advisor_name"), args.advisor):
            continue
        if args.firm and not _ci_match(meta.get("firm"), args.firm):
            continue
        if args.outcome and not _ci_match(meta.get("call_outcome"), args.outcome):
            continue
        if args.template and not _ci_match(meta.get("template_name"), args.template):
            continue
        if getattr(args, "tag", None):
            tag_names = [t.get("name", "") for t in (meta.get("tags") or [])]
            if not any(_ci_match(n, args.tag) for n in tag_names):
                continue
        score = r.get("overall_score")
        if getattr(args, "min_score", None) is not None and (score is None or score < args.min_score):
            continue
        if getattr(args, "max_score", None) is not None and (score is None or score > args.max_score):
            continue
        out.append(r)
    return out


def _compact(r):
    meta = r.get("metadata", {}) or {}
    return {
        "id": r.get("id"),
        "created_at": r.get("created_at"),
        "status": r.get("status"),
        "advisor": meta.get("advisor_name"),
        "firm": meta.get("firm"),
        "prospect": meta.get("prospect_name"),
        "outcome": meta.get("call_outcome"),
        "template": meta.get("template_name"),
        "score": r.get("overall_score"),
        "max_score": r.get("overall_max_score"),
        "tags": [t.get("name") for t in (meta.get("tags") or [])],
    }


# ── resolve names -> ids (for BDS upload) ──────────────────────────────────────


def _resolve_firm_id(args):
    firms = _request(args, "GET", "/api/firms")
    matches = [f for f in firms if _ci_match(f.get("name"), args.firm)]
    exact = [f for f in matches if (f.get("name") or "").lower() == args.firm.lower()]
    chosen = exact or matches
    if not chosen:
        raise SystemExit(f"No firm matches '{args.firm}'. Available: {[f.get('name') for f in firms]}")
    if len(chosen) > 1:
        raise SystemExit(f"'{args.firm}' is ambiguous: {[f.get('name') for f in chosen]}. Use an exact name.")
    return chosen[0]["id"]


def _resolve_advisor_id(args, firm_id):
    detail = _request(args, "GET", f"/api/firms/{firm_id}")
    users = detail.get("users", []) or []
    matches = [u for u in users if _ci_match(u.get("name"), args.advisor)]
    exact = [u for u in matches if (u.get("name") or "").lower() == args.advisor.lower()]
    chosen = exact or matches
    if not chosen:
        raise SystemExit(f"No advisor matches '{args.advisor}' at that firm. Available: {[u.get('name') for u in users]}")
    if len(chosen) > 1:
        raise SystemExit(f"'{args.advisor}' is ambiguous: {[u.get('name') for u in chosen]}. Use an exact name.")
    return chosen[0]["id"]


def _resolve_template_id(args, me):
    templates = _request(args, "GET", "/api/templates")
    if args.template:
        matches = [t for t in templates if _ci_match(t.get("name"), args.template)]
        if not matches:
            raise SystemExit(f"No template matches '{args.template}'. Available: {[t.get('name') for t in templates]}")
        if len(matches) > 1:
            raise SystemExit(f"'{args.template}' is ambiguous: {[t.get('name') for t in matches]}.")
        return matches[0]["id"]
    default_id = me.get("default_template_id")
    if default_id and any(t.get("id") == default_id for t in templates):
        return default_id
    if len(templates) == 1:
        return templates[0]["id"]
    raise SystemExit(
        "No template specified and no usable default. Pass --template with one of: "
        + str([t.get("name") for t in templates])
    )


# ── commands ───────────────────────────────────────────────────────────────────


def cmd_review(args):
    path = args.file
    if not os.path.isfile(path):
        raise SystemExit(f"File not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise SystemExit(f"Unsupported file type '{ext}'. Allowed: {sorted(SUPPORTED_EXTS)}")

    me = _get_me(args)
    role = me.get("role")
    fields = {"prospect_name": args.prospect, "call_outcome": args.outcome}
    if role == "bds_rep":
        if not (args.firm and args.advisor):
            raise SystemExit("--firm and --advisor are required for a BDS-rep key.")
        firm_id = _resolve_firm_id(args)
        fields["firm_id"] = firm_id
        fields["advisor_user_id"] = _resolve_advisor_id(args, firm_id)
        fields["template_id"] = _resolve_template_id(args, me)

    with open(path, "rb") as fh:
        file_bytes = fh.read()
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    body, content_type = _encode_multipart(
        fields, "file", os.path.basename(path), file_bytes, ctype
    )
    created = _request(args, "POST", "/api/upload", body=body, content_type=content_type)
    review_id = created.get("id")
    print(f"Uploaded. review_id={review_id} status={created.get('status')}", file=sys.stderr)

    # Poll until terminal.
    deadline = time.time() + args.timeout
    last_status = None
    review = None
    while time.time() < deadline:
        review = _request(args, "GET", f"/api/reviews/{review_id}")
        status = review.get("status")
        if status != last_status:
            print(f"  status: {status}", file=sys.stderr)
            last_status = status
        if status in ("complete", "failed"):
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    status = (review or {}).get("status")
    if status != "complete":
        result = {"review_id": review_id, "status": status}
        if status == "failed":
            result["error"] = (review or {}).get("error_message")
        else:
            result["note"] = "Timed out waiting; the review is still processing. Re-run search later."
        _emit(result)
        return 1

    # Download PDF.
    pdf_bytes, headers = _request(args, "GET", f"/api/reviews/{review_id}/pdf", raw=True)
    filename = f"Call-Review-{review_id}.pdf"
    disp = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    if "filename=" in disp:
        filename = disp.split("filename=")[-1].strip().strip('"') or filename
    os.makedirs(args.out_dir, exist_ok=True)
    pdf_path = os.path.join(args.out_dir, filename)
    with open(pdf_path, "wb") as fh:
        fh.write(pdf_bytes)

    result = {
        "review_id": review_id,
        "status": "complete",
        "summary": _compact(review),
        "pdf_path": os.path.abspath(pdf_path),
    }

    # Draft the coaching email (BDS-only on the server; surfaced as a note otherwise).
    if not args.no_email:
        try:
            result["email"] = _request(args, "POST", f"/api/reviews/{review_id}/coaching-email")
        except ApiError as e:
            result["email_error"] = e.detail if e.status != 403 else "coaching email is BDS-rep only"
    _emit(result)
    return 0


def cmd_search(args):
    items = _filter_reviews(args, list(_iter_all_reviews(args)))
    items = items[: args.limit]
    _emit({"count": len(items), "reviews": [_compact(r) for r in items]})
    return 0


def cmd_tag(args):
    names = [n.strip() for n in args.tags.split(",") if n.strip()]
    if not names:
        raise SystemExit("--tags must list at least one tag name.")
    # Create-or-fetch each tag (server dedups case-insensitively).
    resolved = {}
    for name in names:
        tag = _request(args, "POST", "/api/tags", json_body={"name": name})
        resolved[tag["id"]] = tag["name"]
    tag_ids = list(resolved.keys())

    if not args.replace:
        review = _request(args, "GET", f"/api/reviews/{args.review_id}")
        existing = review.get("tag_ids") or [t.get("id") for t in (review.get("metadata", {}).get("tags") or [])]
        for tid in existing:
            if tid not in resolved:
                tag_ids.append(tid)

    updated = _request(
        args, "PATCH", f"/api/reviews/{args.review_id}/tags", json_body={"tag_ids": tag_ids}
    )
    final_tags = [t.get("name") for t in (updated.get("metadata", {}).get("tags") or [])]
    _emit({"review_id": args.review_id, "tags": final_tags})
    return 0


def cmd_analyze(args):
    if args.review_ids:
        ids = [i.strip() for i in args.review_ids.split(",") if i.strip()]
    else:
        matched = _filter_reviews(args, list(_iter_all_reviews(args)))
        # history-chat only uses complete, scored reviews; newest first, capped.
        matched = [r for r in matched if (r.get("status") == "complete")]
        ids = [r["id"] for r in matched][:HISTORY_CHAT_MAX_IDS]
    if not ids:
        _emit({"error": "no calls matched the filters; nothing to analyze"})
        return 1
    body = {"review_ids": ids, "messages": [{"role": "user", "content": args.question}]}
    resp = _request(args, "POST", "/api/reviews/history-chat", json_body=body)
    _emit({"analyzed_count": len(ids), "answer": resp.get("answer")})
    return 0


# ── argparse ─────────────────────────────────────────────────────────────────


def _add_common(p):
    p.add_argument("--api-url", default=None, help="overrides CALL_REVIEWER_API_URL")
    p.add_argument("--api-key", default=None, help="overrides CALL_REVIEWER_API_KEY")


def _add_filters(p):
    p.add_argument("--advisor", default=None)
    p.add_argument("--firm", default=None)
    p.add_argument("--outcome", default=None)
    p.add_argument("--template", default=None)
    p.add_argument("--tag", default=None)
    p.add_argument("--status", default=None, help="e.g. complete")
    p.add_argument("--min-score", dest="min_score", type=float, default=None)
    p.add_argument("--max-score", dest="max_score", type=float, default=None)


def build_parser():
    parser = argparse.ArgumentParser(description="Call Reviewer CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("review", help="upload a recording, wait, download PDF + email")
    _add_common(pr)
    pr.add_argument("--file", required=True)
    pr.add_argument("--prospect", required=True)
    pr.add_argument("--advisor", default=None)
    pr.add_argument("--firm", default=None)
    pr.add_argument("--template", default=None)
    pr.add_argument("--outcome", default=None)
    pr.add_argument("--out-dir", dest="out_dir", default=".")
    pr.add_argument("--no-email", dest="no_email", action="store_true")
    pr.add_argument("--timeout", type=int, default=DEFAULT_POLL_TIMEOUT_SECONDS)
    pr.set_defaults(func=cmd_review)

    ps = sub.add_parser("search", help="list/filter past calls")
    _add_common(ps)
    _add_filters(ps)
    ps.add_argument("--limit", type=int, default=500)
    ps.set_defaults(func=cmd_search)

    pt = sub.add_parser("tag", help="create/assign tags to a call (BDS-rep key)")
    _add_common(pt)
    pt.add_argument("--review-id", dest="review_id", required=True)
    pt.add_argument("--tags", required=True, help="comma-separated tag names")
    pt.add_argument("--replace", action="store_true", help="replace instead of merge")
    pt.set_defaults(func=cmd_tag)

    pa = sub.add_parser("analyze", help="cross-call question over a filtered set")
    _add_common(pa)
    _add_filters(pa)
    pa.add_argument("--question", required=True)
    pa.add_argument("--review-ids", dest="review_ids", default=None, help="explicit comma-separated ids")
    pa.set_defaults(func=cmd_analyze)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ApiError as e:
        _emit({"error": str(e), "status": e.status})
        return 1


if __name__ == "__main__":
    sys.exit(main())
