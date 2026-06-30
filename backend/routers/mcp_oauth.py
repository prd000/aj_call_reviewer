"""Browser-facing consent page for the MCP OAuth flow.

When claude.ai/Cowork opens the OAuth popup, the provider's `authorize()`
redirects here. The user proves identity by pasting an `ak_live_…` API key; on
success we mint an authorization code and redirect back to the OAuth client.

Mounted WITHOUT the JWT `_auth` dependency — this IS the sign-in surface.
"""
import html
import logging

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from modules.api_keys import resolve_api_key
from modules.oauth_provider import provider

logger = logging.getLogger(__name__)
router = APIRouter()


def _page(request_id: str, error: str | None = None) -> str:
    rid = html.escape(request_id or "")
    err_html = (
        f'<p class="err">{html.escape(error)}</p>' if error else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect Claude to Call Reviewer</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ background:#0b0e11; color:#eaecef; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         display:flex; min-height:100vh; margin:0; align-items:center; justify-content:center; }}
  .card {{ background:#1e2329; border:1px solid #2b3139; border-radius:16px; padding:32px; width:min(420px,90vw); }}
  h1 {{ font-size:20px; margin:0 0 8px; }}
  p {{ color:#929aa5; font-size:14px; line-height:1.5; margin:0 0 20px; }}
  label {{ display:block; font-size:13px; color:#929aa5; margin-bottom:6px; }}
  input {{ width:100%; box-sizing:border-box; background:#0b0e11; border:1px solid #2b3139; border-radius:8px;
           color:#eaecef; padding:12px; font-size:14px; font-family:ui-monospace,Menlo,Consolas,monospace; }}
  button {{ margin-top:16px; width:100%; background:#fcd535; color:#181a20; border:0; border-radius:8px;
            padding:12px; font-size:15px; font-weight:600; cursor:pointer; }}
  .err {{ color:#f6465d; margin:12px 0 0; }}
  .hint {{ margin-top:16px; font-size:12px; }}
</style></head>
<body>
  <form class="card" method="post" action="/mcp-oauth/consent">
    <h1>Connect Claude to Call Reviewer</h1>
    <p>Paste an API key to authorize Claude. Create one in the app under
       <strong>Management &rarr; API Keys</strong>. Claude will act with this key's permissions.</p>
    <input type="hidden" name="request_id" value="{rid}">
    <label for="api_key">API key</label>
    <input id="api_key" name="api_key" type="password" placeholder="ak_live_…" autocomplete="off" autofocus required>
    <button type="submit">Authorize</button>
    {err_html}
  </form>
</body></html>"""


@router.get("/mcp-oauth/consent", response_class=HTMLResponse)
async def consent_page(request_id: str = ""):
    return HTMLResponse(_page(request_id))


@router.post("/mcp-oauth/consent")
async def consent_submit(request_id: str = Form(...), api_key: str = Form(...)):
    resolved = await resolve_api_key((api_key or "").strip())
    if resolved is None:
        return HTMLResponse(_page(request_id, "That API key is invalid or revoked. Try another."), status_code=401)
    try:
        redirect_url = await provider.complete_authorization(request_id, resolved["user_id"])
    except ValueError as exc:
        return HTMLResponse(_page(request_id, str(exc)), status_code=400)
    except Exception as exc:  # noqa: BLE001
        logger.error("consent_submit failed: %s", exc, exc_info=True)
        return HTMLResponse(_page(request_id, "Something went wrong. Please reconnect from Claude."), status_code=500)
    return RedirectResponse(redirect_url, status_code=302)
