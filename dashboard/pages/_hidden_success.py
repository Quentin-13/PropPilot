"""
Page Succès — Confirmation de souscription Stripe.
Affiche un message de bienvenue selon le forfait et redirige vers le dashboard après 5 secondes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Bienvenue — PropPilot", layout="centered", page_icon="🎉")

from dashboard.auth_ui import require_auth
require_auth(require_active_plan=False)

# ─── Paramètres URL ───────────────────────────────────────────────────────────

plan = st.query_params.get("plan", "votre forfait")

# Mise à jour session après paiement réussi
if plan in ("Indépendant", "Starter", "Pro", "Elite"):
    st.session_state["plan"] = plan
    st.session_state["plan_active"] = True
mock = st.query_params.get("mock", "false") == "true"

# ─── Messages par forfait ─────────────────────────────────────────────────────

WELCOME_MESSAGES: dict[str, str] = {
    "Indépendant": (
        "Votre forfait **Indépendant** est maintenant actif.\n\n"
        "Vos agents IA qualifient déjà vos premiers leads. "
        "Profitez de **600 min voix** et **3 000 follow-ups SMS** ce mois."
    ),
    "Starter": (
        "Votre forfait **Starter** est maintenant actif.\n\n"
        "3 utilisateurs, 1 500 min voix, 8 000 SMS — tout est prêt. "
        "Vos leads ne seront plus jamais sans réponse."
    ),
    "Pro": (
        "Votre forfait **Pro** est maintenant actif.\n\n"
        "6 utilisateurs, 3 000 min voix, 15 000 SMS — vos agents IA travaillent 24h/24. "
        "Votre CA va décoller."
    ),
    "Elite": (
        "Bienvenue dans l'**Elite** PropPilot ! 🏆\n\n"
        "Voix, SMS et leads illimités. White-label, agents custom et account manager dédié. "
        "Votre account manager vous contactera dans les 24h."
    ),
}

message = WELCOME_MESSAGES.get(plan, f"Votre forfait **{plan}** est maintenant actif !")

# ─── Affichage ────────────────────────────────────────────────────────────────

_, center, _ = st.columns([1, 3, 1])
with center:
    st.markdown("""
    <div style="text-align: center; padding: 40px 0 20px 0;">
        <div style="font-size: 64px;">🎉</div>
        <h1 style="color: #1a3a5c; margin: 16px 0 8px 0;">Paiement confirmé !</h1>
    </div>
    """, unsafe_allow_html=True)

    st.success(message)

    if mock:
        st.caption("ℹ️ Mode démonstration — aucun paiement réel effectué.")

    st.markdown("")
    st.markdown("""
    <div style="text-align: center; color: #64748b; font-size: 14px;">
        Redirection automatique vers le tableau de bord dans <strong>5 secondes</strong>…
    </div>
    """, unsafe_allow_html=True)

    st.markdown("")
    if st.button("Aller au tableau de bord maintenant →", use_container_width=True, type="primary"):
        st.switch_page("app.py")

# ─── Auto-redirect JavaScript ─────────────────────────────────────────────────

components.html("""
<script>
    setTimeout(function() {
        window.parent.location.href = "/";
    }, 5000);
</script>
""", height=0)
