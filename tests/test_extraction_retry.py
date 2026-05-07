"""
Tests du filet de sécurité extraction (Chantier 2) :
- Retry avec backoff (3 tentatives)
- Validation Pydantic (lead_type obligatoire dans l'enum)
- extraction_status='failed' si toutes les tentatives échouent
- Logs structurés JSON
- save_*_extraction ne met pas à jour les champs lead si failed
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, call, patch

import pytest


@pytest.fixture(autouse=True)
def _force_testing(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── validate_extraction_json ─────────────────────────────────────────────────

class TestValidateExtractionJson:
    def test_valid_acheteur(self):
        from lib.lead_extraction.retry import validate_extraction_json
        # doit ne pas lever
        validate_extraction_json({"lead_type": "acheteur"})

    def test_valid_vendeur(self):
        from lib.lead_extraction.retry import validate_extraction_json
        validate_extraction_json({"lead_type": "vendeur"})

    def test_valid_locataire(self):
        from lib.lead_extraction.retry import validate_extraction_json
        validate_extraction_json({"lead_type": "locataire"})

    def test_invalid_lead_type_raises(self):
        from lib.lead_extraction.retry import validate_extraction_json
        from pydantic import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            validate_extraction_json({"lead_type": "unknown"})

    def test_missing_lead_type_raises(self):
        from lib.lead_extraction.retry import validate_extraction_json
        from pydantic import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            validate_extraction_json({"score_urgence": 3})

    def test_extra_fields_allowed(self):
        from lib.lead_extraction.retry import validate_extraction_json
        validate_extraction_json({
            "lead_type": "acheteur",
            "some_future_field": "value",
            "score_total": 22,
        })


# ── run_with_retry ────────────────────────────────────────────────────────────

class TestRunWithRetry:
    def test_success_first_attempt(self):
        from lib.lead_extraction.retry import run_with_retry

        calls = [0]
        def fn():
            calls[0] += 1
            return {"lead_type": "acheteur"}, '{"lead_type":"acheteur"}'

        result, status = run_with_retry(fn, lead_id="lead-1", source="call")
        assert status == "ok"
        assert result["lead_type"] == "acheteur"
        assert calls[0] == 1

    def test_retry_on_json_error_then_success(self):
        from lib.lead_extraction.retry import run_with_retry

        attempt = [0]
        def fn():
            attempt[0] += 1
            if attempt[0] < 3:
                raise ValueError("JSON parse error simulé")
            return {"lead_type": "vendeur"}, '{"lead_type":"vendeur"}'

        with patch("lib.lead_extraction.retry.time.sleep"):
            result, status = run_with_retry(fn, lead_id="lead-2", source="sms")

        assert status == "ok"
        assert attempt[0] == 3

    def test_all_attempts_fail_returns_failed_status(self):
        from lib.lead_extraction.retry import run_with_retry

        def fn():
            raise RuntimeError("API error simulé")

        with patch("lib.lead_extraction.retry.time.sleep"):
            result, status = run_with_retry(fn, lead_id="lead-3", source="call")

        assert status == "failed"
        assert result is None

    def test_invalid_lead_type_retried(self):
        """lead_type invalide déclenche ValidationError → retry."""
        from lib.lead_extraction.retry import run_with_retry

        attempt = [0]
        def fn():
            attempt[0] += 1
            # Toujours invalide
            return {"lead_type": "n/a"}, '{"lead_type":"n/a"}'

        with patch("lib.lead_extraction.retry.time.sleep"):
            result, status = run_with_retry(fn, lead_id="lead-4", source="sms")

        assert status == "failed"
        assert attempt[0] == 3

    def test_backoff_delays_called(self):
        """Vérifie que les bons délais de backoff sont utilisés."""
        from lib.lead_extraction.retry import run_with_retry, _BACKOFF

        def fn():
            raise RuntimeError("simulé")

        with patch("lib.lead_extraction.retry.time.sleep") as mock_sleep:
            run_with_retry(fn, lead_id="x", source="call")

        # 3 tentatives → 2 sleeps (entre 1→2 et 2→3)
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0] == call(_BACKOFF[0])
        assert mock_sleep.call_args_list[1] == call(_BACKOFF[1])

    def test_structured_log_on_failure(self, caplog):
        from lib.lead_extraction.retry import run_with_retry

        def fn():
            raise ValueError("JSON malformé")

        with patch("lib.lead_extraction.retry.time.sleep"):
            with caplog.at_level(logging.ERROR, logger="lib.lead_extraction.retry"):
                run_with_retry(fn, lead_id="lead-log", source="sms")

        # Vérifie qu'au moins un log contient le JSON structuré attendu
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_logs) >= 1
        for record in error_logs:
            log_data = json.loads(record.message.split("[ExtractionFailed] ", 1)[1])
            assert log_data["event"] == "extraction_failed"
            assert log_data["lead_id"] == "lead-log"
            assert log_data["source"] == "sms"
            assert "timestamp" in log_data
            assert len(log_data["reason"]) <= 500


# ── intégration CallExtractionPipeline ───────────────────────────────────────

class TestCallExtractionPipelineRetry:
    def test_extraction_status_failed_when_all_retries_fail(self):
        from lib.call_extraction_pipeline import CallExtractionPipeline

        pipeline = CallExtractionPipeline()
        # Le pipeline est déjà en mode mock via _force_testing fixture
        # Pour tester le path "failed", on doit simuler un vrai call qui échoue
        # → on monkey-patche self._mock = False et anthropic
        pipeline._mock = False

        with patch("lib.lead_extraction.retry.run_with_retry") as mock_retry:
            mock_retry.return_value = (None, "failed")
            with patch("anthropic.Anthropic"):
                result = pipeline.extract(call_id="call-test", transcript="Bonjour je cherche")

        assert result.extraction_status == "failed"

    def test_mock_pipeline_returns_ok_status(self):
        from lib.call_extraction_pipeline import CallExtractionPipeline

        pipeline = CallExtractionPipeline()
        assert pipeline._mock is True
        result = pipeline.extract(call_id="call-mock", transcript="test")
        assert result.extraction_status == "ok"


# ── save_*_extraction + _mark_lead_extraction_failed ─────────────────────────

class TestSaveExtractionWithFailedStatus:
    def _make_conn(self, score=0):
        conn = MagicMock()
        def _execute(sql, params=None):
            cur = MagicMock()
            sql_s = sql.strip()
            if "FROM calls" in sql_s:
                cur.fetchone.return_value = {"lead_id": "lead-001"}
            elif "FROM leads" in sql_s:
                cur.fetchone.return_value = {"score": score, "motivation": ""}
            elif "INSERT INTO conversation_extractions" in sql_s:
                cur.fetchone.return_value = {"id": 99}
            return cur
        conn.execute.side_effect = _execute
        return conn

    def _mock_ctx(self, conn):
        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        ctx.__exit__.return_value = False
        return ctx

    def test_failed_extraction_marks_lead_not_applies(self):
        from lib.call_extraction_pipeline import CallExtractionData
        from memory.call_repository import save_sms_extraction

        conn = self._make_conn()
        failed_data = CallExtractionData(extraction_status="failed")

        with patch("memory.call_repository.get_connection", return_value=self._mock_ctx(conn)):
            save_sms_extraction("lead-001", "client-001", failed_data)

        update_calls = [c for c in conn.execute.call_args_list if "UPDATE leads" in str(c)]
        # Doit avoir un UPDATE pour extraction_status='failed', mais PAS de mise à jour des champs leads
        assert any("extraction_status" in str(c) for c in update_calls)
        assert not any("score = %s" in str(c) for c in update_calls)

    def test_ok_extraction_applies_to_lead(self):
        from lib.call_extraction_pipeline import CallExtractionData
        from memory.call_repository import save_sms_extraction

        conn = self._make_conn()
        ok_data = CallExtractionData(
            extraction_status="ok",
            score_qualification="chaud",
            score_total=21,
        )

        with patch("memory.call_repository.get_connection", return_value=self._mock_ctx(conn)):
            save_sms_extraction("lead-001", "client-001", ok_data)

        update_calls = [c for c in conn.execute.call_args_list if "UPDATE leads" in str(c)]
        assert len(update_calls) >= 1
        # Le score chaud (21) doit apparaître dans l'update
        assert any("21" in str(c) for c in update_calls)
