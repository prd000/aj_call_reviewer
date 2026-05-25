import os
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

app = Celery(
    "call_reviewer",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    backend=None,
    include=["tasks"],
)

app.conf.update(
    broker_transport_options={
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
    },
)
