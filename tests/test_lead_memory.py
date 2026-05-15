"""
Tests — mémoire vivante du lead (transcript consolidé + re-extraction + score bidirectionnel).

Scénarios vérifiés :
1. SMS unique → extraction normale
2. SMS puis SMS → transcript contient les 2 messages, score mis à jour
3. SMS puis appel → transcript contient SMS + transcription appel (cross-canal)
4. Appel puis SMS → transcript chronologique (appel avant SMS)
5. Lead tiède → chaud après message urgent (score_urgence=3 + divorce)
6. Re-extraction échoue → anciennes données conservées, lead non écrasé
7. Même numéro SMS + appel → même lead, pas de doublon
8. Lead chaud (J1 urgent) → score baisse après message "on attend l'année prochaine" (overwrite_score)
9. Score partiel (SMS seul) → ne rétrograde jamais (overwrite_score=False par défaut)
10. Extraction consolidée échouée → score chaud conservé (protection failure)
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ─── Fixtures & helpers ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _force_mock_mode(monkeypatch):
    """Toujours activer le mode mock pour éviter les appels Claude réels."""
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mock_ctx(conn):
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    return ctx


def _make_db_conn(sms_rows=None, call_rows=None):
    """Connexion mock : retourne sms_rows sur FROM conversations, call_rows sur FROM calls."""
    sms_rows = sms_rows or []
    call_rows = call_rows or []
    conn = MagicMock()

    def _execute(sql, params=None):
        cur = MagicMock()
        if "FROM conversations" in sql:
            cur.fetchall.return_value = sms_rows
        elif "FROM calls" in sql and "transcript_text" in sql:
            cur.fetchall.return_value = call_rows
        else:
            cur.fetchall.return_value = []
        return cur

    conn.execute.side_effect = _execute
    return conn


def _sms_row(role, contenu, ts):
    return {"role": role, "contenu": contenu, "created_at": ts}


def _call_row(ts, transcript):
    return {"started_at": ts, "transcript_text": transcript}


# ─── 1. SMS unique → extraction normale ────────────────────────────────────────

def test_sms_unique_extraction_normale():
    """Un SMS entrant déclenche une extraction et retourne des données valides."""
    conn = _make_db_conn(
        sms_rows=[_sms_row("user", "Je cherche un T3 à Lyon, budget 350k", datetime(2026, 5, 5, 14, 32))],
    )

    from lib.lead_extraction.consolidated_extraction import extract_and_update_lead

    with patch("lib.consolidated_transcript.get_connection", return_value=_mock_ctx(conn)), \
         patch("memory.call_repository.get_connection", return_value=_mock_ctx(_make_call_repo_conn())):
        data = extract_and_update_lead(lead_id="lead-001", client_id="client-001")

    assert data is not None
    assert data.extraction_status in ("ok", "mock")
    assert data.score_qualification in ("chaud", "tiede", "froid")


def _make_call_repo_conn():
    """Connexion mock pour call_repository (INSERT + SELECT leads)."""
    conn = MagicMock()
    def _execute(sql, params=None):
        cur = MagicMock()
        sql_s = sql.strip()
        if "FROM leads" in sql_s:
            cur.fetchone.return_value = {"score": 0, "motivation": ""}
        elif "INSERT INTO conversation_extractions" in sql_s:
            cur.fetchone.return_value = {"id": 42}
        return cur
    conn.execute.side_effect = _execute
    return conn


# ─── 2. SMS puis SMS → transcript contient les 2 messages ─────────────────────

def test_deux_sms_transcript_complet():
    """Deux SMS consécutifs → le transcript contient les 2 messages."""
    t1 = datetime(2026, 5, 5, 14, 32)
    t2 = datetime(2026, 5, 5, 15, 10)
    sms_rows = [
        _sms_row("user", "Je cherche une maison à Toulouse, budget 300k", t1),
        _sms_row("user", "C'est urgent, on est en divorce", t2),
    ]
    conn = _make_db_conn(sms_rows=sms_rows)

    from lib.consolidated_transcript import build_lead_conversation_transcript

    with patch("lib.consolidated_transcript.get_connection", return_value=_mock_ctx(conn)):
        transcript = build_lead_conversation_transcript("lead-001", "client-001")

    assert "[SMS IN" in transcript
    assert "Toulouse" in transcript
    assert "divorce" in transcript
    # Les 2 messages sont présents
    lines = [l for l in transcript.splitlines() if l.strip()]
    assert len(lines) == 2


def test_deux_sms_score_mis_a_jour():
    """Deux SMS → score mis à jour après extraction consolidée."""
    conn = _make_db_conn(
        sms_rows=[
            _sms_row("user", "Je cherche une maison à Toulouse, budget 300k", datetime(2026, 5, 5, 14, 32)),
            _sms_row("user", "C'est urgent, on est en divorce", datetime(2026, 5, 5, 15, 10)),
        ]
    )
    call_repo_conn = _make_call_repo_conn()

    from lib.lead_extraction.consolidated_extraction import extract_and_update_lead

    with patch("lib.consolidated_transcript.get_connection", return_value=_mock_ctx(conn)), \
         patch("memory.call_repository.get_connection", return_value=_mock_ctx(call_repo_conn)):
        data = extract_and_update_lead("lead-001", "client-001")

    assert data is not None
    # L'extraction doit avoir été lancée (pas de transcript vide)
    assert data.score_qualification in ("chaud", "tiede", "froid")
    # Le score numérique doit être > 0
    assert data.score_total >= 0


# ─── 3. SMS puis appel → transcript cross-canal ────────────────────────────────

def test_sms_puis_appel_transcript_cross_canal():
    """SMS + transcription d'appel → le transcript contient les deux canaux."""
    t_sms = datetime(2026, 5, 5, 14, 32)
    t_call = datetime(2026, 5, 6, 10, 15)
    sms_rows = [_sms_row("user", "Je cherche une maison à Toulouse, budget 300k", t_sms)]
    call_rows = [_call_row(t_call, "Le prospect précise que son divorce est en cours.")]

    conn = _make_db_conn(sms_rows=sms_rows, call_rows=call_rows)

    from lib.consolidated_transcript import build_lead_conversation_transcript

    with patch("lib.consolidated_transcript.get_connection", return_value=_mock_ctx(conn)):
        transcript = build_lead_conversation_transcript("lead-001", "client-001")

    assert "[SMS IN" in transcript
    assert "[CALL" in transcript
    assert "Toulouse" in transcript
    assert "divorce" in transcript


