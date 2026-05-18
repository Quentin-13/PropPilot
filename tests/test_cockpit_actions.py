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


def test_get_detected_info_stats_compte_leads_distincts():
    """
    Les compteurs utilisent COUNT(DISTINCT lead_id), pas COUNT(*).
    Un même lead avec 3 extractions budget doit être compté 1 fois.
    """
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 2
    _row.get = lambda k, d=0: 2

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_stats("client-001", period_days=7)

    sql = mock_conn.execute.call_args[0][0]
    assert "DISTINCT" in sql, "SQL doit utiliser COUNT(DISTINCT lead_id)"
    assert "COUNT(*)" not in sql, "SQL ne doit pas utiliser COUNT(*) pour les infos détectées"


# ─── Tests get_detected_info_detail ──────────────────────────────────────────

def test_get_detected_info_detail_structure():
    """Retourne une liste de dicts avec les clés attendues."""
    from dashboard.lib.cockpit import get_detected_info_detail

    _fake_row = {
        "lead_id": "lead-1", "prenom": "Alice", "nom": "Dupont",
        "telephone": "+33600000001", "score": 20,
        "budget_min": 200000, "budget_max": 300000,
        "zone_geographique": None, "type_bien": None,
        "financement": None, "motivation": None,
        "points_attention": None, "extracted_at": "2026-05-01 10:00:00",
    }
    mock_row = MagicMock()
    mock_row.__iter__ = MagicMock(return_value=iter(_fake_row.items()))
    mock_row.keys = MagicMock(return_value=_fake_row.keys())

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [_fake_row]
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        rows = get_detected_info_detail("client-001", "budgets", period_days=7)

    assert isinstance(rows, list)
    assert len(rows) == 1
    assert "lead_id" in rows[0]
    assert "budget_min" in rows[0]


def test_get_detected_info_detail_categorie_inconnue():
    """Une catégorie inconnue retourne une liste vide sans requête DB."""
    from dashboard.lib.cockpit import get_detected_info_detail

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn) as mock_gc:
        rows = get_detected_info_detail("client-001", "categorie_inconnue", period_days=7)

    assert rows == []
    mock_gc.assert_not_called()


def test_get_detected_info_detail_etat_vide():
    """Aucune extraction sur la période → liste vide."""
    from dashboard.lib.cockpit import get_detected_info_detail

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        rows = get_detected_info_detail("client-001", "budgets", period_days=7)

    assert rows == []


def test_get_detected_info_detail_passe_client_id():
    """client_id est transmis à la requête SQL (isolation multi-tenant)."""
    from dashboard.lib.cockpit import get_detected_info_detail

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_detail("client-SECRET", "zones", period_days=30)

    params = mock_conn.execute.call_args[0][1]
    assert "client-SECRET" in params


def test_get_detected_info_detail_exception_retourne_liste_vide():
    """Erreur DB → retourne [] sans lever d'exception."""
    from dashboard.lib.cockpit import get_detected_info_detail

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("connexion perdue")
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        rows = get_detected_info_detail("client-001", "motivations", period_days=7)

    assert rows == []


# ─── Tests anti-régression ambiguïté colonne ─────────────────────────────────

def test_detail_sql_prefixe_ce_pour_colonnes_ambigues():
    """
    financement, motivation et type_bien existent dans leads ET dans
    conversation_extractions. La requête de détail (qui joint les deux tables)
    doit utiliser l'alias 'ce.' pour éviter 'column reference is ambiguous'.
    """
    from dashboard.lib.cockpit import get_detected_info_detail

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    for cat, col in (
        ("financements", "ce.financement"),
        ("motivations",  "ce.motivation"),
        ("types_bien",   "ce.type_bien"),
    ):
        with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
            get_detected_info_detail("client-001", cat, period_days=30)

        sql = mock_conn.execute.call_args[0][0]
        assert col in sql, (
            f"Catégorie '{cat}' : SQL doit contenir '{col}' pour éviter l'ambiguïté "
            f"(la colonne existe aussi dans la table leads)"
        )


