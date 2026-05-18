"""
Tests — dashboard/lib/cockpit.py

Couverture :
  1. Aucune action → liste vide (état vide)
  2. Tri chaud > tiède > froid
  3. Action marquée comme faite disparaît du cockpit
  4. Action recalculée réapparaît si next_action_computed_at > last_action_completed_at
  5. Isolation client_id : actions d'un autre client invisibles
  6. mark_action_done ne modifie pas next_action_label
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_lead(
    id: str,
    client_id: str,
    score: int,
    next_action_label: str | None = "Rappeler",
    next_action_reason: str | None = "Lead chaud.",
    next_action_computed_at: datetime | None = None,
    last_action_completed_at: datetime | None = None,
    statut: str = "entrant",
) -> dict:
    return {
        "id": id,
        "client_id": client_id,
        "prenom": "Test",
        "nom": "Lead",
        "telephone": "+33600000001",
        "score": score,
        "statut": statut,
        "next_action_label": next_action_label,
        "next_action_priority": "haute" if score >= 18 else "moyenne",
        "next_action_reason": next_action_reason,
        "next_action_computed_at": next_action_computed_at or datetime.now() - timedelta(minutes=10),
        "last_action_completed_at": last_action_completed_at,
        "updated_at": datetime.now(),
    }


def _mock_conn_returning(rows: list[dict]):
    """Retourne un context manager de connexion mockée avec fetchall() → rows."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.fetchone.return_value = [len(rows)]

    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


# ─── Test 1 : aucune action → état vide ──────────────────────────────────────

def test_aucune_action_retourne_liste_vide():
    from dashboard.lib.cockpit import get_priority_actions

    mock_conn = _mock_conn_returning([])
    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        result = get_priority_actions("client-001")

    assert result == []


# ─── Test 2 : tri chaud > tiède > froid ──────────────────────────────────────

def test_tri_chaud_tiede_froid():
    """
    La requête SQL trie par CASE WHEN score >= 18 THEN 0 ...
    On vérifie que get_priority_actions respecte l'ordre retourné par la DB.
    """
    from dashboard.lib.cockpit import get_priority_actions

    row_froid = _make_lead("lead-3", "client-001", score=5)
    row_tiede = _make_lead("lead-2", "client-001", score=14)
    row_chaud = _make_lead("lead-1", "client-001", score=20)

    # La DB retourne déjà dans l'ordre trié (chaud, tiède, froid)
    mock_conn = _mock_conn_returning([row_chaud, row_tiede, row_froid])
    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        result = get_priority_actions("client-001")

    assert len(result) == 3
    assert result[0]["score"] == 20  # chaud en premier
    assert result[1]["score"] == 14  # tiède au milieu
    assert result[2]["score"] == 5   # froid en dernier


# ─── Test 3 : action marquée comme faite → disparaît ─────────────────────────

def test_action_faite_disparait():
    """
    Un lead dont last_action_completed_at >= next_action_computed_at
    n'est PAS retourné par get_priority_actions.
    La requête SQL filtre ce cas — ici on vérifie que la requête est
    bien appelée avec le bon filtre en inspectant l'appel execute().
    """
    from dashboard.lib.cockpit import get_priority_actions

    mock_conn = _mock_conn_returning([])  # DB retourne vide : le lead a été filtré
    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        result = get_priority_actions("client-001")

    assert result == []
    sql_called = mock_conn.execute.call_args[0][0]
    assert "last_action_completed_at < next_action_computed_at" in sql_called


# ─── Test 4 : action recalculée réapparaît ───────────────────────────────────

def test_action_recalculee_reapparait():
    """
    Si next_action_computed_at > last_action_completed_at
    → le lead doit réapparaître dans les actions prioritaires.
    """
    from dashboard.lib.cockpit import get_priority_actions

    completed_at = datetime.now() - timedelta(hours=2)
    recomputed_at = datetime.now() - timedelta(minutes=5)  # plus récent

    row = _make_lead(
        "lead-1", "client-001", score=20,
        next_action_computed_at=recomputed_at,
        last_action_completed_at=completed_at,
    )

    # La DB retourne ce lead car next_action_computed_at > last_action_completed_at
    mock_conn = _mock_conn_returning([row])
    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        result = get_priority_actions("client-001")

    assert len(result) == 1
    assert result[0]["id"] == "lead-1"


# ─── Test 5 : isolation client_id ────────────────────────────────────────────

def test_isolation_client_id():
    """
    Chaque appel passe client_id comme paramètre — les leads d'autres clients
    ne peuvent pas être retournés.
    """
    from dashboard.lib.cockpit import get_priority_actions

    row_client_a = _make_lead("lead-A", "client-A", score=20)

    mock_conn = _mock_conn_returning([row_client_a])
    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        result_a = get_priority_actions("client-A")
        params_a = mock_conn.execute.call_args[0][1]

    assert params_a[0] == "client-A"

    # Appel pour client-B : la DB ne retourne rien (isolation effective)
    mock_conn_b = _mock_conn_returning([])
    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn_b):
        result_b = get_priority_actions("client-B")
        params_b = mock_conn_b.execute.call_args[0][1]

    assert params_b[0] == "client-B"
    assert result_b == []


# ─── Test 6 : mark_action_done ne touche pas next_action_* ───────────────────