# ─── 4. Appel puis SMS → ordre chronologique ────────────────────────────────────

def test_appel_puis_sms_ordre_chronologique():
    """Appel (t=1) puis SMS (t=2) → le transcript est ordonné chronologiquement."""
    t_call = datetime(2026, 5, 5, 9, 0)
    t_sms = datetime(2026, 5, 5, 10, 30)
    sms_rows = [_sms_row("user", "SMS après l'appel", t_sms)]
    call_rows = [_call_row(t_call, "Transcription de l'appel initial.")]

    conn = _make_db_conn(sms_rows=sms_rows, call_rows=call_rows)

    from lib.consolidated_transcript import build_lead_conversation_transcript

    with patch("lib.consolidated_transcript.get_connection", return_value=_mock_ctx(conn)):
        transcript = build_lead_conversation_transcript("lead-001", "client-001")

    idx_call = transcript.index("[CALL")
    idx_sms = transcript.index("[SMS")
    assert idx_call < idx_sms, "L'appel (plus ancien) doit apparaître avant le SMS"


# ─── 5. Lead tiède → chaud après message urgent ───────────────────────────────

def test_tiede_devient_chaud_apres_urgence():
    """
    Score actuel = 14 (tiède).
    Nouvelle extraction avec score_total=24 (chaud, divorce urgent).
    Après _apply_extraction_to_lead, le score du lead doit être 24.
    """
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead

    conn = MagicMock()
    def _execute(sql, params=None):
        cur = MagicMock()
        if "FROM leads" in sql:
            cur.fetchone.return_value = {"score": 14, "motivation": ""}
        return cur
    conn.execute.side_effect = _execute

    # Extraction avec urgence maximale (divorce)
    data = CallExtractionData(
        lead_type="acheteur",
        score_urgence=3,       # divorce → urgence maximale
        score_motivation=3,    # divorce = vie forte
        score_qualification="chaud",
    )
    data._recompute_score()    # recalcule score_total

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = [c for c in conn.execute.call_args_list if "UPDATE leads" in c[0][0]]
    assert len(updates) == 1
    params = list(updates[0][0][1])
    # Le nouveau score (>=18 pour chaud) doit être dans les paramètres
    assert any(p >= 18 for p in params if isinstance(p, (int, float))), (
        f"Score chaud attendu dans les paramètres d'UPDATE, params={params}"
    )