def test_detail_stats_utilisent_meme_filtre_financements():
    """
    Le filtre SQL pour 'financements' dans get_detected_info_detail doit contenir
    le même prédicat que dans get_detected_info_stats : IS NOT NULL et <> '{}'.
    """
    from dashboard.lib.cockpit import get_detected_info_detail

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_detail("client-001", "financements", period_days=30)

    sql = mock_conn.execute.call_args[0][0]
    assert "financement" in sql
    assert "IS NOT NULL" in sql
    # Le filtre exclut le financement vide
    assert "'{}'" in sql or "!= '{}'" in sql or "<> '{}'" in sql


def test_detail_periode_fallback_30_jours():
    """La fonction get_detected_info_detail utilise 30 jours par défaut."""
    import inspect
    from dashboard.lib.cockpit import get_detected_info_detail

    sig = inspect.signature(get_detected_info_detail)
    default_period = sig.parameters["period_days"].default
    assert default_period == 30, (
        f"Fallback attendu : 30 jours, obtenu : {default_period}"
    )


def test_detail_financements_non_vide_retourne_lignes():
    """
    Un financement non vide est compté et retourné par le détail.
    Scénario : 1 extraction avec financement = {"type_pret": "PTZ"}.
    """
    from dashboard.lib.cockpit import get_detected_info_detail

    _fake_row = {
        "lead_id": "lead-fin-1", "prenom": "Paul", "nom": "Moreau",
        "telephone": "+33611223344", "score": 15,
        "budget_min": None, "budget_max": None,
        "zone_geographique": None, "type_bien": None,
        "financement": '{"type_pret": "PTZ", "apport": 30000}',
        "motivation": None, "points_attention": None,
        "extracted_at": "2026-05-10 14:00:00",
    }
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [_fake_row]
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        rows = get_detected_info_detail("client-001", "financements", period_days=30)

    assert len(rows) == 1
    assert rows[0]["lead_id"] == "lead-fin-1"


# ─── Tests Task 4 : filtres renforcés et cohérence ───────────────────────────

def test_stats_sql_filtre_budget_strictement_positif():
    """
    Le filtre budgets exige budget_min > 0 ou budget_max > 0.
    Un lead avec budget_min=0 et budget_max=0 ne doit pas être compté.
    Vérifie que le SQL généré contient la condition > 0.
    """
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 0
    _row.get = lambda k, d=0: 0

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_stats("client-001", period_days=7)

    sql = mock_conn.execute.call_args[0][0]
    assert "budget_min > 0" in sql or "budget_max > 0" in sql, (
        "Filtre budgets doit exiger > 0, pas seulement IS NOT NULL"
    )


def test_stats_sql_filtre_points_attention_tableau_non_vide():
    """
    Le filtre objections doit rejeter points_attention=[].
    Vérifie que le SQL utilise jsonb_array_length(...) > 0.
    """
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 0
    _row.get = lambda k, d=0: 0

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_stats("client-001", period_days=7)

    sql = mock_conn.execute.call_args[0][0]
    assert "jsonb_array_length" in sql, (
        "Filtre objections doit utiliser jsonb_array_length pour exclure []"
    )


def test_stats_sql_filtre_financement_vide_exclu():
    """
    Le filtre financements doit rejeter financement={}.
    Vérifie que le SQL contient <> '{}' ou != '{}' (JSONB vide exclu).
    """
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 0
    _row.get = lambda k, d=0: 0

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_stats("client-001", period_days=7)

    sql = mock_conn.execute.call_args[0][0]
    assert "<> '{}'" in sql or "!= '{}'" in sql, (
        "Filtre financements doit exclure le JSONB vide '{}'"
    )


def test_stats_sql_exclut_valeurs_generiques():
    """
    Les filtres zones, types_bien et motivations excluent les valeurs génériques
    ('inconnu', 'autre', 'non renseigné', 'n/a', …).
    Vérifie que le SQL généré contient NOT IN avec ces valeurs.
    """
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 0
    _row.get = lambda k, d=0: 0

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_stats("client-001", period_days=7)

    sql = mock_conn.execute.call_args[0][0]
    assert "NOT IN" in sql, "SQL doit exclure les valeurs génériques avec NOT IN"
    assert "inconnu" in sql.lower(), "SQL doit exclure 'inconnu'"
    assert "autre" in sql.lower(), "SQL doit exclure 'autre' (types_bien et motivations)"
    assert "non renseigné" in sql.lower(), "SQL doit exclure 'non renseigné'"


