"""
Page Calendrier — Connexion Google Calendar OAuth + RDV bookés automatiquement.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import streamlit as st

from config.settings import get_settings

st.set_page_config(page_title="Calendrier — PropPilot", layout="wide", page_icon="📅")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth(require_active_plan=True)
render_sidebar_logout()

settings = get_settings()
token = st.session_state.get("token", "")
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("📅 Calendrier & RDV")
st.markdown(f"**{agency_name}** · Rendez-vous bookés automatiquement")


def _headers() -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _base() -> str:
    return settings.api_url.rstrip("/")


# ─── Gestion des query params post-OAuth ──────────────────────────────────────

if st.query_params.get("calendar_connected") == "true":
    st.success("✅ Google Calendar connecté avec succès !")
    st.session_state["calendar_connected"] = True
    # Nettoie le query param
    st.query_params.clear()

if st.query_params.get("calendar_error"):
    err = st.query_params.get("calendar_error")
    st.error(f"Erreur de connexion Google Calendar : {err}")
    st.query_params.clear()

# ─── Statut connexion ─────────────────────────────────────────────────────────

st.markdown("### 🔗 Connexion Google Calendar")

try:
    status_resp = httpx.get(f"{_base()}/api/calendar/status", headers=_headers(), timeout=5.0)
    status_data = status_resp.json() if status_resp.is_success else {}
    is_connected = status_data.get("connected", False)
    is_mock = status_data.get("mock", False)
except Exception:
    is_connected = st.session_state.get("calendar_connected", False)
    is_mock = False

col_status, col_btn = st.columns([3, 2])
with col_status:
    if is_connected:
        badge = " *(mode démo)*" if is_mock else ""
        st.markdown(
            f'<div style="background:#d1fae5;color:#065f46;padding:12px 18px;border-radius:8px;'
            f'font-weight:600;">✅ Google Calendar connecté{badge}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:#fee2e2;color:#991b1b;padding:12px 18px;border-radius:8px;'
            'font-weight:600;">⚠️ Google Calendar non connecté</div>',
            unsafe_allow_html=True,
        )

with col_btn:
    st.markdown("")
    btn_label = "🔄 Reconnecter Google Calendar" if is_connected else "🔗 Connecter Google Calendar"
    if st.button(btn_label, use_container_width=True, type="primary"):
        with st.spinner("Génération du lien OAuth…"):
            try:
                resp = httpx.get(f"{_base()}/api/calendar/auth", headers=_headers(), timeout=8.0)
                data = resp.json()
                auth_url = data.get("auth_url")
                if auth_url:
                    st.markdown(
                        f'<meta http-equiv="refresh" content="0; url={auth_url}">',
                        unsafe_allow_html=True,
                    )
                    st.info(
                        f"Redirection vers Google… "
                        f"[Cliquez ici si ça ne démarre pas]({auth_url})"
                    )
                else:
                    st.error("Impossible d'obtenir l'URL d'autorisation.")
            except Exception as e:
                st.error(f"Erreur : {e}")

st.markdown("---")

# ─── Créneaux disponibles ─────────────────────────────────────────────────────

st.markdown("### 🕐 Créneaux disponibles (7 prochains jours)")

if st.button("🔄 Actualiser les créneaux", key="refresh_slots"):
    st.cache_data.clear()

try:
    slots_resp = httpx.get(
        f"{_base()}/api/calendar/slots",
        headers=_headers(),
        params={"days_ahead": 7},
        timeout=8.0,
    )
    if slots_resp.is_success:
        slots_data = slots_resp.json()
        slots = slots_data.get("slots", [])
        if slots:
            import pandas as pd
            df = pd.DataFrame([{"Créneau": s["label"]} for s in slots[:10]])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"{slots_data['count']} créneaux disponibles au total.")
        else:
            st.info("Aucun créneau disponible pour les 7 prochains jours.")
    else:
        st.warning("Impossible de charger les créneaux.")
except Exception as e:
    st.warning(f"Créneaux non disponibles : {e}")

st.markdown("---")

# ─── RDV bookés automatiquement cette semaine ──────────────────────────────────────

st.markdown("### 📋 RDV bookés automatiquement cette semaine")

try:
    from datetime import datetime, timedelta
    from memory.database import get_connection

    week_start = datetime.now() - timedelta(days=datetime.now().weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT c.created_at, l.prenom, l.nom, l.telephone, l.email,
                      l.projet, l.localisation, c.resume
               FROM calls c
               JOIN leads l ON c.lead_id = l.id
               WHERE c.rdv_booke = 1
                 AND c.created_at >= ?
               ORDER BY c.created_at DESC
               LIMIT 50""",
            (week_start.isoformat(),),
        ).fetchall()

    if rows:
        import pandas as pd
        data = []
        for r in rows:
            created = r["created_at"]
            date_str = created.strftime("%d/%m %H:%M") if hasattr(created, "strftime") else str(created)[:16]
            data.append({
                "Date": date_str,
                "Lead": f"{r['prenom'] or ''} {r['nom'] or ''}".strip() or "—",
                "Téléphone": r["telephone"] or "—",
                "Projet": r["projet"] or "—",
                "Localisation": r["localisation"] or "—",
            })
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.success(f"✅ **{len(rows)} RDV** bookés automatiquement cette semaine.")
    else:
        st.info("Aucun RDV booké cette semaine.")

except Exception as e:
    st.info(f"Données non disponibles (base de données hors ligne) : {e}")

st.markdown("---")
st.markdown(
    "<div style='color:#94a3b8;font-size:12px;text-align:center;'>"
    "Les RDV sont proposés automatiquement par Marc lors des échanges SMS de qualification."
    "</div>",
    unsafe_allow_html=True,
)
