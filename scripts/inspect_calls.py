"""
Lecture seule — inspecte la table calls et call_extractions.
Usage : python scripts/inspect_calls.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.database import get_connection


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

        # ── 1. Colonnes de calls ──────────────────────────────────────────────
        section("Colonnes de la table 'calls'")
        cur = conn.execute(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_name = 'calls' "
            "ORDER BY ordinal_position"
        )
        print_columns(cur)

        # ── 2. Les 5 derniers appels ──────────────────────────────────────────
        section("5 derniers appels (calls ORDER BY created_at DESC)")
        cur = conn.execute(
            "SELECT * FROM calls ORDER BY created_at DESC LIMIT 5"
        )
        print_rows(cur)

        # ── 3. Colonnes de call_extractions ───────────────────────────────────
        section("Colonnes de la table 'call_extractions'")
        cur = conn.execute(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_name = 'call_extractions' "
            "ORDER BY ordinal_position"
        )
        print_columns(cur)

        # ── 4. Les 5 dernières extractions ────────────────────────────────────
        section("5 dernières extractions (call_extractions ORDER BY created_at DESC)")
        cur = conn.execute(
            "SELECT * FROM call_extractions ORDER BY created_at DESC LIMIT 5"
        )
        print_rows(cur)


if __name__ == "__main__":
    main()
