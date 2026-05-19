"""
Tests — logique deep-link page SMS (dashboard/pages/04_sms.py).

La logique est simulée ici sans Streamlit. Les 4 scénarios critiques :
  1. Conversation déjà ouverte + query param valide différent → sélection remplacée
  2. Query param identique au dernier traité → pas de retraitement (anti-boucle)
  3. Query param invalide (lead inexistant) → sélection existante conservée
  4. Lead_id appartenant à un autre client → sélection existante conservée
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── Simulation de la logique deeplink ────────────────────────────────────────

def _apply_deeplink(
    qp_lead_id: str,
    session_state: dict,
    client_id: str,
    get_thread_fn,
) -> bool:
    """
    Miroir exact du bloc deep-link dans dashboard/pages/04_sms.py.
    Retourne True si la conversation a été changée.
    """
    if qp_lead_id and qp_lead_id != session_state.get("last_deeplink_lead_id"):
        try:
            if get_thread_fn(client_id, qp_lead_id):
                session_state["selected_lead_id"] = qp_lead_id
                session_state["last_deeplink_lead_id"] = qp_lead_id
                session_state["sms_thread_opened_at"] = time.time()
                return True
        except Exception:
            pass
    return False


def _valid_thread(client_id, lead_id):
    """Simule get_thread_messages → thread valide."""
    return {"lead": {"id": lead_id}, "messages": []}


def _no_thread(client_id, lead_id):
    """Simule get_thread_messages → aucun résultat (lead absent ou mauvais client)."""
    return None


# ─── 1. Conversation déjà ouverte + lead_id valide différent ─────────────────

def test_deeplink_replaces_existing_selection():
    """
    Un agent a lead-A ouvert. Il reçoit une notif pour lead-B.
    Le deep link doit switcher sur lead-B même si lead-A était sélectionné.
    """
    session = {
        "selected_lead_id": "lead-A",
        "last_deeplink_lead_id": "",
    }
    changed = _apply_deeplink("lead-B", session, "client-1", _valid_thread)

    assert changed is True
    assert session["selected_lead_id"] == "lead-B"
    assert session["last_deeplink_lead_id"] == "lead-B"


# ─── 2. Même lead_id déjà traité → pas de retraitement ───────────────────────

def test_deeplink_no_reprocess_same_lead_id():
    """
    Si last_deeplink_lead_id == qp_lead_id, ne pas retraiter.
    Évite la boucle rerun → apply → rerun → …
    """
    session = {
        "selected_lead_id": "lead-B",
        "last_deeplink_lead_id": "lead-B",
    }
    get_thread_fn = MagicMock(return_value={"lead": {}, "messages": []})

    changed = _apply_deeplink("lead-B", session, "client-1", get_thread_fn)

    assert changed is False
    get_thread_fn.assert_not_called()
    assert session["selected_lead_id"] == "lead-B"


# ─── 3. Lead_id invalide → sélection existante conservée ─────────────────────

def test_deeplink_invalid_lead_id_keeps_existing():
    """
    Un lead_id inexistant ou introuvable : la sélection courante ne bouge pas.
    """
    session = {
        "selected_lead_id": "lead-A",
        "last_deeplink_lead_id": "",
    }
    changed = _apply_deeplink("lead-fantome", session, "client-1", _no_thread)

    assert changed is False
    assert session["selected_lead_id"] == "lead-A"
    assert session.get("last_deeplink_lead_id") == ""


# ─── 4. Lead d'un autre client → sélection existante conservée ───────────────

def test_deeplink_other_client_lead_ignored():
    """
    get_thread_messages retourne None pour les leads d'un autre client.
    La sélection existante doit rester intacte.
    """
    session = {
        "selected_lead_id": "lead-A",
        "last_deeplink_lead_id": "",
    }

    def _other_client_thread(client_id, lead_id):
        # Simule l'isolation : le lead n'appartient pas à client-1
        if client_id == "client-1" and lead_id == "lead-other-client":
            return None
        return {"lead": {"id": lead_id}, "messages": []}

    changed = _apply_deeplink("lead-other-client", session, "client-1", _other_client_thread)

    assert changed is False
    assert session["selected_lead_id"] == "lead-A"


# ─── 5. Pas de query param → aucune action ───────────────────────────────────

def test_deeplink_empty_qp_no_action():
    session = {"selected_lead_id": "lead-A", "last_deeplink_lead_id": ""}
    get_thread_fn = MagicMock()
    changed = _apply_deeplink("", session, "client-1", get_thread_fn)

    assert changed is False
    get_thread_fn.assert_not_called()
    assert session["selected_lead_id"] == "lead-A"


# ─── 6. get_thread_messages lève une exception → pas de crash ────────────────

def test_deeplink_exception_in_get_thread_no_crash():
    session = {"selected_lead_id": "lead-A", "last_deeplink_lead_id": ""}

    def _boom(client_id, lead_id):
        raise RuntimeError("DB unreachable")

    changed = _apply_deeplink("lead-new", session, "client-1", _boom)

    assert changed is False
    assert session["selected_lead_id"] == "lead-A"
