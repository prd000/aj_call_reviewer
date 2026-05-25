import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from modules.templates import migrate_default_template
from routers import upload, reviews, templates, management

load_dotenv(Path(__file__).parent.parent / ".env")

_extra_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
ALLOWED_ORIGINS = ["http://localhost:5173"] + _extra_origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    await migrate_default_template()
    yield


app = FastAPI(title="Call Reviewer API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(management.router, prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "ok"}
