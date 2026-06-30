import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from modules.auth import get_current_user
from modules.templates import migrate_default_template
from mcp_server import mcp
from routers import upload, reviews, templates, management, tags

load_dotenv(Path(__file__).parent.parent / ".env")

_extra_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
ALLOWED_ORIGINS = ["http://localhost:5173"] + _extra_origins

# Build the MCP ASGI app once so its session manager exists before mount.
_mcp_app = mcp.streamable_http_app()

# The MCP streamable-HTTP session manager can be started only once per process.
# In production the lifespan runs exactly once; this guard keeps the test suite
# (which spins up many TestClient lifecycles) from re-running it.
_mcp_started = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mcp_started
    await migrate_default_template()
    if _mcp_started:
        yield
        return
    _mcp_started = True
    # Mounting a sub-app does NOT run its lifespan automatically, so enter the
    # MCP app's lifespan here to start its streamable-HTTP session manager.
    async with _mcp_app.router.lifespan_context(_mcp_app):
        yield


app = FastAPI(title="Call Reviewer API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_auth = [Depends(get_current_user)]
app.include_router(upload.router, prefix="/api", dependencies=_auth)
app.include_router(reviews.router, prefix="/api", dependencies=_auth)
app.include_router(tags.router, prefix="/api", dependencies=_auth)
app.include_router(templates.router, prefix="/api", dependencies=_auth)
app.include_router(management.router, prefix="/api", dependencies=_auth)

# Remote MCP connector (streamable HTTP). Auth is handled per-tool inside the MCP
# server via the X-API-Key header, so this mount is NOT behind the JWT `_auth`
# dependency. Endpoint: <base>/mcp
app.mount("/mcp", _mcp_app)


@app.get("/health")
def health_check():
    return {"status": "ok"}
