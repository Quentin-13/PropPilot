"""
Endpoint /admin/health — monitoring opérationnel PropPilot.

Sécurisé par X-Health-Key (même secret que /health) ou ADMIN_PASSWORD.
Retourne un JSON structuré avec :
  - Dernier appel/SMS capté
  - Extractions failed sur 24h
  - Queue SMS en retard
  - État DB et Twilio
  - Répartition leads par type (7j)
  - Liste des alertes actives

Job CRON séparé (_run_health_alert_job) vérifie toutes les 15 min et
envoie un SMS sur ADMIN_PHONE si une condition d'alerte est déclenchée.
"""
from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_PARIS_TZ_OFFSET = 2  # UTC+2 en été, approximation conservative pour les alertes


# ── Requêtes DB ───────────────────────────────────────────────────────────────

def _get_health_data(client_id: Optional[str] = None) -> dict:
    """
    Collecte toutes les métriques de santé du système.
    Si client_id est fourni, filtre sur cette agence ; sinon donne une vue globale.
    """
    from memory.database import get_connection
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = now_utc - timedelta(hours=24)
    cutoff_7d = now_utc - timedelta(days=7)

    result = {
        "checked_at": now_utc.isoformat(),
        "db_ok": False,
        "twilio_ok": False,
        "last_call_received_at": None,
        "last_sms_sent_at": None,
        "extractions_failed_24h": 0,
        "sms_queue_pending": 0,
        "sms_queue_max_delay_minutes": 0,
        "leads_by_type_7d": {"acheteur": 0, "vendeur": 0, "locataire": 0},
        "alerts": [],
    }

    try:
        with get_connection() as conn:
            result["db_ok"] = True

            # Dernier appel reçu
            row = conn.execute(
                "SELECT MAX(created_at) AS last_call FROM calls"
                + (" WHERE client_id = %s" if client_id else ""),
                (client_id,) if client_id else (),
            ).fetchone()
            if row and row["last_call"]:
                ts = row["last_call"]
                result["last_call_received_at"] = (
                    ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                )

            # Dernier SMS sortant (role='assistant' dans conversations)
            row = conn.execute(
                "SELECT MAX(created_at) AS last_sms FROM conversations WHERE role = 'assistant'"
                + (" AND client_id = %s" if client_id else ""),
                (client_id,) if client_id else (),
            ).fetchone()
            if row and row["last_sms"]:
                ts = row["last_sms"]
                result["last_sms_sent_at"] = (
                    ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                )

            # Extractions failed sur 24h
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM leads "
                "WHERE extraction_status = 'failed' AND updated_at >= %s"
                + (" AND client_id = %s" if client_id else ""),
                ((cutoff_24h, client_id) if client_id else (cutoff_24h,)),
            ).fetchone()
            result["extractions_failed_24h"] = row["cnt"] if row else 0

            # Queue SMS en retard (leads nurturing avec followup dépassé)
            row = conn.execute(
                "SELECT COUNT(*) AS cnt, "
                "COALESCE(EXTRACT(EPOCH FROM (NOW() - MIN(prochain_followup)))/60, 0) AS max_delay_min "
                "FROM leads "
                "WHERE statut = 'nurturing' AND prochain_followup IS NOT NULL "
                "AND prochain_followup < NOW()"
                + (" AND client_id = %s" if client_id else ""),
                (client_id,) if client_id else (),
            ).fetchone()
            if row:
                result["sms_queue_pending"] = row["cnt"] or 0
                result["sms_queue_max_delay_minutes"] = int(row["max_delay_min"] or 0)

            # Répartition leads par type sur 7j
            rows = conn.execute(
                "SELECT COALESCE(lead_type, 'acheteur') AS lead_type, COUNT(*) AS cnt "
                "FROM leads WHERE created_at >= %s"
                + (" AND client_id = %s" if client_id else "")
                + " GROUP BY 1",
                ((cutoff_7d, client_id) if client_id else (cutoff_7d,)),
            ).fetchall()
            for r in rows:
                lt = r["lead_type"]
                if lt in result["leads_by_type_7d"]:
                    result["leads_by_type_7d"][lt] = r["cnt"]

    except Exception as exc:
        result["db_ok"] = False
        logger.error("[AdminHealth] DB error: %s", exc)

    # Ping Twilio
    result["twilio_ok"] = _ping_twilio()

    # Calcul des alertes
    result["alerts"] = _compute_alerts(result)

    return result


def _ping_twilio() -> bool:
    try:
        from config.settings import get_settings
        s = get_settings()
        if not s.twilio_available:
            return True  # mock mode, pas d'alerte
        from twilio.rest import Client
        client = Client(s.twilio_account_sid, s.twilio_auth_token)
        client.api.accounts(s.twilio_account_sid).fetch()
        return True
    except Exception as exc:
        logger.warning("[AdminHealth] Twilio ping failed: %s", exc)
        return False


