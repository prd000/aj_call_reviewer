"""One-off backfill: populate overall_score / overall_max_score / template_name
on existing review rows that predate the 2026-06-12 summary columns migration.

Run from the backend/ directory after applying the migration:
    py -m scripts.backfill_summary_columns
"""
import asyncio
import logging
import os
import sys

# Ensure backend/ is on the path when run as a module.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.scoring import overall_score
from modules.supabase_client import get_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def backfill() -> None:
    client = await get_client()

    logger.info("Fetching all review rows...")
    result = await (
        client.table("reviews")
        .select("id, review_results, framework")
        .execute()
    )
    rows = result.data or []
    logger.info("Found %d rows to backfill.", len(rows))

    updated = skipped = 0
    for row in rows:
        score, max_s = overall_score(row.get("review_results"))
        tname = (row.get("framework") or {}).get("template_name")

        # Only write if at least one value is non-None (avoid unnecessary writes
        # for rows with no review data yet, e.g. pending/failed with no results).
        if score is None and tname is None:
            skipped += 1
            continue

        await (
            client.table("reviews")
            .update(
                {
                    "overall_score": score,
                    "overall_max_score": max_s,
                    "template_name": tname,
                }
            )
            .eq("id", row["id"])
            .execute()
        )
        updated += 1
        if updated % 50 == 0:
            logger.info("  Backfilled %d rows so far...", updated)

    logger.info(
        "Done. Updated %d rows, skipped %d (no review/template data).",
        updated,
        skipped,
    )


if __name__ == "__main__":
    asyncio.run(backfill())
