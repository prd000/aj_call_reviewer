"""MCP server exposing Call Reviewer as tools for a Claude connector.

Mounted onto the main FastAPI app (see `main.py`) at `/mcp`, so it shares the
Railway deploy, env, Supabase client, and the API-key auth. Tools reuse the
existing router handlers and module functions — visibility/role rules are NOT
re-implemented here, they come along with the shared handlers.

Auth: every tool resolves the caller from the request's `X-API-Key` header (or a
`Bearer ak_live_…`) via the same `resolve_api_key` + profile-load path the REST
API uses, yielding the identical `{user_id, role, firm_id, name}` context.

NOTE: the MCP transport + connector auth need live verification on Railway; the
streamable-HTTP session manager lifespan is wired into the app lifespan in main.py.
"""
import base64
import logging
import os

from fastapi import HTTPException
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from modules.api_keys import KEY_TAG, resolve_api_key, touch_last_used
from modules.auth import _user_context_from_profile
from modules.firms import get_firm_users, list_firms as _list_firms
from modules.tags import create_tag as _create_tag, list_tags as _list_tags
from modules.templates import list_templates as _list_templates
from modules.user_profiles import get_profile

# Reuse the REST handlers so role/visibility logic stays single-sourced.
from routers.reviews import (
    TagIdsBody,
    ChatMessage,
    HistoryChatBody,
    chat_over_history,
    download_review_pdf,
    draft_coaching_email,
    get_review_by_id,
    get_reviews,
    update_review_tags_by_id,
)
from routers.upload import (
    PresignBody,
    UploadFromStorageBody,
    presign_upload,
    upload_from_storage,
)

logger = logging.getLogger(__name__)

# DNS-rebinding protection is a localhost-server defense (stops a malicious web
# page from making a browser talk to a local MCP server). This is a deliberate
# PUBLIC remote MCP behind Railway's TLS edge, reached by MCP clients over HTTPS,
# so it's off by default. Set MCP_ALLOWED_HOSTS (comma-separated) to lock the
# Host/Origin check to your deploy domain(s).
_mcp_hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
if _mcp_hosts:
    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_mcp_hosts,
        allowed_origins=_mcp_hosts,
    )
else:
    _transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

# streamable_http_path="/" so that mounting the app at "/mcp" yields a clean
# "/mcp" endpoint (instead of "/mcp/mcp").
mcp = FastMCP(
    "call-reviewer", streamable_http_path="/", transport_security=_transport_security
)


# ── auth + error plumbing ──────────────────────────────────────────────────────


async def _auth(ctx: Context) -> dict:
    """Resolve the caller from the request's API key, or raise a tool error.

    Looks for the key in (1) the `X-API-Key` header, (2) an `Authorization:
    Bearer ak_live_…` header, or (3) an `?api_key=` query parameter. The query-
    param path exists for clients whose connector UI has no header field (e.g.
    claude.ai's custom-connector dialog) — paste `…/mcp?api_key=ak_live_…` as the
    URL. Note: a key in the URL can appear in access logs; rotate/revoke as needed.
    """
    request = getattr(ctx.request_context, "request", None)
    headers = getattr(request, "headers", None) or {}
    api_key = headers.get("x-api-key")
    if not api_key:
        authz = headers.get("authorization", "") or ""
        if authz.startswith("Bearer "):
            cand = authz[len("Bearer "):]
            if cand.startswith(KEY_TAG):
                api_key = cand
    if not api_key and request is not None:
        try:
            api_key = request.query_params.get("api_key")
        except Exception:
            api_key = None
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set the X-API-Key header (Claude Code/Desktop) or "
            "append ?api_key=ak_live_… to the MCP URL (claude.ai connector)."
        )
    try:
        resolved = await resolve_api_key(api_key)
        if not resolved:
            raise RuntimeError("Invalid or revoked API key.")
        user = await _user_context_from_profile(resolved["user_id"])
    except HTTPException as e:
        raise RuntimeError(f"{e.status_code}: {e.detail}") from None
    await touch_last_used(resolved["key_id"])
    return user


async def _run(awaitable):
    """Await a reused REST handler, surfacing HTTPException as a readable tool error."""
    try:
        return await awaitable
    except HTTPException as e:
        raise RuntimeError(f"{e.status_code}: {e.detail}") from None


def _summary_row(r: dict) -> dict:
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


def _ci(haystack, needle) -> bool:
    return (needle or "").lower() in (haystack or "").lower()


async def _all_summaries(user: dict) -> list[dict]:
    """Page through every review the caller can see (reuses get_reviews → FA scoping)."""
    items, cursor = [], None
    while True:
        page = await _run(get_reviews(user=user, limit=200, cursor=cursor))
        items.extend(page.get("items", []))
        cursor = page.get("next_cursor")
        if not cursor:
            return items