def _compute_alerts(data: dict) -> list[str]:
    alerts = []
    now_utc = datetime.now(timezone.utc)
    now_paris_hour = (now_utc.hour + _PARIS_TZ_OFFSET) % 24
    heures_ouvrées = 9 <= now_paris_hour < 19

    # Aucun appel/SMS depuis >6h en heures ouvrées
    if heures_ouvrées:
        cutoff_6h = datetime.now(timezone.utc) - timedelta(hours=6)

        def _is_stale(ts_str: Optional[str]) -> bool:
            if not ts_str:
                return True
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts < cutoff_6h
            except Exception:
                return True

        call_stale = _is_stale(data.get("last_call_received_at"))
        sms_stale = _is_stale(data.get("last_sms_sent_at"))
        if call_stale and sms_stale:
            alerts.append("NO_ACTIVITY_6H")

    # Plus de 3 extractions failed sur 24h
    if data.get("extractions_failed_24h", 0) > 3:
        alerts.append(f"EXTRACTION_FAILED_{data['extractions_failed_24h']}")

    # Queue SMS en retard de plus de 10 min
    if data.get("sms_queue_max_delay_minutes", 0) > 10:
        alerts.append(f"SMS_QUEUE_DELAYED_{data['sms_queue_max_delay_minutes']}MIN")

    # DB ou Twilio down
    if not data.get("db_ok"):
        alerts.append("DB_DOWN")
    if not data.get("twilio_ok"):
        alerts.append("TWILIO_DOWN")

    return alerts


def _check_no_vendeur_7j() -> list[str]:
    """
    Vérifie chaque agence active : aucun lead vendeur depuis 7 jours → alerte.
    Retourne la liste des client_id concernés.
    """
    try:
        from memory.database import get_connection
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        with get_connection() as conn:
            # Agences actives
            active = conn.execute(
                "SELECT id FROM users WHERE plan_active = TRUE"
            ).fetchall()
            alerted = []
            for row in active:
                cid = row["id"]
                cnt = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM leads "
                    "WHERE client_id = %s AND lead_type = 'vendeur' AND created_at >= %s",
                    (cid, cutoff),
                ).fetchone()
                if (cnt["cnt"] if cnt else 0) == 0:
                    alerted.append(cid)
            return alerted
    except Exception as exc:
        logger.error("[AdminHealth] _check_no_vendeur_7j error: %s", exc)
        return []


# ── Job CRON ──────────────────────────────────────────────────────────────────

def run_health_alert_job() -> None:
    """
    Vérifie la santé toutes les 15 min et envoie un SMS sur ADMIN_PHONE si alerte.
    Appelé par APScheduler.
    """
    from config.settings import get_settings
    s = get_settings()
    admin_phone = getattr(s, "admin_phone", None)
    if not admin_phone:
        logger.debug("[AdminHealth] ADMIN_PHONE non défini — alertes SMS désactivées")
        return

    data = _get_health_data()
    alerts = list(data.get("alerts", []))

    # Aucun lead vendeur sur 7j par agence active
    no_vendeur = _check_no_vendeur_7j()
    if no_vendeur:
        alerts.append(f"NO_VENDEUR_7D_{len(no_vendeur)}_AGENCES")

    if not alerts:
        logger.debug("[AdminHealth] Tout OK — aucune alerte")
        return

    _send_admin_sms(admin_phone, alerts, s)


def _send_admin_sms(admin_phone: str, alerts: list[str], settings) -> None:
    alert_str = ", ".join(alerts[:3])  # SMS court, max 3 alertes
    msg = f"[PropPilot ALERT] {alert_str}. Check /admin/health"
    if len(msg) > 160:
        msg = msg[:157] + "..."

    try:
        if not settings.twilio_available:
            logger.info("[MOCK] Admin SMS alert: %s → %s", admin_phone, msg)
            return
        from twilio.rest import Client
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            body=msg,
            from_=settings.twilio_sms_number,
            to=admin_phone,
        )
        logger.info("[AdminHealth] SMS alert envoyé → %s", admin_phone)
    except Exception as exc:
        logger.error("[AdminHealth] Impossible d'envoyer le SMS d'alerte: %s", exc)


# ── Endpoint FastAPI ───────────────────────────────────────────────────────────

@router.get("/health", tags=["admin"])
async def admin_health(request: Request):
    """
    Health check opérationnel — accès restreint (X-Health-Key ou X-Admin-Key).

    Retourne les métriques système + alertes actives.
    """
    from config.settings import get_settings
    s = get_settings()

    # Auth : X-Health-Key (même secret que /health) ou X-Admin-Key (admin_password)
    provided_health = request.headers.get("X-Health-Key", "")
    provided_admin = request.headers.get("X-Admin-Key", "")

    health_ok = bool(s.health_secret and hmac.compare_digest(provided_health, s.health_secret))
    admin_ok = bool(provided_admin and hmac.compare_digest(provided_admin, s.admin_password))

    if not health_ok and not admin_ok:
        raise HTTPException(status_code=401, detail="Authentification requise")

    # client_id optionnel pour filtrer par agence
    client_id = request.query_params.get("client_id")

    return _get_health_data(client_id=client_id)
