"""Helper click-to-call PropPilot — bouton Appeler standardisé."""
from __future__ import annotations

import streamlit as st


def _agent_phone_cached(client_id: str) -> str:
    """Retourne le numéro agent depuis la DB, mis en cache dans la session."""
    cache_key = f"_agent_phone_{client_id}"
    if cache_key not in st.session_state:
        try:
            from memory.database import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT phone FROM users WHERE id = %s LIMIT 1",
                    (client_id,),
                ).fetchone()
            st.session_state[cache_key] = (row.get("phone") or "") if row else ""
        except Exception:
            st.session_state[cache_key] = ""
    return st.session_state.get(cache_key) or ""


def render_call_button(
    *,
    lead_id: str,
    lead_phone: str | None,
    client_id: str,
    api_url: str,
    key: str,
    use_container_width: bool = True,
) -> None:
    """Bouton Appeler PropPilot avec états désactivé / actif.

    - numéro agent absent  → désactivé + tooltip "Configurez votre numéro…"
    - téléphone lead absent → désactivé + tooltip "Téléphone du lead indisponible"
    - tout OK              → bouton actif → POST /api/calls/outbound
    - appel échoue         → message d'erreur propre, jamais de détail technique
    """
    agent_phone = _agent_phone_cached(client_id)

    if not agent_phone:
        st.button(
            "Appeler",
            key=key,
            disabled=True,
            use_container_width=use_container_width,
            help="Configurez votre numéro dans Paramètres pour activer l'appel PropPilot.",
        )
        return

    if not lead_phone:
        st.button(
            "Appeler",
            key=key,
            disabled=True,
            use_container_width=use_container_width,
            help="Téléphone du lead indisponible.",
        )
        return

    if st.button("Appeler", key=key, use_container_width=use_container_width):
        try:
            import httpx
            resp = httpx.post(
                f"{api_url}/api/calls/outbound",
                json={"lead_id": lead_id, "agent_id": client_id, "lead_phone": lead_phone},
                headers={"Authorization": f"Bearer {st.session_state.get('token', '')}"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                st.success(f"Appel initié. {resp.json().get('message', '')}")
            else:
                st.error("L'appel n'a pas pu être lancé. Réessayez dans un instant.")
        except Exception:
            st.error("L'appel n'a pas pu être lancé. Réessayez dans un instant.")