async def _filtered_summaries(user, advisor=None, firm=None, outcome=None,
                              template=None, tag=None, status=None) -> list[dict]:
    out = []
    for r in await _all_summaries(user):
        meta = r.get("metadata", {}) or {}
        if status and (r.get("status") or "") != status:
            continue
        if advisor and not _ci(meta.get("advisor_name"), advisor):
            continue
        if firm and not _ci(meta.get("firm"), firm):
            continue
        if outcome and not _ci(meta.get("call_outcome"), outcome):
            continue
        if template and not _ci(meta.get("template_name"), template):
            continue
        if tag and not any(_ci(t.get("name"), tag) for t in (meta.get("tags") or [])):
            continue
        out.append(r)
    return out


# ── discovery / resolution tools ───────────────────────────────────────────────


@mcp.tool()
async def list_firms(ctx: Context) -> list[dict]:
    """List firms (id + name) the caller can use for uploads."""
    await _auth(ctx)
    return await _run(_list_firms())


@mcp.tool()
async def list_firm_advisors(firm_id: str, ctx: Context) -> list[dict]:
    """List the advisors (id + name) at a firm."""
    await _auth(ctx)
    return await _run(get_firm_users(firm_id))


@mcp.tool()
async def list_templates(ctx: Context) -> list[dict]:
    """List the available review templates (id + name)."""
    await _auth(ctx)
    return await _run(_list_templates())


@mcp.tool()
async def resolve_upload_targets(
    firm_name: str, advisor_name: str, ctx: Context, template_name: str | None = None
) -> dict:
    """Resolve firm/advisor/template names to the IDs needed for an upload.

    Returns {firm_id, advisor_user_id, template_id}. Raises a readable error with
    the candidate names if a name is ambiguous or not found.
    """
    user = await _auth(ctx)
    firms = await _run(_list_firms())
    fmatch = [f for f in firms if _ci(f.get("name"), firm_name)]
    fexact = [f for f in fmatch if (f.get("name") or "").lower() == firm_name.lower()]
    firm = (fexact or fmatch)
    if not firm:
        raise RuntimeError(f"No firm matches '{firm_name}'. Available: {[f.get('name') for f in firms]}")
    if len(firm) > 1:
        raise RuntimeError(f"'{firm_name}' is ambiguous: {[f.get('name') for f in firm]}")
    firm_id = firm[0]["id"]

    users = await _run(get_firm_users(firm_id))
    amatch = [u for u in users if _ci(u.get("name"), advisor_name)]
    aexact = [u for u in amatch if (u.get("name") or "").lower() == advisor_name.lower()]
    advisor = (aexact or amatch)
    if not advisor:
        raise RuntimeError(f"No advisor matches '{advisor_name}' at that firm. Available: {[u.get('name') for u in users]}")
    if len(advisor) > 1:
        raise RuntimeError(f"'{advisor_name}' is ambiguous: {[u.get('name') for u in advisor]}")
    advisor_user_id = advisor[0]["id"]

    templates = await _run(_list_templates())
    if template_name:
        tmatch = [t for t in templates if _ci(t.get("name"), template_name)]
        if len(tmatch) != 1:
            raise RuntimeError(f"Template '{template_name}' did not match exactly one of {[t.get('name') for t in templates]}")
        template_id = tmatch[0]["id"]
    else:
        profile = await _run(get_profile(user["user_id"]))
        default_id = (profile or {}).get("default_template_id")
        if default_id and any(t.get("id") == default_id for t in templates):
            template_id = default_id
        elif len(templates) == 1:
            template_id = templates[0]["id"]
        else:
            raise RuntimeError(f"No template specified and no usable default. Choose one of {[t.get('name') for t in templates]}")
    return {"firm_id": firm_id, "advisor_user_id": advisor_user_id, "template_id": template_id}


# ── upload (pre-signed; bytes never traverse MCP) ──────────────────────────────


@mcp.tool()
async def request_upload_url(filename: str, ctx: Context) -> dict:
    """Get a pre-signed URL to PUT a recording to (mp3/mp4/m4a/wav).

    Returns {upload_url, token, storage_path}. PUT the file bytes to `upload_url`,
    then call `create_review_from_upload` with the returned `storage_path`.
    """
    user = await _auth(ctx)
    return await _run(presign_upload(PresignBody(filename=filename), user=user))


@mcp.tool()
async def create_review_from_upload(
    storage_path: str,
    prospect_name: str,
    ctx: Context,
    firm_id: str | None = None,
    advisor_user_id: str | None = None,
    template_id: str | None = None,
    call_outcome: str | None = None,
) -> dict:
    """Create a review from a recording already PUT to a pre-signed URL.

    For a BDS-rep key, pass firm_id/advisor_user_id/template_id (see
    `resolve_upload_targets`). Returns {id, status}; poll with `get_review_status`.
    """
    user = await _auth(ctx)
    body = UploadFromStorageBody(
        storage_path=storage_path, filename=storage_path.rsplit("/", 1)[-1],
        prospect_name=prospect_name, firm_id=firm_id, advisor_user_id=advisor_user_id,
        template_id=template_id, call_outcome=call_outcome,
    )
    return await _run(upload_from_storage(body, user=user))


