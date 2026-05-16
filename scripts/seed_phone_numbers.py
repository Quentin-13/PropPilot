"""
Ajoute des numéros PropPilot dans le pool phone_numbers.

Usage :
    python scripts/seed_phone_numbers.py +33700000001 +33700000002 +33700000003

Comportement :
- Ajoute chaque numéro s'il n'existe pas (ON CONFLICT DO NOTHING)
- Provider = twilio, status = available
- N'écrase pas les numéros déjà assignés
- Affiche un rapport clair
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _validate(number: str) -> bool:
    stripped = number.strip()
    return stripped.startswith("+") and stripped[1:].isdigit() and len(stripped) >= 8


def seed(numbers: list[str]) -> None:
    from memory.database import init_database, get_connection

    init_database()

    added = 0
    skipped = 0
    invalid = 0

    with get_connection() as conn:
        for raw in numbers:
            number = raw.strip()
            if not _validate(number):
                print(f"  [INVALIDE]  {number!r} — format attendu : +33700000000")
                invalid += 1
                continue

            result = conn.execute(
                """
                INSERT INTO phone_numbers (phone_number, provider, status)
                VALUES (%s, 'twilio', 'available')
                ON CONFLICT (phone_number) DO NOTHING
                RETURNING phone_number
                """,
                (number,),
            ).fetchone()

            if result:
                print(f"  [AJOUTÉ]    {number}")
                added += 1
            else:
                # Numéro déjà présent — afficher son statut actuel
                row = conn.execute(
                    "SELECT status, client_id FROM phone_numbers WHERE phone_number = %s",
                    (number,),
                ).fetchone()
                status = row["status"] if row else "?"
                client = row["client_id"] if row else None
                detail = f"statut={status}" + (f", client={client}" if client else "")
                print(f"  [EXISTANT]  {number} — {detail}")
                skipped += 1

    print(f"\nRapport : {added} ajouté(s), {skipped} déjà présent(s), {invalid} invalide(s)")

    # Affiche l'état du pool complet
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT phone_number, status, client_id FROM phone_numbers ORDER BY id"
        ).fetchall()

    if rows:
        print("\nPool actuel :")
        for r in rows:
            tag = f"→ client {r['client_id']}" if r["client_id"] else ""
            print(f"  {r['phone_number']}  [{r['status']}]  {tag}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage : python scripts/seed_phone_numbers.py +33700000001 +33700000002 ...")
        sys.exit(1)
    seed(args)
