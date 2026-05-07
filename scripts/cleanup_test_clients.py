"""
Script one-shot : suppression des comptes test PropPilot.

À lancer manuellement APRÈS le déploiement de la migration 014 :
    railway run python scripts/cleanup_test_clients.py

Conditions préalables :
    - Migration 014 appliquée (colonne is_internal présente sur users)
    - Les 2 comptes internes ont bien is_internal=TRUE

Le script N'EST PAS exécuté automatiquement par le Procfile Railway.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.database import get_connection

# ── Comptes à supprimer ───────────────────────────────────────────────────────

EMAILS_TO_DELETE = [
    "winy.contact@gmail.com",
    "quentingouaze31@gmail.com",
    "manon.bernett@gmail.com",
    "quentinecom13@gmail.com",
    "pro.quentingouaze@gmail.com",
]

# ── Comptes à préserver (double-check sécurité) ───────────────────────────────

EMAILS_INTERNAL = [
    "contact@proppilot.fr",
    "contact.maisondusommeil@gmail.com",
]


def _check_migration_applied(conn) -> None:
    """Vérifie que la migration 014 est appliquée (colonne is_internal présente)."""
    try:
        conn.execute("SELECT is_internal FROM users LIMIT 1")
    except Exception as exc:
        print(
            "\n❌ Colonne is_internal absente de la table users.\n"
            "   Appliquer d'abord la migration 014 :\n"
            "   railway run alembic upgrade head\n"
        )
        sys.exit(1)


def _fetch_client_ids(conn, emails: list[str]) -> dict[str, str]:
    """Retourne {email: user_id} pour les emails trouvés en base."""
    result = {}
    for email in emails:
        row = conn.execute(
            "SELECT id FROM users WHERE email = %s", (email,)
        ).fetchone()
        if row:
            result[email] = row[0]
    return result


def _count_rows(conn, table: str, client_id: str, col: str = "client_id") -> int:
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} = %s", (client_id,)
        ).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


def _print_summary(conn, email: str, uid: str, agency_name: str) -> None:
    leads    = _count_rows(conn, "leads", uid)
    calls    = _count_rows(conn, "calls", uid)
    convs    = _count_rows(conn, "conversations", uid)
    extracts = _count_rows(conn, "conversation_extractions", uid)
    sms_rows = _count_rows(conn, "usage_tracking", uid)
    users_n  = _count_rows(conn, "users", uid, col="id")
    print(
        f"  Client: {agency_name} ({email})\n"
        f"    - {leads} leads\n"
        f"    - {calls} calls\n"
        f"    - {convs} conversations\n"
        f"    - {extracts} extractions\n"
        f"    - {sms_rows} entrées usage_tracking\n"
        f"    - {users_n} user(s)\n"
    )


def _delete_client(conn, uid: str) -> dict[str, int]:
    """Supprime toutes les données d'un client. Retourne le nombre de lignes supprimées par table."""
    counts = {}

    tables_by_client_id = [
        "twilio_usage",
        "user_activity",
        "usage_tracking",
        "api_actions",
        "conversation_extractions",
        "reminders",
        "conversations",
        "lead_journey",
        "roi_metrics",
        "estimations",
        "listings",
        "crm_connections",
        "calls",
        "leads",
    ]

    for table in tables_by_client_id:
        try:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE client_id = %s", (uid,)
            )
            counts[table] = getattr(cur, "rowcount", 0) or 0
        except Exception as exc:
            # Table peut ne pas avoir client_id (ex: admin_access_log) — ignorer
            counts[table] = 0

    # user_activity utilise aussi user_id = uid
    try:
        cur = conn.execute(
            "DELETE FROM user_activity WHERE user_id = %s", (uid,)
        )
        # ajoute au compteur déjà initialisé ci-dessus
        counts["user_activity"] = counts.get("user_activity", 0) + (getattr(cur, "rowcount", 0) or 0)
    except Exception:
        pass

    cur = conn.execute("DELETE FROM users WHERE id = %s", (uid,))
    counts["users"] = getattr(cur, "rowcount", 0) or 0

    return counts


def main() -> None:
    with get_connection() as conn:
        _check_migration_applied(conn)

        # Vérifie que les comptes internes ont bien is_internal=TRUE
        for email in EMAILS_INTERNAL:
            row = conn.execute(
                "SELECT is_internal FROM users WHERE email = %s", (email,)
            ).fetchone()
            if row is None:
                print(f"⚠️  Compte interne non trouvé en base : {email}")
            elif not row[0]:
                print(
                    f"\n❌ Compte {email} existe mais is_internal=FALSE.\n"
                    "   La migration 014 ne s'est pas correctement appliquée.\n"
                    "   Ne pas continuer — risque de suppression non intentionnelle.\n"
                )
                sys.exit(1)

        # Résolution email → user_id
        id_map = _fetch_client_ids(conn, EMAILS_TO_DELETE)

        if not id_map:
            print("Aucun des comptes cibles trouvé en base. Rien à supprimer.")
            return

        print(f"\n{'─'*60}")
        print(f"  {len(id_map)} compte(s) à supprimer :")
        print(f"{'─'*60}\n")

        for email, uid in id_map.items():
            row = conn.execute(
                "SELECT agency_name FROM users WHERE id = %s", (uid,)
            ).fetchone()
            agency = (row[0] or "—") if row else "—"
            _print_summary(conn, email, uid, agency)

        not_found = [e for e in EMAILS_TO_DELETE if e not in id_map]
        if not_found:
            print(f"  (Non trouvés en base, ignorés : {', '.join(not_found)})\n")

        print(f"{'─'*60}")
        confirm = input('\n  Tape "OUI SUPPRIMER" pour confirmer : ').strip()
        if confirm != "OUI SUPPRIMER":
            print("\n  Annulé — aucune modification.")
            return

        # Suppression en transaction (get_connection fait commit/rollback auto)
        total_counts: dict[str, int] = {}
        for email, uid in id_map.items():
            counts = _delete_client(conn, uid)
            for table, n in counts.items():
                total_counts[table] = total_counts.get(table, 0) + n
            print(f"  ✅ {email} supprimé (id={uid})")

    print(f"\n{'─'*60}")
    print("  Récapitulatif des lignes supprimées :")
    for table, n in sorted(total_counts.items()):
        if n > 0:
            print(f"    {table:40s} {n}")
    print(f"{'─'*60}\n")

    # Vérification finale : les comptes internes sont toujours là et intacts
    with get_connection() as conn:
        for email in EMAILS_INTERNAL:
            row = conn.execute(
                "SELECT id, is_internal FROM users WHERE email = %s", (email,)
            ).fetchone()
            if row:
                flag = "✅ is_internal=TRUE" if row[1] else "⚠️  is_internal=FALSE"
                print(f"  Compte interne {email} : {flag}")
            else:
                print(f"  ⚠️  Compte interne {email} INTROUVABLE après nettoyage !")

    print("\n  Nettoyage terminé.\n")


if __name__ == "__main__":
    main()
