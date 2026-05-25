import os

import httpx
from supabase import acreate_client, AsyncClient, ClientOptions

_client: AsyncClient | None = None


async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = await acreate_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
            options=ClientOptions(httpx_client=httpx.AsyncClient(timeout=10.0)),
        )
    return _client
