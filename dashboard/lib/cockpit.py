"""
Fonctions métier du cockpit client — page d'accueil dashboard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from memory.database import get_connection

logger = logging.getLogger(__name__)

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


# ─── Nouvelles fonctions tableau de bord valeur ───────────────────────────────

def get_dashboard_kpis(client_id: str, period_days: int = 7) -> dict:
    """
    6 KPIs orientés valeur pour la période donnée.
    Sources : calls, conversations, leads, crm_sync_log.
    """
    since = datetime.now() - timedelta(days=period_days)
    try:
        with get_connection() as conn:
            appels = conn.execute(
                "SELECT COUNT(*) FROM calls WHERE client_id = ? AND created_at >= ?",
                (client_id, since),
            ).fetchone()[0]
            sms = conn.execute(
                """SELECT COUNT(*) FROM conversations
                   WHERE client_id = ? AND canal = 'sms' AND role = 'user' AND created_at >= ?""",
                (client_id, since),
            ).fetchone()[0]
            leads_crees = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE client_id = ? AND created_at >= ?",
                (client_id, since),
            ).fetchone()[0]
            leads_enrichis = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE client_id = ? AND last_extraction_at >= ?",
                (client_id, since),
            ).fetchone()[0]
            envois_crm = conn.execute(
                """SELECT COUNT(*) FROM crm_sync_log
                   WHERE client_id = ? AND status = 'success' AND sent_at >= ?""",
                (client_id, since),
            ).fetchone()[0]
            actions = conn.execute(
                f"""SELECT COUNT(*) FROM leads
                   WHERE client_id = ?
                     AND statut IN {_ACTIVE_STATUTS}
                     AND next_action_label IS NOT NULL AND next_action_label != ''
                     AND (last_action_completed_at IS NULL
                          OR last_action_completed_at < next_action_computed_at)""",
                (client_id,),
            ).fetchone()[0]
        return {
            "appels_captes": appels or 0,
            "sms_captes": sms or 0,
            "leads_crees": leads_crees or 0,
            "leads_enrichis": leads_enrichis or 0,
            "envois_crm": envois_crm or 0,
            "actions_recommandees": actions or 0,
        }
    except Exception as e:
        logger.warning("[Cockpit] get_dashboard_kpis: %s", e)
        return {"appels_captes": 0, "sms_captes": 0, "leads_crees": 0,
                "leads_enrichis": 0, "envois_crm": 0, "actions_recommandees": 0}


_CATEGORY_FILTER: dict[str, str] = {
    "budgets":     "ce.budget_min IS NOT NULL OR ce.budget_max IS NOT NULL",
    "zones":       "ce.zone_geographique IS NOT NULL AND ce.zone_geographique != ''",
    "types_bien":  "ce.type_bien IS NOT NULL AND ce.type_bien != ''",
    "motivations": "ce.motivation IS NOT NULL AND ce.motivation != ''",
    "financements":"ce.financement IS NOT NULL AND ce.financement <> '{}'::jsonb",
    "objections":  "ce.points_attention IS NOT NULL AND jsonb_array_length(ce.points_attention) > 0",
}


def get_detected_info_stats(client_id: str, period_days: int = 7) -> dict:
    """
    Compte les leads distincts ayant une information clé extraite sur la période.
    Source : conversation_extractions (extraction_status='ok').
    """
    since = datetime.now() - timedelta(days=period_days)
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT
                     COUNT(DISTINCT lead_id) FILTER (WHERE budget_min IS NOT NULL
                                         OR budget_max IS NOT NULL) AS budgets,
                     COUNT(DISTINCT lead_id) FILTER (WHERE zone_geographique IS NOT NULL
                                         AND zone_geographique != '') AS zones,
                     COUNT(DISTINCT lead_id) FILTER (WHERE type_bien IS NOT NULL
                                         AND type_bien != '') AS types_bien,
                     COUNT(DISTINCT lead_id) FILTER (WHERE motivation IS NOT NULL
                                         AND motivation != '') AS motivations,
                     COUNT(DISTINCT lead_id) FILTER (WHERE financement IS NOT NULL
                                         AND financement <> '{}'::jsonb) AS financements,
                     COUNT(DISTINCT lead_id) FILTER (WHERE points_attention IS NOT NULL
                                         AND jsonb_array_length(points_attention) > 0) AS objections
                   FROM conversation_extractions
                   WHERE client_id = ? AND extraction_status = 'ok' AND extracted_at >= ?""",
                (client_id, since),
            ).fetchone()
        if row:
            return {k: row[k] or 0
                    for k in ("budgets", "zones", "types_bien", "motivations", "financements", "objections")}
    except Exception as e:
        logger.warning("[Cockpit] get_detected_info_stats: %s", e)
    return {"budgets": 0, "zones": 0, "types_bien": 0, "motivations": 0, "financements": 0, "objections": 0}


