"""
Page Annonces — Générateur annonces SEO + historique.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
from datetime import datetime

from config.settings import get_settings
from memory.database import init_database, get_connection

init_database()
settings = get_settings()

st.set_page_config(page_title="Annonces — PropPilot", layout="wide", page_icon="🏠")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("🏠 Annonces")
st.markdown(f"**{agency_name}** · Forfait {tier}")

# ─── KPIs annonces ────────────────────────────────────────────────────────────

with get_connection() as conn:
    stats = conn.execute(
        """SELECT COUNT(*) as total,
                  COUNT(CASE WHEN images_urls != '[]' THEN 1 END) as avec_images,
                  COALESCE(AVG(prix), 0) as prix_moyen,
                  COALESCE(SUM(surface), 0) as surface_totale
           FROM listings WHERE client_id = ?""",
        (client_id,),
    ).fetchone()
    nb_listings = stats["total"] if stats else 0
    nb_avec_images = stats["avec_images"] if stats else 0
    prix_moyen = stats["prix_moyen"] if stats else 0
    surface_totale = stats["surface_totale"] if stats else 0

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Annonces générées", nb_listings)
with col2:
    st.metric("Avec visuels IA", nb_avec_images)
with col3:
    st.metric("Prix moyen", f"{int(prix_moyen):,}€".replace(",", " ") if prix_moyen else "—")
with col4:
    st.metric("Surface totale", f"{int(surface_totale):,} m²".replace(",", " ") if surface_totale else "—")

st.markdown("---")

# ─── Onglets ──────────────────────────────────────────────────────────────────

tab_gen, tab_history = st.tabs(["✍️ Générer une annonce", "📋 Historique"])

# ═══════════════════════════════════════════════════════════════════════════════
# ONGLET 1 : GÉNÉRATION ANNONCE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_gen:
    st.markdown("### Générer une annonce SEO complète")

    from agents.listing_generator import ListingGeneratorAgent

    with st.form("listing_form"):
        col_a, col_b = st.columns(2)

        with col_a:
            type_bien = st.selectbox(
                "Type de bien",
                ["Appartement", "Maison", "Studio", "Loft", "Duplex", "Villa", "Terrain", "Local commercial"],
            )
            adresse = st.text_input("Adresse complète", placeholder="12 rue de la Paix, 75001 Paris")
            surface = st.number_input("Surface habitable (m²)", min_value=5.0, max_value=1000.0, value=65.0, step=1.0)
            nb_pieces = st.number_input("Nombre de pièces", min_value=1, max_value=20, value=3)
            nb_chambres = st.number_input("Dont chambres", min_value=0, max_value=15, value=2)
            prix = st.number_input("Prix de vente (€)", min_value=0, value=320000, step=5000)

        with col_b:
            col_dpe1, col_dpe2 = st.columns(2)
            with col_dpe1:
                dpe_energie = st.selectbox("DPE Énergie", ["A", "B", "C", "D", "E", "F", "G"], index=3)
            with col_dpe2:
                dpe_ges = st.selectbox("DPE GES", ["A", "B", "C", "D", "E", "F", "G"], index=3)

            etage = st.text_input("Étage", value="2ème étage")
            exposition = st.selectbox("Exposition", ["sud", "nord", "est", "ouest", "sud-est", "sud-ouest", "nord-est", "nord-ouest"])
            etat = st.selectbox("État général", ["excellent", "bon", "à rafraîchir", "à rénover"])

            col_opt1, col_opt2 = st.columns(2)
            with col_opt1:
                parking = st.checkbox("Parking inclus")
                cave = st.checkbox("Cave / Cellier")
            with col_opt2:
                exterieur = st.text_input("Extérieur", placeholder="Terrasse 12m²")

        notes = st.text_area("Notes complémentaires", placeholder="Gardien, digicode, double vitrage, parquet ancien...")

        submitted_listing = st.form_submit_button("✍️ Générer l'annonce", type="primary")

    if submitted_listing:
        if not adresse:
            st.error("Veuillez renseigner l'adresse du bien.")
        else:
            with st.spinner("Génération de l'annonce en cours..."):
                agent = ListingGeneratorAgent(
                    client_id=client_id,
                    tier=tier,
                )
                result = agent.generate(
                    type_bien=type_bien,
                    adresse=adresse,
                    surface=surface,
                    nb_pieces=nb_pieces,
                    nb_chambres=nb_chambres,
                    dpe_energie=dpe_energie,
                    dpe_ges=dpe_ges,
                    prix=prix,
                    etage=etage,
                    exposition=exposition,
                    parking=parking,
                    cave=cave,
                    exterieur=exterieur,
                    etat=etat,
                    notes=notes,
                )

            if result.get("limit_reached"):
                st.error(f"⚠️ Quota annonces atteint ce mois : {result.get('message', '')}")
            elif result.get("success"):
                if result.get("mock"):
                    st.info("ℹ️ Mode démo — annonce générée sans clé API Anthropic.")

                st.success(f"✅ Annonce générée ! ID : {result.get('listing_id', '')[:12]}")

                # Titre + descriptions
                st.markdown(f"#### {result.get('titre', '')}")

                tab_desc_long, tab_desc_court, tab_legal, tab_seo, tab_compromis = st.tabs([
                    "Description longue", "Version courte", "Mentions légales", "SEO", "Pré-compromis"
                ])

                with tab_desc_long:
                    desc_longue = result.get("description_longue", "")
                    st.markdown(desc_longue)
                    st.download_button(
                        "📥 Copier la description",
                        data=desc_longue,
                        file_name=f"annonce_{result.get('listing_id', 'xxx')[:8]}.txt",
                        mime="text/plain",
                    )

                with tab_desc_court:
                    st.markdown(result.get("description_courte", ""))
                    points = result.get("points_forts", [])
                    if points:
                        st.markdown("**Points forts :**")
                        for pt in points:
                            st.markdown(f"• {pt}")

                with tab_legal:
                    st.markdown(result.get("mentions_legales", ""))

                with tab_seo:
                    mots = result.get("mots_cles_seo", [])
                    if mots:
                        st.markdown("**Mots-clés ciblés :**")
                        st.write(" · ".join(mots))

                with tab_compromis:
                    comp = result.get("compromis_prefill", {})
                    if comp:
                        st.markdown(f"**Référence :** {comp.get('reference', '')} | **Date :** {comp.get('date_redaction', '')}")
                        st.markdown(f"**Type acte :** {comp.get('type_acte', '')}")

                        bien = comp.get("bien", {})
                        prix_comp = comp.get("prix", {})
                        col_c1, col_c2 = st.columns(2)
                        with col_c1:
                            st.markdown("**Bien :**")
                            st.text(f"Type : {bien.get('type', '')}")
                            st.text(f"Adresse : {bien.get('adresse', '')}")
                            st.text(f"Surface Carrez : {bien.get('surface_loi_carrez', '')}")
                            st.text(f"DPE : {bien.get('mention_dpe', '')}")
                        with col_c2:
                            st.markdown("**Prix :**")
                            st.text(f"Net vendeur : {prix_comp.get('net_vendeur', 0):,}€".replace(",", " "))
                            st.text(f"Honoraires : {prix_comp.get('honoraires_agence_ttc', 0):,}€".replace(",", " "))
                            st.text(f"Prix FAI : {prix_comp.get('prix_fai', 0):,}€".replace(",", " "))
                            st.text(f"Honoraires % : {prix_comp.get('honoraires_pct', '')}")

                        st.markdown("**Conditions suspensives :**")
                        for cs in comp.get("conditions_suspensives", []):
                            st.markdown(f"• {cs}")

                        st.caption(comp.get("mention_legale_hoguet", ""))

                        # À compléter
                        champs = comp.get("champs_a_completer", [])
                        if champs:
                            with st.expander("📋 Champs à compléter avant signature"):
                                for c in champs:
                                    st.markdown(f"☐ {c}")


# ═══════════════════════════════════════════════════════════════════════════════
# ONGLET 2 : HISTORIQUE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.markdown("### Historique des annonces")

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, type_bien, adresse, surface, nb_pieces, prix, dpe,
                      titre, description_courte, points_forts, images_urls,
                      created_at
               FROM listings
               WHERE client_id = ?
               ORDER BY created_at DESC
               LIMIT 100""",
            (client_id,),
        ).fetchall()

    if not rows:
        st.info("Aucune annonce générée. Utilisez l'onglet **Générer une annonce** pour commencer.")
    else:
        # Tableau résumé
        table_data = []
        for r in rows:
            prix_fmt = f"{int(r['prix']):,}€".replace(",", " ") if r["prix"] else "—"
            has_images = r["images_urls"] != "[]" and r["images_urls"]
            table_data.append({
                "_id": r["id"],
                "Type": r["type_bien"],
                "Adresse": r["adresse"][:40] + "…" if len(r["adresse"] or "") > 40 else r["adresse"] or "—",
                "Surface": f"{r['surface']:.0f} m²" if r["surface"] else "—",
                "Pièces": r["nb_pieces"] or "—",
                "Prix": prix_fmt,
                "DPE": r["dpe"] or "—",
                "Visuels": "✅" if has_images else "—",
                "Date": (r["created_at"] or "")[:10],
            })

        df_listings = pd.DataFrame(table_data)
        display_cols = ["Type", "Adresse", "Surface", "Pièces", "Prix", "DPE", "Visuels", "Date"]

        selected_listing = st.dataframe(
            df_listings[display_cols],
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="listings_table",
        )

        # Détail annonce sélectionnée
        sel_rows = selected_listing.selection.rows if selected_listing.selection else []
        if sel_rows:
            idx = sel_rows[0]
            listing_id = table_data[idx]["_id"]
            selected_row = next((r for r in rows if r["id"] == listing_id), None)

            if selected_row:
                st.markdown("---")
                st.markdown(f"### {selected_row['titre'] or 'Annonce'}")
                st.caption(f"ID : {listing_id} | Créée le {(selected_row['created_at'] or '')[:16]}")

                tab_d1, tab_d2, tab_d3 = st.tabs(["📝 Description", "🏷️ Points forts & SEO", "🖼️ Visuels"])

                with tab_d1:
                    st.markdown(selected_row["description_courte"] or "—")
                    st.markdown("---")
                    st.markdown(f"**Description longue :**")
                    with get_connection() as conn2:
                        full = conn2.execute(
                            "SELECT description_longue, mentions_legales FROM listings WHERE id = ?",
                            (listing_id,),
                        ).fetchone()
                    if full:
                        st.markdown(full["description_longue"] or "")
                        if full["mentions_legales"]:
                            st.caption(f"*{full['mentions_legales']}*")

                with tab_d2:
                    points_raw = selected_row["points_forts"] or "[]"
                    try:
                        points = json.loads(points_raw)
                    except Exception:
                        points = []
                    if points:
                        for pt in points:
                            st.markdown(f"✅ {pt}")

                    mots_raw = selected_row["mots_cles_seo"] or "[]"
                    try:
                        mots = json.loads(mots_raw)
                    except Exception:
                        mots = []
                    if mots:
                        st.markdown("**Mots-clés SEO :**")
                        st.write(" · ".join(mots))

                with tab_d3:
                    images_raw = selected_row["images_urls"] or "[]"
                    try:
                        images_list = json.loads(images_raw)
                    except Exception:
                        images_list = []
                    if images_list:
                        img_cols = st.columns(min(len(images_list), 3))
                        for i, img_path in enumerate(images_list):
                            with img_cols[i % 3]:
                                p = Path(img_path)
                                if p.exists() and p.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                                    st.image(str(p), use_column_width=True)
                                else:
                                    st.caption(f"Image : {p.name}")
                    else:
                        st.info("Aucun visuel généré pour cette annonce.")