def test_mark_action_done_preserve_next_action():
    """
    mark_action_done met à jour UNIQUEMENT last_action_completed_at.
    Le SQL exécuté ne doit pas modifier next_action_label, next_action_reason,
    next_action_computed_at, next_action_priority ni next_action_deadline.
    """
    from dashboard.lib.cockpit import mark_action_done

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        result = mark_action_done("lead-1", "client-001")

    assert result is True
    sql = mock_conn.execute.call_args[0][0]
    assert "last_action_completed_at" in sql
    assert "next_action_label" not in sql
    assert "next_action_reason" not in sql
    assert "next_action_computed_at" not in sql
    assert "next_action_priority" not in sql
    assert "next_action_deadline" not in sql
    # Vérifie l'isolation client_id dans le WHERE
    assert "client_id" in sql


# ─── Test 7 : get_cockpit_kpis retourne les 4 clés ───────────────────────────

def test_get_cockpit_kpis_structure():
    from dashboard.lib.cockpit import get_cockpit_kpis

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [3]

    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        kpis = get_cockpit_kpis("client-001")

    assert set(kpis.keys()) == {"chauds", "tiedes", "nouveaux", "actions"}
    assert all(isinstance(v, int) for v in kpis.values())


# ─── Test 8 : get_dashboard_kpis — structure et 6 clés ───────────────────────

def test_get_dashboard_kpis_structure():
    from dashboard.lib.cockpit import get_dashboard_kpis

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [4]

    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        kpis = get_dashboard_kpis("client-001", period_days=7)

    expected_keys = {"appels_captes", "sms_captes", "leads_crees",
                     "leads_enrichis", "envois_crm", "actions_recommandees"}
    assert set(kpis.keys()) == expected_keys
    assert all(isinstance(v, int) for v in kpis.values())


def test_sms_captes_compte_messages_pas_leads():
    """
    SMS captés = COUNT(*) de messages entrants, pas COUNT(DISTINCT lead_id).
    Scénario : lead A a 3 SMS, lead B a 2 SMS → KPI = 5.
    """
    from dashboard.lib.cockpit import get_dashboard_kpis

    # Séquence de retours fetchone() pour les 6 requêtes exécutées :
    # appels=0, sms=5, leads_crees=0, leads_enrichis=0, envois_crm=0, actions=0
    _side_effects = [
        MagicMock(**{"__getitem__": lambda s, k: 0}),  # appels
        MagicMock(**{"__getitem__": lambda s, k: 5}),  # sms → 5 messages
        MagicMock(**{"__getitem__": lambda s, k: 0}),  # leads_crees
        MagicMock(**{"__getitem__": lambda s, k: 0}),  # leads_enrichis
        MagicMock(**{"__getitem__": lambda s, k: 0}),  # envois_crm
        MagicMock(**{"__getitem__": lambda s, k: 0}),  # actions
    ]
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = _side_effects

    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        kpis = get_dashboard_kpis("client-001", period_days=7)

    assert kpis["sms_captes"] == 5

    # Vérifie que le SQL utilise COUNT(*) et non COUNT(DISTINCT lead_id)
    sms_call = mock_conn.execute.call_args_list[1]  # 2e requête = SMS
    sql = sms_call[0][0]
    assert "COUNT(*)" in sql
    assert "DISTINCT" not in sql


def test_get_dashboard_kpis_etat_vide():
    """Aucune donnée → tous les KPIs à 0."""
    from dashboard.lib.cockpit import get_dashboard_kpis

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [0]

    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        kpis = get_dashboard_kpis("client-vide", period_days=7)

    assert all(v == 0 for v in kpis.values())


def test_get_dashboard_kpis_passe_client_id():
    """client_id est bien transmis à chaque requête SQL."""
    from dashboard.lib.cockpit import get_dashboard_kpis

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [0]
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_dashboard_kpis("client-XYZ", period_days=7)

    for call_args in mock_conn.execute.call_args_list:
        params = call_args[0][1] if len(call_args[0]) > 1 else ()
        if params:
            assert "client-XYZ" in params, f"client_id absent des params : {params}"


# ─── Test 9 : get_crm_export_stats lit crm_sync_log ──────────────────────────

def test_get_crm_export_stats_structure():
    from dashboard.lib.cockpit import get_crm_export_stats

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = MagicMock(**{"__getitem__": lambda s, k: 5 if k == 0 else None})
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        stats = get_crm_export_stats("client-001", period_days=7)

    assert "success_count" in stats
    assert "last_push_at" in stats
    # Vérifie que crm_sync_log est bien la table interrogée
    calls_sql = [c[0][0] for c in mock_conn.execute.call_args_list]
    assert any("crm_sync_log" in sql for sql in calls_sql)


def test_get_crm_export_stats_etat_vide():
    """Pas de push CRM → success_count=0, last_push_at=None."""
    from dashboard.lib.cockpit import get_crm_export_stats

    _none_row = MagicMock()
    _none_row.__getitem__ = lambda s, k: None
    _none_row.get = lambda k, d=None: None

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _none_row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        stats = get_crm_export_stats("client-vide", period_days=7)

    assert stats["last_push_at"] is None


# ─── Test 10 : get_detected_info_stats — structure ───────────────────────────

def test_get_detected_info_stats_structure():
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 3
    _row.get = lambda k, d=0: 3

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        stats = get_detected_info_stats("client-001", period_days=7)

    expected_keys = {"budgets", "zones", "types_bien", "motivations", "financements", "objections"}
    assert set(stats.keys()) == expected_keys


def test_get_detected_info_stats_exception_retourne_zeros():
    """Si la DB lève une erreur, retourne des zéros proprement."""
    from dashboard.lib.cockpit import get_detected_info_stats

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("table introuvable")
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        stats = get_detected_info_stats("client-001", period_days=7)

    assert all(v == 0 for v in stats.values())