def get_detected_info_detail(client_id: str, category: str, period_days: int = 30) -> list[dict]:
    """
    Retourne un enregistrement par lead distinct (extraction la plus récente sur la période).
    category : budgets | zones | types_bien | motivations | financements | objections
    """
    cat_filter = _CATEGORY_FILTER.get(category)
    if not cat_filter:
        return []
    since = datetime.now() - timedelta(days=period_days)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT ON (ce.lead_id)
                    l.id AS lead_id, l.prenom, l.nom, l.telephone, l.score,
                    ce.budget_min, ce.budget_max, ce.zone_geographique, ce.type_bien,
                    ce.financement, ce.motivation, ce.points_attention, ce.extracted_at
                FROM conversation_extractions ce
                LEFT JOIN leads l ON l.id = ce.lead_id
                WHERE ce.client_id = ? AND ce.extraction_status = 'ok' AND ce.extracted_at >= ?
                  AND ({cat_filter})
                ORDER BY ce.lead_id, ce.extracted_at DESC
                """,
                (client_id, since),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[Cockpit] get_detected_info_detail: %s", e)
        return []


def get_crm_export_stats(client_id: str, period_days: int = 7) -> dict:
    """
    Stats d'export CRM : envois réussis sur la période + date du dernier envoi.
    Source : crm_sync_log.
    """
    since = datetime.now() - timedelta(days=period_days)
    try:
        with get_connection() as conn:
            count = conn.execute(
                """SELECT COUNT(*) FROM crm_sync_log
                   WHERE client_id = ? AND status = 'success' AND sent_at >= ?""",
                (client_id, since),
            ).fetchone()[0]
            row_last = conn.execute(
                """SELECT MAX(sent_at) AS last_push_at FROM crm_sync_log
                   WHERE client_id = ? AND status = 'success'""",
                (client_id,),
            ).fetchone()
        return {
            "success_count": count or 0,
            "last_push_at": row_last["last_push_at"] if row_last else None,
        }
    except Exception as e:
        logger.warning("[Cockpit] get_crm_export_stats: %s", e)
        return {"success_count": 0, "last_push_at": None}


def get_recent_activity(client_id: str, limit: int = 5) -> list[dict]:
    """
    Activité récente multi-source : appels, SMS entrants, envois CRM.
    Chaque événement : {"icon", "label", "name", "at"}.
    """
    events: list[dict] = []
    try:
        with get_connection() as conn:
            for row in conn.execute(
                """SELECT c.direction, l.prenom, l.nom, l.telephone, c.created_at AS at
                   FROM calls c LEFT JOIN leads l ON l.id = c.lead_id
                   WHERE c.client_id = ? ORDER BY c.created_at DESC LIMIT ?""",
                (client_id, limit),
            ).fetchall():
                direction = (row.get("direction") or "inbound")
                lbl = "Appel entrant capté" if direction == "inbound" else "Appel sortant"
                events.append({"icon": "📞", "label": lbl, "name": _lead_name(row), "at": row["at"]})

            for row in conn.execute(
                """SELECT l.prenom, l.nom, l.telephone, MAX(c.created_at) AS at
                   FROM conversations c LEFT JOIN leads l ON l.id = c.lead_id
                   WHERE c.client_id = ? AND c.canal = 'sms' AND c.role = 'user'
                   GROUP BY c.lead_id, l.prenom, l.nom, l.telephone
                   ORDER BY at DESC LIMIT ?""",
                (client_id, limit),
            ).fetchall():
                events.append({"icon": "💬", "label": "SMS reçu", "name": _lead_name(row), "at": row["at"]})

            for row in conn.execute(
                """SELECT l.prenom, l.nom, l.telephone, s.sent_at AS at
                   FROM crm_sync_log s LEFT JOIN leads l ON l.id = s.lead_id
                   WHERE s.client_id = ? AND s.status = 'success'
                   ORDER BY s.sent_at DESC LIMIT ?""",
                (client_id, limit),
            ).fetchall():
                events.append({"icon": "🔗", "label": "CRM alimenté", "name": _lead_name(row), "at": row["at"]})

    except Exception as e:
        logger.warning("[Cockpit] get_recent_activity: %s", e)

    events.sort(key=lambda e: e["at"] if e["at"] else datetime.min, reverse=True)
    return events[:limit]


def _lead_name(row) -> str:
    prenom = (row.get("prenom") or "").strip()
    nom = (row.get("nom") or "").strip()
    name = f"{prenom} {nom}".strip()
    return name or (row.get("telephone") or "Prospect")
