import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone

from modules.supabase_client import get_client

logger = logging.getLogger(__name__)

DEFAULT_CRITERIA = [
    {
        "title": "Rapport Building",
        "description": (
            "Assess whether the advisor opened with a warm personalized greeting, used the "
            "prospect's name naturally, showed genuine interest in the prospect's situation "
            "before moving to business, mirrored the prospect's tone and energy, created "
            "moments of authentic connection, and listened actively before responding."
        ),
        "success_condition": (
            "The advisor created a genuinely comfortable and trusting atmosphere. The "
            "prospect opened up freely, there were multiple natural moments of connection, "
            "and the advisor consistently listened and acknowledged before responding. "
            "Score 9–10 for exceptional warmth; 1–2 for cold or dismissive tone with no "
            "attempt to connect."
        ),
    },
    {
        "title": "Needs Discovery",
        "description": (
            "Assess whether the advisor asked open-ended questions, uncovered the prospect's "
            "current financial situation (assets, accounts, income), identified the prospect's "
            "goals and desired outcomes, uncovered fears and pain points, explored timeline "
            "and urgency, listened more than they talked, and asked follow-up questions that "
            "deepened understanding."
        ),
        "success_condition": (
            "The advisor comprehensively uncovered the prospect's current situation, goals, "
            "fears, and timeline. The prospect felt heard. The advisor asked more questions "
            "than they made statements and dug deeper on key concerns. Score 9–10 for "
            "comprehensive discovery; 1–2 for launching into a pitch with no discovery."
        ),
    },
    {
        "title": "Solution Presentation",
        "description": (
            "Assess whether the advisor tied the solution directly to the needs the prospect "
            "expressed, explained it in plain language, used concrete examples or case studies, "
            "clearly articulated the value proposition for this specific prospect, avoided "
            "unexplained jargon, presented with confidence, and kept the presentation "
            "appropriately concise."
        ),
        "success_condition": (
            "The solution was clearly connected to the prospect's specific situation, "
            "compelling, and easy to understand. The advisor used concrete examples and "
            "tied everything back to what the prospect said they cared about. Score 9–10 "
            "for highly tailored and clear presentation; 1–2 for no real solution presented "
            "or an irrelevant one."
        ),
    },
    {
        "title": "Objection Handling",
        "description": (
            "Assess whether the advisor acknowledged objections before responding, asked "
            "clarifying questions to understand the root of the objection, responded with "
            "empathy and without defensiveness, provided specific relevant answers, "
            "proactively surfaced common concerns before they arose, turned objections into "
            "opportunities to reinforce value, and maintained confidence after handling an "
            "objection."
        ),
        "success_condition": (
            "All objections were handled with empathy, specificity, and confidence. The "
            "advisor proactively surfaced and addressed common concerns before they became "
            "objections, and turned each objection into an opportunity to reinforce value. "
            "Score 9–10 for masterful handling; 1–2 for ignored or trust-damaging responses."
        ),
    },
]


async def list_templates() -> list[dict]:
    client = await get_client()
    result = await client.table("templates").select("*").order("created_at", desc=True).execute()
    return result.data


async def get_template(template_id: str) -> dict | None:
    client = await get_client()
    result = await client.table("templates").select("*").eq("id", template_id).execute()
    if not result.data:
        return None
    return result.data[0]


async def save_template(template: dict) -> dict:
    client = await get_client()
    now = datetime.now(timezone.utc).isoformat()
    if "id" not in template:
        template["id"] = str(uuid.uuid4())
    if "created_at" not in template:
        template["created_at"] = now
    template["updated_at"] = now
    await client.table("templates").upsert(template).execute()
    return template


async def delete_template(template_id: str) -> bool:
    client = await get_client()
    existing = await client.table("templates").select("id").eq("id", template_id).execute()
    if not existing.data:
        return False
    await client.table("templates").delete().eq("id", template_id).execute()
    return True


async def migrate_default_template() -> None:
    """One-time startup migration: import disk templates into Supabase, then seed Rudimentary if absent."""
    client = await get_client()
    existing = await client.table("templates").select("id").execute()
    if existing.data:
        return

    # Migrate any templates found on disk (both possible locations)
    disk_locations = [
        Path(__file__).parent.parent.parent / "data" / "templates",
        Path(__file__).parent.parent / "data" / "templates",
    ]
    migrated = 0
    for templates_dir in disk_locations:
        if not templates_dir.exists():
            continue
        for path in templates_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                await client.table("templates").upsert(data).execute()
                migrated += 1
            except Exception as exc:
                logger.warning("Failed to migrate template %s: %s", path, exc)

    if migrated:
        logger.info("Migrated %d template(s) from disk to Supabase.", migrated)

    # Seed Rudimentary if still absent after migration
    after = await client.table("templates").select("name").execute()
    if any(t.get("name") == "Rudimentary" for t in after.data):
        return

    template = {
        "name": "Rudimentary",
        "criteria": [{"id": str(uuid.uuid4()), **c} for c in DEFAULT_CRITERIA],
    }
    await save_template(template)
    logger.info("Created default 'Rudimentary' template.")