# ── status / results / analysis ────────────────────────────────────────────────


@mcp.tool()
async def get_review_status(review_id: str, ctx: Context) -> dict:
    """Get a review's processing status (and error/score if available)."""
    user = await _auth(ctx)
    review = await _run(get_review_by_id(review_id, user=user))
    return {
        "id": review.get("id"),
        "status": review.get("status"),
        "error_message": review.get("error_message"),
        "overall_score": review.get("overall_score"),
        "overall_max_score": review.get("overall_max_score"),
    }


@mcp.tool()
async def get_review_report(review_id: str, ctx: Context) -> dict:
    """Get the structured review (summary + per-criterion scores/feedback) plus the
    PDF as base64. Only works once the review is `complete`."""
    user = await _auth(ctx)
    review = await _run(get_review_by_id(review_id, user=user))
    resp = await _run(download_review_pdf(review_id, user=user))
    pdf_b64 = base64.b64encode(getattr(resp, "body", b"")).decode("ascii")
    return {
        "id": review.get("id"),
        "status": review.get("status"),
        "metadata": review.get("metadata"),
        "review": review.get("review"),
        "major_focus": review.get("major_focus"),
        "pdf_base64": pdf_b64,
    }


@mcp.tool()
async def draft_email(review_id: str, ctx: Context) -> dict:
    """Draft a coaching email {subject, body} for a completed review (BDS-rep key)."""
    user = await _auth(ctx)
    if user["role"] != "bds_rep":
        raise RuntimeError("403: BDS reps only")
    return await _run(draft_coaching_email(review_id, user=user))


@mcp.tool()
async def search_reviews(
    ctx: Context,
    advisor: str | None = None,
    firm: str | None = None,
    outcome: str | None = None,
    template: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict:
    """Search past calls by advisor/firm/outcome/template/tag/status (case-insensitive)."""
    user = await _auth(ctx)
    rows = await _filtered_summaries(user, advisor, firm, outcome, template, tag, status)
    rows = rows[: max(1, min(limit, 500))]
    return {"count": len(rows), "reviews": [_summary_row(r) for r in rows]}


@mcp.tool()
async def list_tags(ctx: Context) -> list[dict]:
    """List the tag vocabulary (id + name)."""
    await _auth(ctx)
    return await _run(_list_tags())


@mcp.tool()
async def tag_review(
    review_id: str, tag_names: list[str], ctx: Context, replace: bool = False
) -> dict:
    """Create-or-fetch the given tags and assign them to a review (BDS-rep key).

    Merges with the review's existing tags unless `replace` is true."""
    user = await _auth(ctx)
    if user["role"] != "bds_rep":
        raise RuntimeError("403: BDS reps only")
    resolved = {}
    for name in tag_names:
        if name and name.strip():
            tag = await _run(_create_tag(name.strip()))
            resolved[tag["id"]] = tag["name"]
    tag_ids = list(resolved.keys())
    if not replace:
        current = await _run(get_review_by_id(review_id, user=user))
        existing = current.get("tag_ids") or [
            t.get("id") for t in (current.get("metadata", {}).get("tags") or [])
        ]
        for tid in existing:
            if tid not in resolved:
                tag_ids.append(tid)
    updated = await _run(
        update_review_tags_by_id(review_id, TagIdsBody(tag_ids=tag_ids), user=user)
    )
    return {"review_id": review_id, "tags": [t.get("name") for t in (updated.get("metadata", {}).get("tags") or [])]}


@mcp.tool()
async def analyze_calls(
    question: str,
    ctx: Context,
    review_ids: list[str] | None = None,
    advisor: str | None = None,
    firm: str | None = None,
    outcome: str | None = None,
    template: str | None = None,
    tag: str | None = None,
) -> dict:
    """Ask a question across many calls (cross-call coaching analysis).

    Provide explicit `review_ids`, or filters to select the set (newest 200
    complete calls). Example: advisor='ABC', firm='XYZ', question='which criterion
    are they consistently lowest on?'.
    """
    user = await _auth(ctx)
    if review_ids:
        ids = review_ids[:200]
    else:
        rows = await _filtered_summaries(user, advisor, firm, outcome, template, tag, status="complete")
        ids = [r["id"] for r in rows][:200]
    if not ids:
        return {"analyzed_count": 0, "answer": "No matching calls to analyze."}
    body = HistoryChatBody(review_ids=ids, messages=[ChatMessage(role="user", content=question)])
    result = await _run(chat_over_history(body, user=user))
    answer = result.get("answer") if isinstance(result, dict) else getattr(result, "answer", None)
    return {"analyzed_count": len(ids), "answer": answer}
