"""
Fonctions métier du cockpit client — page d'accueil dashboard.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from memory.database import get_connection

_ACTIVE_STATUTS = "('entrant', 'qualifie', 'nurturing')"


def get_priority_actions(client_id: str) -> list[dict]:
    """
    Retourne les leads avec une action en attente, triés chaud → tiède → froid.

    Une action est considérée faite si last_action_completed_at >= next_action_computed_at.
    Les champs next_action_* ne sont jamais modifiés par cette logique.
    """
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, prenom, nom, telephone, score,
                   next_action_label, next_action_priority, next_action_reason,
                   next_action_computed_at, last_action_completed_at, updated_at
            FROM leads
            WHERE client_id = ?
              AND statut IN {_ACTIVE_STATUTS}
              AND next_action_label IS NOT NULL
              AND next_action_label != ''
              AND (
                  last_action_completed_at IS NULL
                  OR last_action_completed_at < next_action_computed_at
              )
            ORDER BY
              CASE WHEN score >= 18 THEN 0 WHEN score >= 11 THEN 1 ELSE 2 END,
              updated_at DESC
            """,
            (client_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_cockpit_kpis(client_id: str) -> dict:
    """Calcule les 4 KPIs affichés sur le bandeau résumé."""
    one_week_ago = datetime.now() - timedelta(days=7)
    with get_connection() as conn:
        chauds = conn.execute(
            f"SELECT COUNT(*) FROM leads WHERE client_id = ? AND score >= 18 AND statut IN {_ACTIVE_STATUTS}",
            (client_id,),
        ).fetchone()[0]
        tiedes = conn.execute(
            f"SELECT COUNT(*) FROM leads WHERE client_id = ? AND score >= 11 AND score < 18 AND statut IN {_ACTIVE_STATUTS}",
            (client_id,),
        ).fetchone()[0]
        nouveaux = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE client_id = ? AND created_at >= ?",
            (client_id, one_week_ago),
        ).fetchone()[0]
        actions = conn.execute(
            f"""
            SELECT COUNT(*) FROM leads
            WHERE client_id = ?
              AND statut IN {_ACTIVE_STATUTS}
              AND next_action_label IS NOT NULL
              AND next_action_label != ''
              AND (
                  last_action_completed_at IS NULL
                  OR last_action_completed_at < next_action_computed_at
              )
            """,
            (client_id,),
        ).fetchone()[0]
    return {"chauds": chauds, "tiedes": tiedes, "nouveaux": nouveaux, "actions": actions}


def get_recent_activity(client_id: str, limit: int = 5) -> list[dict]:
    """5 derniers leads modifiés pour la section activité récente."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, prenom, nom, telephone, statut, score, updated_at
            FROM leads
            WHERE client_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_action_done(lead_id: str, client_id: str) -> bool:
    """
    Marque l'action courante comme faite en posant last_action_completed_at = now().
    Ne modifie jamais next_action_label, next_action_reason ni next_action_computed_at.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE leads SET last_action_completed_at = ? WHERE id = ? AND client_id = ?",
            (datetime.now(), lead_id, client_id),
        )
    return True
