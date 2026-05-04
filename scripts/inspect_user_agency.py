"""
Lecture seule — inspecte le schéma et les données de users + agency_phone_numbers.
Usage : python scripts/inspect_user_agency.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.database import get_connection

TARGET_EMAIL = "contact.maisondusommeil@gmail.com"


def print_columns(cur) -> None:
    rows = cur.fetchall()
    if not rows:
        print("  (table introuvable dans information_schema)")
        return
    for row in rows:
        print(f"  {row['column_name']:<40} {row['data_type']}")


def print_rows(cur) -> None:
    rows = cur.fetchall()
    if not rows:
        print("  (aucun résultat)")
        return
    for i, row in enumerate(rows, 1):
        print(f"  [#{i}]")
        for key in row.keys():
            print(f"    {key}: {row[key]}")
        print()


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def main() -> None:
    with get_connection() as conn:

        # ── 1. Colonnes de users ──────────────────────────────────────────────
        section("Colonnes de la table 'users'")
        cur = conn.execute(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_name = 'users' "
            "ORDER BY ordinal_position"
        )
        print_columns(cur)

        # ── 2. Colonnes de agency_phone_numbers ───────────────────────────────
        section("Colonnes de la table 'agency_phone_numbers'")
        cur = conn.execute(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_name = 'agency_phone_numbers' "
            "ORDER BY ordinal_position"
        )
        print_columns(cur)

        # ── 3. Données users pour l'email cible ───────────────────────────────
        section(f"users WHERE email = '{TARGET_EMAIL}'")
        cur = conn.execute(
            "SELECT * FROM users WHERE email = %s",
            (TARGET_EMAIL,),
        )
        print_rows(cur)

        # ── 4. Toutes les lignes de agency_phone_numbers ──────────────────────
        section("agency_phone_numbers (toutes les lignes)")
        cur = conn.execute("SELECT * FROM agency_phone_numbers")
        print_rows(cur)


if __name__ == "__main__":
    main()