def test_stats_lead_unique_plusieurs_extractions_compte_une_fois():
    """
    Un même lead avec 3 extractions budget doit être compté 1 fois (DISTINCT).
    Ce test vérifie le comportement quand la DB retourne 1 (déjà dédupliqué côté SQL).
    """
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 1
    _row.get = lambda k, d=0: 1

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        stats = get_detected_info_stats("client-001", period_days=7)

    assert stats["budgets"] == 1, "Lead compté deux fois au lieu d'une"
    sql = mock_conn.execute.call_args[0][0]
    assert "COUNT(DISTINCT" in sql, "SQL doit déduplicuer avec COUNT(DISTINCT lead_id)"


def test_stats_filtre_periode_extraction():
    """
    Seules les extractions dans la fenêtre temporelle sont prises en compte.
    Vérifie que le SQL contient extracted_at >= ?.
    """
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 0
    _row.get = lambda k, d=0: 0

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_stats("client-001", period_days=7)

    sql = mock_conn.execute.call_args[0][0]
    params = mock_conn.execute.call_args[0][1]
    assert "extracted_at" in sql, "SQL doit filtrer par extracted_at"
    # La date seuil doit être dans les paramètres (2e param après client_id)
    assert len(params) >= 2, "SQL doit recevoir client_id + date seuil en paramètres"


def test_coherence_stats_detail_utilisent_meme_filtre():
    """
    Stats et détail utilisent _CATEGORY_FILTER comme source de vérité unique.
    Pour chaque catégorie, les deux fonctions doivent inclure le même prédicat
    dans leur SQL (garantit que compteur == len(détail)).
    """
    from dashboard.lib.cockpit import (
        _CATEGORY_FILTER, _FILTER_KEYS, _no_alias,
        get_detected_info_stats, get_detected_info_detail,
    )

    mock_cursor_stats = MagicMock()
    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 0
    _row.get = lambda k, d=0: 0
    mock_cursor_stats.fetchone.return_value = _row

    mock_cursor_detail = MagicMock()
    mock_cursor_detail.fetchall.return_value = []

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    for cat in _FILTER_KEYS:
        expected_fragment = _no_alias(_CATEGORY_FILTER[cat])[:30]  # 30 premiers chars suffisent

        mock_conn.execute.return_value = mock_cursor_stats
        with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
            get_detected_info_stats("client-coh", period_days=30)
        sql_stats = mock_conn.execute.call_args[0][0]

        mock_conn.execute.return_value = mock_cursor_detail
        with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
            get_detected_info_detail("client-coh", cat, period_days=30)
        sql_detail = mock_conn.execute.call_args[0][0]

        assert expected_fragment in sql_stats, (
            f"Catégorie '{cat}': fragment '{expected_fragment}' absent du SQL stats"
        )
        assert expected_fragment in sql_detail, (
            f"Catégorie '{cat}': fragment '{expected_fragment}' absent du SQL détail"
        )


def test_stats_isolation_client_id():
    """
    get_detected_info_stats transmet client_id en paramètre SQL.
    Un appel pour client-A ne peut pas retourner les données de client-B.
    """
    from dashboard.lib.cockpit import get_detected_info_stats

    _row = MagicMock()
    _row.__getitem__ = lambda s, k: 0
    _row.get = lambda k, d=0: 0

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        get_detected_info_stats("client-ALPHA", period_days=7)

    params = mock_conn.execute.call_args[0][1]
    assert "client-ALPHA" in params, "client_id doit être passé en paramètre SQL (pas interpolé)"


