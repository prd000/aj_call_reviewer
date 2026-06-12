import asyncio
import os

import httpx
from supabase import acreate_client, AsyncClient, ClientOptions

_client: AsyncClient | None = None
_lock = asyncio.Lock()


async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        async with _lock:
            if _client is None:
                _client = await acreate_client(
                    os.environ["SUPABASE_URL"],
                    os.environ["SUPABASE_KEY"],
                    options=ClientOptions(httpx_client=httpx.AsyncClient(timeout=10.0)),
                )
    return _client


def reset_client() -> None:
    """Drop the cached client so the next get_client() rebinds to the current event loop."""
    global _client
    _client = None
