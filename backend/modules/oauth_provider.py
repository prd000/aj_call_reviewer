"""OAuth 2.1 authorization-server provider for the MCP connector.

Implements `mcp.server.auth.provider.OAuthAuthorizationServerProvider`, backed by
Supabase (`oauth_clients` / `oauth_pending` / `oauth_codes` / `oauth_tokens`).
The flow exists to satisfy claude.ai/Cowork's connector (which requires OAuth +
dynamic client registration). Identity is established on our consent page by
pasting an `ak_live_…` API key; the issued bearer token is bound to that key's
user. Direct API-key access keeps working because `load_access_token` also
accepts an `ak_live_…` value as a bearer token (Claude Code/Desktop).

The provider is a thin layer over the existing API-key/user model — role/firm
still flow through `_user_context_from_profile` once `_auth` maps a token to a
`user_id`.
"""
import logging
import os
import secrets
import time
from datetime import datetime, timezone

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from modules.api_keys import KEY_TAG, resolve_api_key
from modules.supabase_client import get_client

logger = logging.getLogger(__name__)

MCP_SCOPE = "call-reviewer"
_PENDING_TTL = 600          # 10 min to complete the consent step
_CODE_TTL = 60              # auth codes are short-lived
_ACCESS_TTL = 3600          # 1 hour
_REFRESH_TTL = 60 * 60 * 24 * 30  # 30 days


def _public_base_url() -> str:
    url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not url:
        # OAuth metadata URLs would be wrong without this — fail loudly.
        raise RuntimeError("PUBLIC_BASE_URL must be set for the MCP OAuth server.")
    return url


def _now() -> int:
    return int(time.time())