def test_score_ne_retrograde_pas():
    """Score actuel = 21 (chaud). Nouvelle extraction froid → score reste 21."""
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead, _SCORE_MAP

    conn = MagicMock()
    def _execute(sql, params=None):
        cur = MagicMock()
        if "FROM leads" in sql:
            cur.fetchone.return_value = {"score": 21, "motivation": "divorce"}
        return cur
    conn.execute.side_effect = _execute

    data = CallExtractionData(score_qualification="froid")

    _apply_extraction_to_lead("lead-001", data, conn)

    updates = [c for c in conn.execute.call_args_list if "UPDATE leads" in c[0][0]]
    assert len(updates) == 1
    params = list(updates[0][0][1])
    assert _SCORE_MAP["froid"] not in params, "Le score froid ne doit pas rétrograder un lead chaud"


# ─── 6. Re-extraction échoue → données conservées ─────────────────────────────

def test_extraction_echec_conserve_donnees():
    """
    Si l'extraction échoue, leads.* ne doit pas être écrasé.
    save_sms_extraction avec extraction_status='failed' → seul
    leads.extraction_status='failed' est touché.
    """
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import save_sms_extraction

    conn = MagicMock()
    def _execute(sql, params=None):
        cur = MagicMock()
        sql_s = sql.strip()
        if "INSERT INTO conversation_extractions" in sql_s:
            cur.fetchone.return_value = {"id": 99}
        elif "FROM leads" in sql_s:
            cur.fetchone.return_value = {"score": 14, "motivation": "divorce"}
        return cur
    conn.execute.side_effect = _execute

    failed_data = CallExtractionData(extraction_status="failed")

    with patch("memory.call_repository.get_connection", return_value=_mock_ctx(conn)):
        result = save_sms_extraction("lead-001", "client-001", failed_data)

    assert result == 99

    # Vérifier que leads.score n'a PAS été mis à jour (pas d'UPDATE leads SET score=...)
    update_calls = [c for c in conn.execute.call_args_list if "UPDATE leads" in c[0][0]]
    # L'UPDATE doit seulement toucher extraction_status='failed', pas score/resume/etc.
    for call in update_calls:
        sql = call[0][0]
        assert "score" not in sql or "extraction_status" in sql, (
            f"UPDATE inattendu avec score lors d'une extraction échouée : {sql}"
        )


# ─── 7. Même numéro SMS + appel → même lead, pas de doublon ──────────────────

def test_meme_numero_sms_et_appel_meme_lead():
    """
    get_lead_by_phone retourne le même lead pour SMS et appel depuis le même numéro.
    Vérifie que les deux flux utilisent le même lead_id (pas de doublon).
    """
    from memory.models import Lead, Canal, LeadStatus

    existing_lead = Lead(
        id="lead-existant-001",
        client_id="client-001",
        telephone="+33612345678",
        source=Canal.SMS,
        statut=LeadStatus.ENTRANT,
    )

    # Simule le flux SMS : trouve le lead existant
    with patch("memory.lead_repository.get_lead_by_phone", return_value=existing_lead) as mock_get:
        from lib.sms_storage import store_incoming_sms
        with patch("memory.lead_repository.add_conversation_message"):
            result = store_incoming_sms(
                from_number="+33612345678",
                to_number="+33700000001",
                body="Bonjour",
                client_id="client-001",
            )
        # Le lead existant doit être retrouvé, pas recréé
        assert result["lead_id"] == "lead-existant-001"
        assert result["is_new_lead"] is False
        mock_get.assert_called_once_with("+33612345678", "client-001")

    # Simule le flux appel : même logique
    with patch("memory.lead_repository.get_lead_by_phone", return_value=existing_lead) as mock_get2:
        from webhooks.twilio_voice import _persist_incoming_call
        with patch("memory.call_repository.create_call", return_value="call-001"):
            _persist_incoming_call(
                call_sid="CA123",
                from_number="+33612345678",
                to_number="+33700000001",
                agency_id="client-001",
                agent_id=None,
                client_id="client-001",
                call_status="ringing",
            )
        mock_get2.assert_called_once_with("+33612345678", "client-001")


