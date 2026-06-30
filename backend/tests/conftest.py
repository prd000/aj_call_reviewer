"""
Set required env vars before any backend module is imported.
auth.py reads SUPABASE_URL at module-level, before load_dotenv runs in main.py,
so tests fail with KeyError unless we seed the environment first.
"""
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
# mcp_server reads this at import time (OAuth metadata origin).
os.environ.setdefault("PUBLIC_BASE_URL", "https://test-app.example.com")