def _to_iso(epoch: float | int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def _from_iso(iso: str | None) -> int | None:
    if not iso:
        return None
    return int(datetime.fromisoformat(iso).timestamp())


def _new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


class SupabaseOAuthProvider(OAuthAuthorizationServerProvider):
    # ── clients (dynamic registration) ─────────────────────────────────────────

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        client = await get_client()
        res = await client.table("oauth_clients").select("data").eq("client_id", client_id).execute()
        if not res.data:
            return None
        return OAuthClientInformationFull.model_validate(res.data[0]["data"])

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        client = await get_client()
        await client.table("oauth_clients").upsert({
            "client_id": client_info.client_id,
            "data": client_info.model_dump(mode="json"),
            "created_at": _to_iso(_now()),
        }).execute()

    # ── authorize → consent redirect ───────────────────────────────────────────

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Stash the in-flight request and send the user to our consent page."""
        request_id = _new_token("cr_rq_")
        stored = {
            "state": params.state,
            "scopes": params.scopes or [MCP_SCOPE],
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
        }
        sb = await get_client()
        await sb.table("oauth_pending").insert({
            "request_id": request_id,
            "client_id": client.client_id,
            "params": stored,
            "expires_at": _to_iso(_now() + _PENDING_TTL),
        }).execute()
        return f"{_public_base_url()}/mcp-oauth/consent?request_id={request_id}"

    async def complete_authorization(self, request_id: str, user_id: str) -> str:
        """Called by the consent route after a valid API key. Mints a code and
        returns the redirect URL back to the OAuth client."""
        sb = await get_client()
        res = await sb.table("oauth_pending").select("*").eq("request_id", request_id).execute()
        if not res.data:
            raise ValueError("This sign-in request has expired. Please reconnect from Claude.")
        pending = res.data[0]
        if _from_iso(pending["expires_at"]) and _from_iso(pending["expires_at"]) < _now():
            await sb.table("oauth_pending").delete().eq("request_id", request_id).execute()
            raise ValueError("This sign-in request has expired. Please reconnect from Claude.")
        params = pending["params"]
        code = _new_token("cr_ac_")
        await sb.table("oauth_codes").insert({
            "code": code,
            "client_id": pending["client_id"],
            "user_id": user_id,
            "scopes": params["scopes"],
            "code_challenge": params.get("code_challenge"),
            "redirect_uri": params["redirect_uri"],
            "redirect_uri_provided_explicitly": params.get("redirect_uri_provided_explicitly", True),
            "resource": params.get("resource"),
            "expires_at": _to_iso(_now() + _CODE_TTL),
        }).execute()
        await sb.table("oauth_pending").delete().eq("request_id", request_id).execute()
        return construct_redirect_uri(params["redirect_uri"], code=code, state=params.get("state"))

    # ── authorization codes ────────────────────────────────────────────────────

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        sb = await get_client()
        res = await sb.table("oauth_codes").select("*").eq("code", authorization_code).execute()
        if not res.data:
            return None
        row = res.data[0]
        if row["client_id"] != client.client_id:
            return None
        exp = _from_iso(row["expires_at"])
        if exp and exp < _now():
            return None
        return AuthorizationCode(
            code=row["code"],
            scopes=row["scopes"],
            expires_at=float(exp) if exp else float(_now()),
            client_id=row["client_id"],
            code_challenge=row.get("code_challenge") or "",
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=row.get("redirect_uri_provided_explicitly", True),
            resource=row.get("resource"),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        sb = await get_client()
        # Resolve the code's user, then consume it (one-time use).
        res = await sb.table("oauth_codes").select("user_id").eq("code", authorization_code.code).execute()
        if not res.data:
            raise ValueError("Invalid authorization code.")
        user_id = res.data[0]["user_id"]
        await sb.table("oauth_codes").delete().eq("code", authorization_code.code).execute()
        return await self._issue_tokens(client.client_id, user_id, authorization_code.scopes)

    # ── token issuance / refresh ────────────────────────────────────────────────

    async def _issue_tokens(self, client_id: str, user_id: str, scopes: list[str]) -> OAuthToken:
        access = _new_token("cr_at_")
        refresh = _new_token("cr_rt_")
        sb = await get_client()
        await sb.table("oauth_tokens").insert([
            {
                "token": access, "kind": "access", "client_id": client_id, "user_id": user_id,
                "scopes": scopes, "expires_at": _to_iso(_now() + _ACCESS_TTL),
            },
            {
                "token": refresh, "kind": "refresh", "client_id": client_id, "user_id": user_id,
                "scopes": scopes, "expires_at": _to_iso(_now() + _REFRESH_TTL),
            },
        ]).execute()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=_ACCESS_TTL,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        sb = await get_client()
        res = await sb.table("oauth_tokens").select("*").eq("token", refresh_token).eq("kind", "refresh").execute()
        if not res.data:
            return None
        row = res.data[0]
        if row["client_id"] != client.client_id or row.get("revoked_at"):
            return None
        exp = _from_iso(row["expires_at"])
        if exp and exp < _now():
            return None
        return RefreshToken(token=row["token"], client_id=row["client_id"], scopes=row["scopes"], expires_at=exp)

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        sb = await get_client()
        res = await sb.table("oauth_tokens").select("user_id").eq("token", refresh_token.token).execute()
        if not res.data:
            raise ValueError("Invalid refresh token.")
        user_id = res.data[0]["user_id"]
        # Rotate: revoke the old refresh token.
        await sb.table("oauth_tokens").update({"revoked_at": _to_iso(_now())}).eq("token", refresh_token.token).execute()
        return await self._issue_tokens(client.client_id, user_id, scopes or refresh_token.scopes)

    # ── access-token verification (the hot path) ────────────────────────────────

    async def load_access_token(self, token: str) -> AccessToken | None:
        # Dual path: an API key works as a bearer token (Claude Code/Desktop), so
        # the SDK's bearer auth accepts `Authorization: Bearer ak_live_…`.
        if token.startswith(KEY_TAG):
            resolved = await resolve_api_key(token)
            if resolved is None:
                return None
            return AccessToken(token=token, client_id="api-key", scopes=[MCP_SCOPE], expires_at=None)
        sb = await get_client()
        res = await sb.table("oauth_tokens").select("*").eq("token", token).eq("kind", "access").execute()
        if not res.data:
            return None
        row = res.data[0]
        if row.get("revoked_at"):
            return None
        exp = _from_iso(row["expires_at"])
        if exp and exp < _now():
            return None
        return AccessToken(token=row["token"], client_id=row["client_id"], scopes=row["scopes"], expires_at=exp)

    async def revoke_token(self, token) -> None:
        sb = await get_client()
        await sb.table("oauth_tokens").update({"revoked_at": _to_iso(_now())}).eq("token", token.token).execute()

    # ── helper used by mcp_server._auth ─────────────────────────────────────────

    async def resolve_token_user_id(self, token: str) -> str | None:
        """Map a validated bearer token back to a `user_id` (API key or OAuth token)."""
        if token.startswith(KEY_TAG):
            resolved = await resolve_api_key(token)
            return resolved["user_id"] if resolved else None
        sb = await get_client()
        res = await sb.table("oauth_tokens").select("user_id").eq("token", token).eq("kind", "access").execute()
        return res.data[0]["user_id"] if res.data else None


provider = SupabaseOAuthProvider()