def test_detail_sousrequete_garantit_coherence():
    """
    get_detected_info_detail utilise une sous-requête IN pour sélectionner les leads
    où AU MOINS UNE extraction passe le filtre — garantit cohérence avec stats.
    Vérifie que le SQL contient un sous-SELECT avec DISTINCT lead_id.
    """
    from dashboard.lib.cockpit import get_detected_info_detail

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    for cat in ("budgets", "zones", "financements", "objections"):
        with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
            get_detected_info_detail("client-001", cat, period_days=30)

        sql = mock_conn.execute.call_args[0][0]
        assert "IN (" in sql or "lead_id IN" in sql, (
            f"Catégorie '{cat}' : SQL doit utiliser une sous-requête IN pour garantir la cohérence"
        )
        assert "SELECT DISTINCT lead_id" in sql or "DISTINCT lead_id" in sql, (
            f"Catégorie '{cat}' : sous-requête doit dédupliquer les leads"
        )


def test_get_detected_info_matrix_structure():
    """
    get_detected_info_matrix retourne une liste de dicts
    avec les 8 clés attendues (lead_id, display_name, has_* × 6).
    """
    from dashboard.lib.cockpit import get_detected_info_matrix

    _fake_row = {
        "lead_id": "lead-1",
        "display_name": "Alice Dupont",
        "has_budget": True,
        "has_zone": False,
        "has_type_bien": False,
        "has_motivation": True,
        "has_financement": False,
        "has_points_attention": False,
        "extracted_at": "2026-05-01 10:00:00",
    }
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [_fake_row]
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        matrix = get_detected_info_matrix("client-001", period_days=30)

    assert isinstance(matrix, list)
    assert len(matrix) == 1
    row = matrix[0]
    expected_keys = {
        "lead_id", "display_name",
        "has_budget", "has_zone", "has_type_bien",
        "has_motivation", "has_financement", "has_points_attention",
        "extracted_at",
    }
    assert expected_keys.issubset(set(row.keys())), (
        f"Clés manquantes : {expected_keys - set(row.keys())}"
    )


def test_get_detected_info_matrix_exception_retourne_liste_vide():
    """Erreur DB → retourne [] sans lever d'exception."""
    from dashboard.lib.cockpit import get_detected_info_matrix

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("connexion perdue")
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("dashboard.lib.cockpit.get_connection", return_value=mock_conn):
        result = get_detected_info_matrix("client-001", period_days=30)

    assert result == []


# ─── Tests resolve_period_days — propagation période dashboard → détail ────────

def test_resolve_period_days_7_jours():
    """dash_period='7 jours' → detail utilise 7 jours."""
    from dashboard.lib.cockpit import resolve_period_days
    assert resolve_period_days("7 jours") == 7


def test_resolve_period_days_30_jours():
    """dash_period='30 jours' → detail utilise 30 jours."""
    from dashboard.lib.cockpit import resolve_period_days
    assert resolve_period_days("30 jours") == 30


def test_resolve_period_days_depuis_le_debut():
    """dash_period='Depuis le début' → detail utilise 3650 jours (comportement attendu)."""
    from dashboard.lib.cockpit import resolve_period_days
    assert resolve_period_days("Depuis le début") == 3650


def test_resolve_period_days_absence_fallback_30():
    """Absence de dash_period → fallback 30 jours."""
    from dashboard.lib.cockpit import resolve_period_days
    assert resolve_period_days(None) == 30
    assert resolve_period_days("") == 30
    assert resolve_period_days("valeur_inconnue") == 30


def test_resolve_period_days_fallback_personnalisable():
    """Le fallback peut être surchargé (tasks.py utilise fallback=7)."""
    from dashboard.lib.cockpit import resolve_period_days
    assert resolve_period_days(None, fallback=7) == 7
    assert resolve_period_days("valeur_inconnue", fallback=7) == 7


# ─── Tests format_lead_status — labels UI propres ─────────────────────────────

def test_format_lead_status_en_qualification():
    from dashboard.utils.lead_formatters import format_lead_status
    assert format_lead_status("en_qualification") == "À qualifier"


def test_format_lead_status_rdv_booke():
    from dashboard.utils.lead_formatters import format_lead_status
    assert format_lead_status("rdv_booke") == "RDV planifié"


def test_format_lead_status_mandat():
    from dashboard.utils.lead_formatters import format_lead_status
    assert format_lead_status("mandat") == "Opportunité avancée"


