"""
Auth sweep: every non-health, non-docs API route must require authentication.

Uses FastAPI's dependency tree (static analysis) to find routes that lack
get_current_user or require_bds_rep in their dependency chain — the same gap
that would have caught the unauthenticated templates router (finding 3.1).

Any failing route is a security gap: it can be accessed without a token.
"""
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from modules.auth import get_current_user, require_bds_rep

_SKIP_PATHS = frozenset({"/health", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"})
_AUTH_DEPS = frozenset({get_current_user, require_bds_rep})


def _has_auth_dep(dependant) -> bool:
    """Recursively check whether the dependency tree contains an auth function."""
    if dependant.call in _AUTH_DEPS:
        return True
    return any(_has_auth_dep(d) for d in dependant.dependencies)


def _collect_routes():
    routes = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in _SKIP_PATHS:
            continue
        for method in sorted(route.methods or set()):
            routes.append((method, route.path, route))
    return routes


_ROUTES = _collect_routes()


@pytest.mark.parametrize("method,path,route", _ROUTES, ids=[f"{m} {p}" for m, p, _ in _ROUTES])
def test_route_has_auth_dependency(method, path, route):
    """
    SECURITY SWEEP: every mounted route except /health and docs must have
    get_current_user or require_bds_rep somewhere in its dependency tree.

    A failing test means the route at this path/method is accessible without
    authentication — a potential security vulnerability (finding 3.1).
    """
    assert _has_auth_dep(route.dependant), (
        f"SECURITY: {method} {path} has no authentication dependency. "
        "Add Depends(get_current_user) or Depends(require_bds_rep). "
        "Any caller without a valid token can access this endpoint."
    )