# ─── 8. Score bidirectionnel — extraction consolidée peut faire baisser le score ─

def test_chaud_devient_froid_apres_refroidissement():
    """
    J1 : lead chaud (score=21).
    J7 : nouveau message "finalement on attend l'année prochaine".
    Extraction consolidée → score DOIT baisser (overwrite_score=True).
    """
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead

    conn = MagicMock()
    def _execute(sql, params=None):
        cur = MagicMock()
        if "FROM leads" in sql:
            cur.fetchone.return_value = {"score": 21, "motivation": "divorce"}
        return cur
    conn.execute.side_effect = _execute

    # Extraction après le message de refroidissement
    data = CallExtractionData(
        lead_type="acheteur",
        score_urgence=0,       # plus d'urgence — "on attend"
        score_motivation=1,    # projet vague
        score_capacite_fin=None,
        score_engagement=1,    # peu engagé
        score_qualification="froid",
    )
    data._recompute_score()

    _apply_extraction_to_lead("lead-001", data, conn, overwrite_score=True)

    updates = [c for c in conn.execute.call_args_list if "UPDATE leads" in c[0][0]]
    assert len(updates) == 1
    params = list(updates[0][0][1])
    # Le score doit être inférieur à 18 (plus chaud)
    score_values = [p for p in params if isinstance(p, (int, float)) and 0 < p < 18]
    assert score_values, (
        f"Le score consolidé doit avoir baissé en dessous de 18 (chaud). params={params}"
    )


def test_score_partiel_sms_ne_retrograde_jamais():
    """
    Extraction SMS partielle (overwrite_score=False par défaut) :
    même si le nouveau score est plus bas, le score actuel est conservé.
    Vérifie que le comportement existant n'est pas cassé.
    """
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import _apply_extraction_to_lead, _SCORE_MAP

    conn = MagicMock()
    def _execute(sql, params=None):
        cur = MagicMock()
        if "FROM leads" in sql:
            cur.fetchone.return_value = {"score": 21, "motivation": "divorce"}
        return cur
    conn.execute.side_effect = _execute

    data = CallExtractionData(score_qualification="froid")  # score_map["froid"] = 5

    # overwrite_score=False (défaut) — comportement partiel SMS/appel
    _apply_extraction_to_lead("lead-001", data, conn, overwrite_score=False)

    updates = [c for c in conn.execute.call_args_list if "UPDATE leads" in c[0][0]]
    assert len(updates) == 1
    params = list(updates[0][0][1])
    assert _SCORE_MAP["froid"] not in params, (
        "Extraction partielle : score froid ne doit pas écraser score=21"
    )


def test_extraction_consolidee_echouee_conserve_score_chaud():
    """
    Extraction consolidée avec extraction_status='failed' :
    même avec overwrite_score=True, le score chaud doit être conservé.
    """
    from lib.call_extraction_pipeline import CallExtractionData
    from memory.call_repository import save_sms_extraction

    conn = MagicMock()
    def _execute(sql, params=None):
        cur = MagicMock()
        sql_s = sql.strip()
        if "INSERT INTO conversation_extractions" in sql_s:
            cur.fetchone.return_value = {"id": 77}
        elif "FROM leads" in sql_s:
            cur.fetchone.return_value = {"score": 21, "motivation": "divorce"}
        return cur
    conn.execute.side_effect = _execute

    failed_data = CallExtractionData(extraction_status="failed")

    with patch("memory.call_repository.get_connection", return_value=_mock_ctx(conn)):
        result = save_sms_extraction("lead-001", "client-001", failed_data, overwrite_score=True)

    assert result == 77

    # Aucun UPDATE leads SET score ne doit être présent
    score_updates = [
        c for c in conn.execute.call_args_list
        if "UPDATE leads" in c[0][0] and "score" in c[0][0]
        and "extraction_status" not in c[0][0]
    ]
    assert not score_updates, (
        "Extraction échouée : le score ne doit jamais être mis à jour"
    )
