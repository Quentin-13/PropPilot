"""
Tests — synchronisation leads.* depuis les extractions.

Couvre :
1. _apply_extraction_to_lead (unitaire) — champs mis à jour, règles de non-régression
2. save_sms_extraction (intégration) — met bien à jour leads.* après INSERT
3. save_call_extraction (non-régression) — INSERT dans conversation_extractions toujours fait
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ─── Fixture commune ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _force_testing(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_conn(score: int = 0, motivation: str = "") -> MagicMock:
    """Connexion mock : SELECT leads renvoie score/motivation, INSERT renvoie id=42."""
    conn = MagicMock()

    def _execute(sql, params=None):
        cur = MagicMock()
        sql_s = sql.strip()
        if "FROM calls" in sql_s:
            cur.fetchone.return_value = {"lead_id": "lead-001"}
        elif "FROM leads" in sql_s:
            cur.fetchone.return_value = {"score": score, "motivation": motivation}
        elif "INSERT INTO conversation_extractions" in sql_s:
            cur.fetchone.return_value = {"id": 42}
        return cur

    conn.execute.side_effect = _execute
    return conn


def _update_calls(conn: MagicMock) -> list:
    return [c for c in conn.execute.call_args_list if "UPDATE leads" in c[0][0]]


def _insert_calls(conn: MagicMock) -> list:
    return [c for c in conn.execute.call_args_list if "INSERT INTO conversation_extractions" in c[0][0]]


def _mock_ctx(conn):
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Tests unitaires — _apply_extraction_to_lead
# ═══════════════════════════════════════════════════════════════════════════════

def test_apply_updates_score_when_higher():
    """Score mis à jour si la nouvelle valeur est plus haute."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead, _SCORE_MAP

    conn = _make_conn(score=2)
    data = CallExtractionData(score_qualification="chaud")  # chaud → midpoint plage chaud

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = _update_calls(conn)
    assert len(updates) == 1
    params = updates[0][0][1]
    assert _SCORE_MAP["chaud"] in params


def test_apply_does_not_downgrade_score():
    """Score non rétrogradé : si score actuel=21 et extraction=froid, on garde 21."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead, _SCORE_MAP

    conn = _make_conn(score=21)  # score chaud actuel
    data = CallExtractionData(score_qualification="froid")  # froid → 5 < 21

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = _update_calls(conn)
    assert len(updates) == 1
    params = updates[0][0][1]
    assert _SCORE_MAP["froid"] not in params  # le score froid ne doit pas apparaître


def test_apply_skips_none_fields():
    """Les champs None dans l'extraction ne génèrent pas de SET correspondant."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead

    conn = _make_conn()
    data = CallExtractionData(
        score_qualification="tiede",
        zone_geographique=None,
        budget_max=None,
        type_bien=None,
    )

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = _update_calls(conn)
    sql = updates[0][0][0]
    assert "localisation" not in sql
    assert "budget" not in sql
    assert "type_bien" not in sql


def test_apply_preserves_existing_motivation():
    """Si leads.motivation est déjà remplie, l'extraction ne l'écrase pas."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead

    conn = _make_conn(motivation="Veut s'agrandir pour nouveau bébé")
    data = CallExtractionData(motivation="premier_achat")

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = _update_calls(conn)
    sql = updates[0][0][0]
    assert "motivation" not in sql


def test_apply_sets_motivation_when_empty():
    """Si leads.motivation est vide, l'extraction peut la remplir."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead

    conn = _make_conn(motivation="")
    data = CallExtractionData(motivation="divorce")

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = _update_calls(conn)
    sql = updates[0][0][0]
    assert "motivation" in sql


def test_apply_maps_investissement_to_inconnu():
    """type_projet='investissement' (hors enum leads) est converti en 'inconnu'."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead

    conn = _make_conn()
    data = CallExtractionData(type_projet="investissement")

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = _update_calls(conn)
    params = updates[0][0][1]
    assert "inconnu" in params


def test_apply_noop_when_lead_not_found():
    """Aucun UPDATE si le lead est introuvable en base."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None

    data = CallExtractionData(score_qualification="chaud")
    _apply_extraction_to_lead("lead-inexistant", data, conn)

    updates = [c for c in conn.execute.call_args_list if "UPDATE" in str(c[0][0])]
    assert len(updates) == 0


def test_apply_always_sets_last_extraction_at():
    """last_extraction_at est toujours inclus dans l'UPDATE."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead
    from datetime import datetime

    conn = _make_conn()
    data = CallExtractionData(score_qualification="tiede")

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = _update_calls(conn)
    sql = updates[0][0][0]
    params = updates[0][0][1]
    assert "last_extraction_at" in sql
    assert any(isinstance(p, datetime) for p in params)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Test d'intégration — save_sms_extraction met à jour leads.*
# ═══════════════════════════════════════════════════════════════════════════════

def test_save_sms_extraction_updates_leads():
    """save_sms_extraction insère dans conversation_extractions ET met à jour leads.*."""
    from lib.call_extraction_pipeline import CallExtractionData

    conn = _make_conn(score=0)

    with patch("memory.call_repository.get_connection", return_value=_mock_ctx(conn)):
        from memory.call_repository import save_sms_extraction
        data = CallExtractionData(
            score_qualification="chaud",
            type_projet="achat",
            zone_geographique="Paris 15",
            budget_max=350000,
        )
        result = save_sms_extraction("lead-001", "client-001", data)

    assert result == 42
    assert len(_insert_calls(conn)) == 1
    assert len(_update_calls(conn)) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Non-régression — save_call_extraction continue d'insérer source='call'
# ═══════════════════════════════════════════════════════════════════════════════

def test_save_call_extraction_inserts_with_source_call():
    """save_call_extraction insère toujours dans conversation_extractions avec source='call'."""
    from lib.call_extraction_pipeline import CallExtractionData

    conn = _make_conn()

    with patch("memory.call_repository.get_connection", return_value=_mock_ctx(conn)):
        from memory.call_repository import save_call_extraction
        data = CallExtractionData(score_qualification="tiede")
        result = save_call_extraction("call-001", data)

    assert result == 42
    inserts = _insert_calls(conn)
    assert len(inserts) == 1
    sql = inserts[0][0][0]
    assert "'call'" in sql  # source='call' est littéral dans le SQL