def test_format_lead_status_mapping_complet():
    """Tous les statuts LeadStatus ont un label défini (pas de fallback sur valeur brute)."""
    from dashboard.utils.lead_formatters import format_lead_status, _LEAD_STATUS_LABELS
    known_statuts = [
        "entrant", "en_qualification", "qualifie", "rdv_propose",
        "rdv_booke", "mandat", "vendu", "perdu", "nurturing",
    ]
    for s in known_statuts:
        label = format_lead_status(s)
        assert label in _LEAD_STATUS_LABELS.values(), (
            f"'{s}' → '{label}' n'est pas dans les labels définis"
        )
        assert "_" not in label, f"Label '{label}' contient encore un underscore"


def test_format_lead_status_valeur_inconnue_pas_crash():
    """Une valeur inconnue retourne la valeur brute — jamais crash."""
    from dashboard.utils.lead_formatters import format_lead_status
    assert format_lead_status("statut_inexistant") == "statut_inexistant"
    assert format_lead_status(None) == "—"
    assert format_lead_status("") == "—"


# ─── Tests filter_leads_by_search ─────────────────────────────────────────────

def _make_lead_fixture(**kwargs):
    """Crée un Lead de test avec des valeurs par défaut."""
    from memory.models import Lead, Canal, ProjetType, LeadStatus
    defaults = dict(
        client_id="client-001",
        prenom="", nom="", telephone="", email="",
        localisation="", budget="", motivation="", resume="",
        notes_agent="", financement="", timeline="",
        source=Canal.SMS, projet=ProjetType.ACHAT, statut=LeadStatus.ENTRANT,
    )
    defaults.update(kwargs)
    return Lead(**defaults)


def test_search_par_prenom():
    """Recherche 'Claire' retourne Claire Martin."""
    from dashboard.utils.lead_formatters import filter_leads_by_search
    claire = _make_lead_fixture(prenom="Claire", nom="Martin")
    other  = _make_lead_fixture(prenom="Thomas", nom="Dupont")
    result = filter_leads_by_search([claire, other], {}, "Claire")
    assert len(result) == 1
    assert result[0].prenom == "Claire"


def test_search_par_ville():
    """Recherche 'Toulouse' retourne les leads localisés à Toulouse."""
    from dashboard.utils.lead_formatters import filter_leads_by_search
    toulouse = _make_lead_fixture(prenom="Alice", localisation="Toulouse centre")
    paris    = _make_lead_fixture(prenom="Bob",   localisation="Paris 15e")
    result = filter_leads_by_search([toulouse, paris], {}, "Toulouse")
    assert len(result) == 1
    assert result[0].localisation == "Toulouse centre"


def test_search_dans_resume():
    """Recherche 'travaux' retourne les leads dont le résumé contient 'travaux'."""
    from dashboard.utils.lead_formatters import filter_leads_by_search
    lead_travaux = _make_lead_fixture(prenom="Marc", resume="Besoin de travaux importants avant achat")
    lead_propre  = _make_lead_fixture(prenom="Julie", resume="Appartement clé en main")
    result = filter_leads_by_search([lead_travaux, lead_propre], {}, "travaux")
    assert len(result) == 1
    assert result[0].prenom == "Marc"


def test_search_telephone_partiel():
    """Recherche partielle sur téléphone retourne le bon lead."""
    from dashboard.utils.lead_formatters import filter_leads_by_search
    lead = _make_lead_fixture(prenom="Sophie", telephone="+33612345678")
    other = _make_lead_fixture(prenom="Luc", telephone="+33698765432")
    result = filter_leads_by_search([lead, other], {}, "1234")
    assert len(result) == 1
    assert result[0].prenom == "Sophie"


def test_search_vide_retourne_tous():
    """Une recherche vide retourne tous les leads."""
    from dashboard.utils.lead_formatters import filter_leads_by_search
    leads = [_make_lead_fixture(prenom=n) for n in ["Alice", "Bob", "Carole"]]
    assert filter_leads_by_search(leads, {}, "") == leads
    assert filter_leads_by_search(leads, {}, "   ") == leads


