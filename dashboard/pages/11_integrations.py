"""
Page Intégrations — Sources de leads et webhook unique.
"""
from __future__ import annotations

import io
import csv
import streamlit as st

st.set_page_config(page_title="Mes Intégrations — PropPilot", layout="wide")


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _get_auth() -> tuple[str, str, str]:
    """Retourne (token, user_id, tier) depuis la session."""
    token = st.session_state.get("token", "")
    user_id = st.session_state.get("user_id", "")
    tier = st.session_state.get("tier", "Starter")
    return token, user_id, tier


def _api(method: str, path: str, token: str, **kwargs):
    """Appel API PropPilot."""
    import requests
    from config.settings import get_settings
    base = get_settings().api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = getattr(requests, method)(f"{base}{path}", headers=headers, timeout=15, **kwargs)
        return resp.json() if resp.content else {}
    except Exception as e:
        return {"error": str(e)}


# ─── Vérification auth ────────────────────────────────────────────────────────

token, user_id, tier = _get_auth()
if not token or not user_id:
    st.warning("Connectez-vous depuis la page d'accueil.")
    st.stop()

if st.session_state.get("is_demo", False):
    st.info("Cette fonctionnalité n'est pas disponible en mode démo.")
    st.stop()


# ─── Titre ────────────────────────────────────────────────────────────────────

st.title("🔗 Mes Intégrations")
st.markdown("Connectez vos sources de leads à PropPilot pour une qualification automatique.")

# ─── Webhook unique ───────────────────────────────────────────────────────────

st.header("Votre URL Webhook unique")

PRODUCTION_URL = "https://proppilot-production.up.railway.app"
webhook_url = f"{PRODUCTION_URL}/webhooks/{user_id}/leads"

st.markdown(
    "Utilisez cette URL dans tous vos outils externes pour envoyer automatiquement "
    "vos leads vers PropPilot."
)
st.code(webhook_url, language=None)
st.caption("Cette URL est unique à votre compte. Ne la partagez pas publiquement.")

# ─── Sources de leads ─────────────────────────────────────────────────────────

st.header("Sources de leads")

col1, col2 = st.columns(2)
col3, col4 = st.columns(2)

# ── Card LeBonCoin Pro ────────────────────────────────────────────────────────
with col1:
    with st.container(border=True):
        st.subheader("🟠 LeBonCoin Pro")
        st.caption("Statut : Import CSV disponible")
        st.markdown("""
**Étapes :**
1. Connectez-vous à votre espace LeBonCoin Pro
2. Exportez vos leads en CSV (Leads → Exporter)
3. Importez le fichier ci-dessous
        """)
        lbc_file = st.file_uploader(
            "Importer CSV LeBonCoin",
            type=["csv"],
            key="lbc_csv",
            help="Colonnes attendues : nom, prénom, téléphone, email",
        )
        st.caption("Colonnes attendues : nom, prénom, téléphone, email")
        if st.button("Importer", key="btn_lbc") and lbc_file:
            with st.spinner("Import en cours…"):
                result = _api(
                    "post",
                    "/api/leads/import",
                    token,
                    files={"file": (lbc_file.name, lbc_file.getvalue(), "text/csv")},
                    data={"source": "leboncoin"},
                )
            if result.get("error"):
                st.error(f"Erreur : {result['error']}")
            else:
                imported = result.get("imported", 0)
                errors = result.get("errors", [])
                st.success(f"✅ {imported} lead(s) importé(s)")
                if errors:
                    st.warning(f"⚠️ {len(errors)} ligne(s) ignorée(s) : {', '.join(errors[:3])}")

# ── Card SeLoger Pro ─────────────────────────────────────────────────────────
with col2:
    with st.container(border=True):
        st.subheader("🔵 SeLoger Pro")
        st.caption("Statut : Webhook automatique")
        st.markdown("""
**Configuration webhook SeLoger :**

1. Connectez-vous à votre espace SeLoger Pro
2. Allez dans **Paramètres → Notifications → Webhooks**
3. Cliquez sur **Ajouter un webhook**
4. Collez l'URL ci-dessous dans le champ URL
5. Sélectionnez l'événement **Nouveau contact**
6. Cliquez sur **Enregistrer**
        """)
        st.code(webhook_url, language=None)
        st.caption("SeLoger enverra automatiquement chaque nouveau lead vers PropPilot.")

# ── Card Hektor CRM ───────────────────────────────────────────────────────────
with col3:
    with st.container(border=True):
        st.subheader("🔜 Hektor CRM")
        st.markdown(
            "<span style='background:#eee;padding:4px 10px;border-radius:8px;"
            "color:#888;font-size:0.85em'>Intégration en cours</span>",
            unsafe_allow_html=True,
        )
        st.markdown("""
L'intégration native Hektor CRM est en cours de développement.

Elle permettra la synchronisation bidirectionnelle de vos leads, mandats et RDV.

**Disponible : T2 2026**
        """)

# ── Card Import CSV Manuel ────────────────────────────────────────────────────
with col4:
    with st.container(border=True):
        st.subheader("📄 Import CSV Manuel")
        st.caption("Pour toute autre source")
        st.markdown("""
**Importez vos leads depuis n'importe quelle source :**
- Extraction CRM
- Export Excel converti en CSV
- Liste prospects manuelle
        """)
        manual_file = st.file_uploader(
            "Importer CSV",
            type=["csv"],
            key="manual_csv",
            help="Colonnes attendues : nom, prénom, téléphone, email",
        )
        st.caption("Colonnes attendues : nom, prénom, téléphone, email")

        source_manuelle = st.text_input("Source (ex: salon immobilier, prospection terrain)", key="source_manuelle")

        if st.button("Importer", key="btn_manual") and manual_file:
            with st.spinner("Import en cours…"):
                result = _api(
                    "post",
                    "/api/leads/import",
                    token,
                    files={"file": (manual_file.name, manual_file.getvalue(), "text/csv")},
                    data={"source": source_manuelle or "manuel"},
                )
            if result.get("error"):
                st.error(f"Erreur : {result['error']}")
            else:
                imported = result.get("imported", 0)
                errors = result.get("errors", [])
                st.success(f"✅ {imported} lead(s) importé(s)")
                if errors:
                    st.warning(f"⚠️ {len(errors)} ligne(s) ignorée(s) : {', '.join(errors[:3])}")


# ─── Derniers leads reçus ─────────────────────────────────────────────────────

st.header("Derniers leads reçus")

try:
    from memory.database import get_connection
    from memory.auth import verify_token

    payload = verify_token(token)
    if payload:
        db_user_id = payload["user_id"]
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT prenom, nom, source, created_at, statut, score
                   FROM leads
                   WHERE client_id = ?
                   ORDER BY created_at DESC
                   LIMIT 10""",
                (db_user_id,),
            ).fetchall()

        if rows:
            import pandas as pd
            data = []
            for r in rows:
                data.append({
                    "Prénom": r["prenom"] or "—",
                    "Source": r["source"] or "—",
                    "Date": str(r["created_at"])[:16] if r["created_at"] else "—",
                    "Statut": r["statut"] or "—",
                    "Score": r["score"] or 0,
                })
            st.dataframe(
                pd.DataFrame(data),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("Aucun lead reçu pour l'instant. Configurez une source ci-dessus.")
except Exception as e:
    st.info("Connectez-vous pour voir vos derniers leads.")
