"""
Crée (ou met à jour) le mapping numéro Twilio → portable agent
dans la table agency_phone_numbers.

Usage:
    python scripts/setup_test_phone_mapping.py --agent-phone +336XXXXXXXX
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from memory.database import init_database
from memory.call_repository import upsert_phone_number, get_phone_number_config

TWILIO_NUMBER = "+33757596114"


def main() -> None:
    parser = argparse.ArgumentParser(description="Crée le mapping Twilio → agent dans agency_phone_numbers")
    parser.add_argument("--agent-phone", required=True, help="Numéro de portable de l'agent (ex: +336XXXXXXXX)")
    parser.add_argument("--agency-id", default=None, help="Agency ID à utiliser (défaut: AGENCY_CLIENT_ID du .env)")
    args = parser.parse_args()

    settings = get_settings()
    agency_id = args.agency_id if args.agency_id else settings.agency_client_id

    init_database()

    print(f"\n[setup] Numéro Twilio  : {TWILIO_NUMBER}")
    print(f"[setup] Agency ID      : {agency_id}")
    print(f"[setup] Agent phone    : {args.agent_phone}")

    before = get_phone_number_config(TWILIO_NUMBER)
    print(f"\n[setup] État AVANT     : {before or 'aucun mapping existant'}")

    upsert_phone_number(
        twilio_number=TWILIO_NUMBER,
        agency_id=agency_id,
        agent_id=None,
        agent_phone=args.agent_phone,
        label="test-mapping-initial",
    )

    after = get_phone_number_config(TWILIO_NUMBER)
    print(f"[setup] État APRÈS     : {after}")
    print("\n[setup] Mapping OK — prêt pour l'appel entrant.\n")


if __name__ == "__main__":
    main()
