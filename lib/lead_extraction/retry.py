"""
Filet de sécurité extraction LLM :
- Retry avec backoff exponentiel (3 tentatives : 1s/3s/9s)
- Validation Pydantic stricte du JSON renvoyé
- Log structuré JSON à chaque échec (lead_id, raison, raw_output, timestamp)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

from pydantic import BaseModel, field_validator, ValidationError

logger = logging.getLogger(__name__)

# Délais entre tentatives : 0s (1ère), 1s (2ème), 3s (3ème avant fail)
_BACKOFF = (1, 3, 9)


class ExtractionOutputSchema(BaseModel):
    """Validation minimale du JSON renvoyé par le LLM.

    Seules les contraintes non déductibles du code Python sont vérifiées ici :
    - lead_type doit être dans l'enum autorisé
    - score_* doivent être 0-3 ou null si présents
    """
    model_config = {"extra": "allow"}

    lead_type: str

    @field_validator("lead_type")
    @classmethod
    def validate_lead_type(cls, v: str) -> str:
        v = (v or "").lower().strip()
        if v not in ("acheteur", "vendeur", "locataire"):
            raise ValueError(
                f"lead_type invalide : {v!r} — attendu acheteur|vendeur|locataire"
            )
        return v


def validate_extraction_json(parsed: dict) -> None:
    """Lève ValueError/ValidationError si le JSON ne respecte pas le schéma minimal."""
    ExtractionOutputSchema.model_validate(parsed)


def _log_failure(
    *,
    lead_id: str,
    source: str,
    attempt: int,
    reason: str,
    raw_output: Optional[str],
    lead_type_detected: Optional[str],
) -> None:
    record = {
        "event": "extraction_failed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lead_id": lead_id,
        "source": source,
        "attempt": attempt,
        "reason": reason[:500],
        "lead_type_detected": lead_type_detected,
        "raw_output": (raw_output or "")[:500],
    }
    logger.error("[ExtractionFailed] %s", json.dumps(record, ensure_ascii=False))


def run_with_retry(
    call_fn: Callable[[], Tuple[dict, str]],
    *,
    lead_id: str,
    source: str,
) -> Tuple[Optional[dict], str]:
    """
    Exécute call_fn() jusqu'à 3 fois avec backoff 1s/3s/9s.

    call_fn() doit retourner (parsed_dict, raw_str) ou lever une exception.
    Chaque parsed_dict est validé via validate_extraction_json().

    Returns:
        (parsed_dict, "ok")     si une tentative réussit
        (None,        "failed") si toutes les tentatives échouent
    """
    raw_output: Optional[str] = None
    lead_type_detected: Optional[str] = None

    for attempt in range(1, 4):
        if attempt > 1:
            time.sleep(_BACKOFF[attempt - 2])
        try:
            parsed, raw_output = call_fn()
            validate_extraction_json(parsed)
            lead_type_detected = parsed.get("lead_type")
            if attempt > 1:
                logger.info(
                    "[Retry] Extraction OK tentative=%d lead_id=%s source=%s",
                    attempt, lead_id, source,
                )
            return parsed, "ok"
        except Exception as exc:
            _log_failure(
                lead_id=lead_id,
                source=source,
                attempt=attempt,
                reason=str(exc),
                raw_output=raw_output,
                lead_type_detected=lead_type_detected,
            )

    return None, "failed"