def test_search_isolation_client_id():
    """filter_leads_by_search ne filtre pas par client_id (déjà fait en DB)
    — mais les résultats n'incluent que les leads passés en paramètre."""
    from dashboard.utils.lead_formatters import filter_leads_by_search
    lead_a = _make_lead_fixture(client_id="client-A", prenom="Eve", localisation="Lyon")
    lead_b = _make_lead_fixture(client_id="client-B", prenom="Frank", localisation="Lille")
    # On ne passe que les leads de client-A
    result = filter_leads_by_search([lead_a], {}, "Lyon")
    assert len(result) == 1
    assert result[0].client_id == "client-A"
    # lead-B n'est jamais dans les résultats car il n'est pas dans la liste
    result_b = filter_leads_by_search([lead_a], {}, "Lille")
    assert result_b == []


def test_search_dans_next_action():
    """Recherche dans next_action_label et next_action_reason via le dict next_actions."""
    from dashboard.utils.lead_formatters import filter_leads_by_search
    lead = _make_lead_fixture(prenom="Paul")
    na = {lead.id: {"next_action_label": "Rappeler — objection budget", "next_action_reason": "Craint les travaux"}}
    result_label  = filter_leads_by_search([lead], na, "budget")
    result_reason = filter_leads_by_search([lead], na, "travaux")
    result_absent = filter_leads_by_search([lead], na, "hypothèque")
    assert len(result_label) == 1
    assert len(result_reason) == 1
    assert result_absent == []


# ─── Tests search_leads_by_text — recherche SQL sans limite 200 ────────────────

def test_search_leads_by_text_limite_superieure_200():
    """La limite par défaut de search_leads_by_text est > 200 (pas limitée aux 200 premiers)."""
    import inspect
    from memory.lead_repository import search_leads_by_text
    default_limit = inspect.signature(search_leads_by_text).parameters["limit"].default
    assert default_limit > 200, f"Limite attendue > 200, obtenu {default_limit}"


def test_search_leads_by_text_utilise_ilike():
    """La requête SQL contient ILIKE pour la recherche texte case-insensitive."""
    from memory.lead_repository import search_leads_by_text
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    with patch("memory.lead_repository.get_connection", return_value=mock_conn):
        search_leads_by_text("client-001", "Toulouse")
    sql = mock_conn.execute.call_args[0][0]
    assert "ILIKE" in sql, "SQL doit utiliser ILIKE pour la recherche case-insensitive"


def test_search_leads_by_text_client_id_parametre():
    """client_id est transmis comme paramètre SQL — pas interpolé dans la chaîne."""
    from memory.lead_repository import search_leads_by_text
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    with patch("memory.lead_repository.get_connection", return_value=mock_conn):
        search_leads_by_text("client-SECRET", "Paris")
    params = mock_conn.execute.call_args[0][1]
    assert "client-SECRET" in params, "client_id doit être un paramètre SQL (isolation multi-tenant)"
    sql = mock_conn.execute.call_args[0][0]
    assert "client-SECRET" not in sql, "client_id ne doit pas être interpolé dans le SQL"


def test_search_leads_by_text_query_encapsulee():
    """La valeur de recherche est encapsulée en %query% dans les paramètres."""
    from memory.lead_repository import search_leads_by_text
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    with patch("memory.lead_repository.get_connection", return_value=mock_conn):
        search_leads_by_text("client-001", "Claire")
    params = mock_conn.execute.call_args[0][1]
    assert "%Claire%" in params, "La requête doit être encapsulée en %Claire% pour le ILIKE"


def test_search_leads_by_text_couvre_champs_principaux():
    """La requête SQL couvre les 12 champs prioritaires demandés."""
    from memory.lead_repository import search_leads_by_text
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    with patch("memory.lead_repository.get_connection", return_value=mock_conn):
        search_leads_by_text("client-001", "test")
    sql = mock_conn.execute.call_args[0][0]
    for col in ("prenom", "nom", "telephone", "email", "localisation",
                "budget", "motivation", "resume", "notes_agent",
                "next_action_label", "next_action_reason"):
        assert col in sql, f"Colonne '{col}' absente de la requête SQL"
