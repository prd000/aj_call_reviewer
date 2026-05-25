import os

import httpx
from supabase import Client, ClientOptions, create_client

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
            options=ClientOptions(httpx_client=httpx.Client(timeout=10.0)),
        )
    return _client
