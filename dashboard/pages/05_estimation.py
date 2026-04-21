"""
Page Estimer un bien — Thomas analyse le marché en quelques secondes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from config.settings import get_settings

st.set_page_config(
    page_title="Estimer un bien — PropPilot",
    page_icon="📊",
    layout="wide",
)

from dashboard.auth_ui import require_auth, render_sidebar_logout, require_non_demo
require_auth()
require_non_demo()
render_sidebar_logout()

settings = get_settings()

st.title("📊 Estimer un bien")
st.caption(
    "Thomas analyse le marché local et vous donne "
    "une estimation argumentée en quelques secondes."
)
st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    type_bien = st.selectbox(
        "Type de bien",
        ["Appartement", "Maison", "Studio",
         "Loft", "Local commercial", "Terrain"],
    )
    surface = st.number_input(
        "Surface (m²)", min_value=1, max_value=2000, value=60,
    )
    nb_pieces = st.number_input(
        "Nombre de pièces", min_value=1, max_value=20, value=3,
    )
    etage = st.number_input(
        "Étage (0 = RDC)", min_value=0, max_value=30, value=2,
    )

with col2:
    ville = st.text_input(
        "Ville / Quartier",
        placeholder="Toulouse, Saint-Aubin",
    )
    etat = st.selectbox(
        "État du bien",
        ["Bon état", "Refait à neuf", "Travaux à prévoir", "Neuf"],
    )
    dpe = st.selectbox(
        "DPE (diagnostic énergétique)",
        ["A", "B", "C", "D", "E", "F", "G", "Non communiqué"],
    )
    points_forts = st.text_area(
        "Caractéristiques notables",
        placeholder="Terrasse, parking, vue dégagée, cave...",
        height=80,
    )

st.markdown("")
estimer = st.button(
    "📊 Estimer avec Thomas",
    type="primary",
    use_container_width=True,
)

if estimer:
    if not ville:
        st.error("Veuillez indiquer la ville.")
    else:
        with st.spinner("Thomas analyse le marché..."):
            try:
                import anthropic

                client = anthropic.Anthropic(
                    api_key=settings.anthropic_api_key
                )

                prompt = f"""Tu es Thomas, expert en estimation immobilière française.
Fournis une estimation argumentée pour ce bien :

Type : {type_bien}
Surface : {surface} m²
Pièces : {nb_pieces}
Étage : {etage}
Ville/Quartier : {ville}
État : {etat}
DPE : {dpe}
Caractéristiques : {points_forts}

Fournis :
1. Une fourchette de prix réaliste (min/max)
2. Un prix au m² estimé vs marché local
3. Les 3 principaux facteurs qui influencent cette estimation
4. Un conseil de positionnement prix (sous le marché / dans le marché / premium)

Base-toi sur ta connaissance du marché immobilier français en 2026.
Sois précis et professionnel."""

                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=600,
                    messages=[{"role": "user", "content": prompt}],
                )

                estimation = response.content[0].text

                st.success("✅ Estimation générée !")
                st.markdown("---")
                st.markdown("### Estimation Thomas")
                st.markdown(estimation)
                st.markdown("---")
                st.caption(
                    "⚠️ Cette estimation est indicative et basée sur les données de marché "
                    "disponibles. Une visite terrain reste indispensable pour une valorisation précise."
                )

            except Exception as e:
                st.error(f"Erreur lors de l'estimation : {e}")
