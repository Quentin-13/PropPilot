"""
Page Générer une annonce — Hugo rédige en 30 secondes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from config.settings import get_settings

st.set_page_config(
    page_title="Générer une annonce — PropPilot",
    page_icon="📝",
    layout="wide",
)

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

settings = get_settings()

st.title("📝 Générer une annonce")
st.caption(
    "Hugo rédige une annonce professionnelle "
    "pour votre bien en 30 secondes."
)
st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    type_bien = st.selectbox(
        "Type de bien",
        ["Appartement", "Maison", "Studio",
         "Loft", "Local commercial",
         "Terrain", "Immeuble"],
    )
    surface = st.number_input(
        "Surface (m²)", min_value=1, max_value=2000, value=50,
    )
    nb_pieces = st.number_input(
        "Nombre de pièces", min_value=1, max_value=20, value=3,
    )
    prix = st.number_input(
        "Prix (€)", min_value=0, max_value=5_000_000,
        value=200_000, step=5_000,
    )

with col2:
    ville = st.text_input(
        "Ville / Quartier",
        placeholder="Toulouse, Carmes",
    )
    points_forts = st.text_area(
        "Points forts du bien",
        placeholder="Lumineux, vue dégagée, proche transports, terrasse 15m²...",
        height=100,
    )
    travaux = st.selectbox(
        "État du bien",
        ["Bon état", "Refait à neuf", "Travaux à prévoir", "Neuf"],
    )

st.markdown("")
generer = st.button(
    "✨ Générer l'annonce avec Hugo",
    type="primary",
    use_container_width=True,
)

if generer:
    if not ville:
        st.error("Veuillez indiquer la ville.")
    else:
        with st.spinner("Hugo rédige votre annonce..."):
            try:
                import anthropic

                client = anthropic.Anthropic(
                    api_key=settings.anthropic_api_key
                )

                prompt = f"""Tu es Hugo, expert en rédaction d'annonces immobilières françaises.
Rédige une annonce professionnelle et attractive pour ce bien :

Type : {type_bien}
Surface : {surface} m²
Pièces : {nb_pieces}
Prix : {prix:,}€
Ville/Quartier : {ville}
État : {travaux}
Points forts : {points_forts}

L'annonce doit :
- Avoir un titre accrocheur
- Faire 150-200 mots
- Mettre en valeur les points forts
- Utiliser un ton professionnel et chaleureux
- Terminer par un appel à l'action
- Être prête à copier-coller sur LBC ou SeLoger"""

                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=600,
                    messages=[{"role": "user", "content": prompt}],
                )

                annonce = response.content[0].text

                st.success("✅ Annonce générée !")
                st.markdown("---")
                st.markdown("### Votre annonce")
                st.text_area(
                    "Copiez-collez cette annonce :",
                    value=annonce,
                    height=300,
                )
                st.caption(
                    "💡 Vous pouvez modifier l'annonce avant de la publier."
                )

            except Exception as e:
                st.error(f"Erreur lors de la génération : {e}")
