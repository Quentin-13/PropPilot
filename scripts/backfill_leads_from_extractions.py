"""
Backfill leads.* depuis la dernière extraction disponible.
Pour chaque lead ayant au moins une extraction mais des champs vides,
applique les données extraites via apply_extraction_to_lead().

Usage :
  python3 scripts/backfill_leads_from_extractions.py           # dry-run
  python3 scripts/backfill_leads_from_extractions.py --apply   # exécution réelle
"""
import sys
import os
import logging
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from memory.database import get_connection
from memory.call_repository import get_latest_extraction_for_lead, apply_extraction_to_lead


def main(dry_run: bool) -> None:
    with get_connection() as conn:
        leads = conn.execute(
            "SELECT id, score, projet, budget, localisation FROM leads"
        ).fetchall()

    total = len(leads)
    would_update = 0
    updated = 0
    skipped_no_extraction = 0

    for lead_row in leads:
        lead_id = lead_row["id"]
        extraction = get_latest_extraction_for_lead(lead_id)

        if not extraction:
            skipped_no_extraction += 1
            continue

        would_update += 1
        logger.info(
            "[backfill] lead=%s score=%s→%s projet=%s→%s budget=%s→%s localisation=%s→%s",
            lead_id[:8],
            lead_row["score"], extraction.get("score_qualification"),
            lead_row["projet"], extraction.get("type_projet"),
            lead_row["budget"] or "—", extraction.get("budget_max"),
            lead_row["localisation"] or "—", extraction.get("zone_geographique"),
        )

        if not dry_run:
            apply_extraction_to_lead(lead_id, extraction)
            updated += 1

    if dry_run:
        logger.info(
            "DRY-RUN — %d leads sur %d seraient mis à jour (%d sans extraction)",
            would_update, total, skipped_no_extraction,
        )
    else:
        logger.info(
            "DONE — %d leads mis à jour sur %d (%d sans extraction)",
            updated, total, skipped_no_extraction,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="Exécuter réellement (défaut: dry-run)"
    )
    args = parser.parse_args()
    main(dry_run=not args.apply)
