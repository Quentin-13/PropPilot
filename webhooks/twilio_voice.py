"""
Webhooks Twilio Voice — appels entrants, enregistrement, statut.

Routes :
    POST /webhooks/twilio/voice/incoming  — TwiML : mention légale + record + dial
    POST /webhooks/twilio/voice/recording — Notification fin d'enregistrement
    POST /webhooks/twilio/voice/status    — Suivi du statut de l'appel

Toutes les routes valident la signature Twilio.
Idempotence garantie sur CallSid.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel

from tools.security import validate_twilio_signature, sanitize_phone_number

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks-voice"])


# ── TwiML helpers ─────────────────────────────────────────────────────────────

def _build_inbound_twiml(
    agent_phone: str | None,
    legal_text: str,
    legal_audio_url: str | None,
    base_url: str,
    call_sid: str,
) -> str:
    """
    Construit le TwiML pour un appel entrant :
    1. Mention légale RGPD (audio ou TTS)
    2. Enregistrement + dial vers l'agent
    3. Fallback : message vocal + boîte vocale si pas de réponse en 30s
    """
    recording_cb = f"{base_url}/webhooks/twilio/voice/recording"
    status_cb = f"{base_url}/webhooks/twilio/voice/status"
    voicemail_action = f"{base_url}/webhooks/twilio/voice/voicemail?call_sid={call_sid}"

    # Mention légale : audio pré-enregistré ou TTS français
    if legal_audio_url:
        notice_xml = f'<Play>{legal_audio_url}</Play>'
    else:
        escaped = legal_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        notice_xml = (
            f'<Say language="fr-FR" voice="Polly.Lea-Neural">{escaped}</Say>'
        )

    # Dial vers l'agent (ou message si pas d'agent configuré)
    if agent_phone:
        dial_xml = (
            f'<Dial record="record-from-answer" '
            f'recordingStatusCallback="{recording_cb}" '
            f'recordingStatusCallbackMethod="POST" '
            f'action="{voicemail_action}" '
            f'timeout="30">'
            f'<Number statusCallback="{status_cb}" '
            f'statusCallbackMethod="POST">{agent_phone}</Number>'
            f'</Dial>'
        )
    else:
        # Pas d'agent configuré : enregistrement direct (boîte vocale)
        dial_xml = (
            f'<Say language="fr-FR" voice="Polly.Lea-Neural">'
            f'Aucun conseiller n\'est disponible pour le moment. '
            f'Laissez-nous votre message après le signal.'
            f'</Say>'
            f'<Record maxLength="120" action="{recording_cb}" '
            f'recordingStatusCallback="{recording_cb}" '
            f'recordingStatusCallbackMethod="POST" />'
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"{notice_xml}"
        f"{dial_xml}"
        "</Response>"
    )


def _build_voicemail_twiml(recording_cb: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Say language="fr-FR" voice="Polly.Lea-Neural">'
        "Votre conseiller est actuellement indisponible. "
        "Laissez-nous votre message après le signal, nous vous rappellerons."
        "</Say>"
        f'<Record maxLength="120" action="{recording_cb}" '
        f'recordingStatusCallback="{recording_cb}" '
        f'recordingStatusCallbackMethod="POST" />'
        "</Response>"
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/webhooks/twilio/voice/incoming", response_class=Response)
async def voice_incoming(request: Request, background_tasks: BackgroundTasks):
    """
    Appel entrant sur un numéro Twilio.
    1. Valide la signature Twilio
    2. Crée l'enregistrement call en DB
    3. Retourne TwiML (mention légale + enregistrement + routage)
    """
    if not await validate_twilio_signature(request):
        raise HTTPException(status_code=403, detail="Signature Twilio invalide")

    form = dict(await request.form())
    call_sid = form.get("CallSid", "")
    from_number = sanitize_phone_number(form.get("From", ""))
    to_number = form.get("To", "")
    call_status = form.get("CallStatus", "ringing")

    logger.info(
        "[Voice] Incoming call_sid=%s from=%s to=%s status=%s",
        call_sid, from_number, to_number, call_status,
    )

    from config.settings import get_settings
    from memory.call_repository import create_call, get_phone_number_config

    settings = get_settings()

    # Lookup agent associé au numéro Twilio
    phone_config = get_phone_number_config(to_number)
    agent_phone = phone_config["agent_phone"] if phone_config else None
    agency_id = phone_config["agency_id"] if phone_config else None
    agent_id = phone_config["agent_id"] if phone_config else None

    # Fallback : chercher un user avec ce numéro assigné
    if not agent_phone:
        try:
            from memory.database import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT id, phone FROM users WHERE twilio_sms_number = %s AND plan_active = TRUE LIMIT 1",
                    (to_number,),
                ).fetchone()
                if row:
                    agent_id = row["id"]
                    agent_phone = row.get("phone")
        except Exception as exc:
            logger.warning("[Voice] DB lookup for agent phone failed: %s", exc)

    # Créer le call en DB (idempotent sur call_sid)
    background_tasks.add_task(
        _persist_incoming_call,
        call_sid=call_sid,
        from_number=from_number,
        to_number=to_number,
        agency_id=agency_id,
        agent_id=agent_id,
        call_status=call_status,
    )

    # Construire le TwiML
    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    forwarded_host = request.headers.get("X-Forwarded-Host", request.url.netloc)
    base_url = f"{forwarded_proto}://{forwarded_host}"
    twiml = _build_inbound_twiml(
        agent_phone=agent_phone,
        legal_text=settings.legal_notice_text,
        legal_audio_url=settings.legal_notice_audio_url if not settings.fallback_use_tts else None,
        base_url=base_url,
        call_sid=call_sid,
    )

    return Response(content=twiml, media_type="application/xml")


@router.post("/webhooks/twilio/voice/voicemail", response_class=Response)
async def voice_voicemail(request: Request):
    """Appel non décroché : lecture message + démarrage enregistrement boîte vocale."""
    if not await validate_twilio_signature(request):
        raise HTTPException(status_code=403, detail="Signature Twilio invalide")

    form = dict(await request.form())
    call_sid = form.get("CallSid", "")
    dial_status = form.get("DialCallStatus", "no-answer")
    logger.info("[Voice] No answer call_sid=%s dial_status=%s", call_sid, dial_status)

    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    forwarded_host = request.headers.get("X-Forwarded-Host", request.url.netloc)
    base_url = f"{forwarded_proto}://{forwarded_host}"
    recording_cb = f"{base_url}/webhooks/twilio/voice/recording"
    twiml = _build_voicemail_twiml(recording_cb)

    # Mise à jour statut
    try:
        from memory.call_repository import get_call_by_sid, update_call_status
        call = get_call_by_sid(call_sid)
        if call:
            status = "voicemail" if dial_status == "no-answer" else "no_answer"
            update_call_status(call["id"], status)
    except Exception as exc:
        logger.warning("[Voice] Could not update status for %s: %s", call_sid, exc)

    return Response(content=twiml, media_type="application/xml")


@router.post("/webhooks/twilio/voice/recording")
async def voice_recording(request: Request, background_tasks: BackgroundTasks):
    """
    Webhook de fin d'enregistrement Twilio.
    Télécharge l'audio depuis Twilio, l'upload sur B2, lance la transcription.
    """
    if not await validate_twilio_signature(request):
        raise HTTPException(status_code=403, detail="Signature Twilio invalide")

    form = dict(await request.form())
    call_sid = form.get("CallSid", "")
    recording_sid = form.get("RecordingSid", "")
    recording_url = form.get("RecordingUrl", "")
    recording_status = form.get("RecordingStatus", "")
    recording_duration = int(form.get("RecordingDuration", 0) or 0)

    logger.info(
        "[Voice] Recording call_sid=%s recording_sid=%s status=%s duration=%ds",
        call_sid, recording_sid, recording_status, recording_duration,
    )

    if recording_status != "completed":
        logger.info("[Voice] Recording not completed (status=%s) — skip", recording_status)
        return {"ok": True}

    background_tasks.add_task(
        _process_recording,
        call_sid=call_sid,
        recording_sid=recording_sid,
        twilio_recording_url=recording_url,
        recording_duration=recording_duration,
    )

    return {"ok": True}


@router.post("/webhooks/twilio/voice/status")
async def voice_status(request: Request):
    """
    Suivi du statut de l'appel (initié, décroché, terminé…).
    Met à jour la table calls en temps réel.
    """
    if not await validate_twilio_signature(request):
        raise HTTPException(status_code=403, detail="Signature Twilio invalide")

    form = dict(await request.form())
    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")
    duration = int(form.get("CallDuration", 0) or 0)

    logger.info("[Voice] Status call_sid=%s status=%s duration=%ds", call_sid, call_status, duration)

    _TWILIO_TO_DB_STATUS = {
        "initiated": "initiated",
        "ringing": "ringing",
        "in-progress": "answered",
        "completed": "completed",
        "busy": "no_answer",
        "no-answer": "no_answer",
        "failed": "failed",
        "canceled": "failed",
    }
    db_status = _TWILIO_TO_DB_STATUS.get(call_status, call_status)

    try:
        from memory.call_repository import get_call_by_sid, update_call_status
        call = get_call_by_sid(call_sid)
        if call:
            kwargs: dict = {}
            if call_status in ("in-progress",) and not call.get("answered_at"):
                kwargs["answered_at"] = datetime.utcnow()
            if call_status in ("completed", "busy", "no-answer", "failed", "canceled"):
                kwargs["ended_at"] = datetime.utcnow()
                if duration:
                    kwargs["duration_seconds"] = duration
            update_call_status(call["id"], db_status, **kwargs)
    except Exception as exc:
        logger.warning("[Voice] Status update failed for %s: %s", call_sid, exc)

    return {"ok": True}


# ── Background tasks ──────────────────────────────────────────────────────────

def _persist_incoming_call(
    *,
    call_sid: str,
    from_number: str,
    to_number: str,
    agency_id: str | None,
    agent_id: str | None,
    call_status: str,
) -> None:
    """Crée l'enregistrement call en DB (exécuté en background)."""
    try:
        from memory.call_repository import create_call
        create_call(
            call_sid=call_sid,
            direction="inbound",
            mode="dedicated_number",
            from_number=from_number,
            to_number=to_number,
            twilio_number=to_number,
            agency_id=agency_id,
            agent_id=agent_id,
            started_at=datetime.utcnow(),
        )
    except Exception as exc:
        logger.error("[Voice] _persist_incoming_call failed call_sid=%s: %s", call_sid, exc)


def _process_recording(
    *,
    call_sid: str,
    recording_sid: str,
    twilio_recording_url: str,
    recording_duration: int,
) -> None:
    """
    Pipeline complet post-enregistrement :
    1. Télécharge depuis Twilio
    2. Upload sur B2
    3. Supprime chez Twilio
    4. Met à jour DB (status=recorded, recording_url)
    5. Lance transcription puis extraction
    """
    from config.settings import get_settings
    from lib.audio_storage import AudioStorage
    from memory.call_repository import get_call_by_sid, update_call_status

    settings = get_settings()

    call = get_call_by_sid(call_sid)
    if not call:
        logger.warning("[Voice] _process_recording: call not found for sid=%s", call_sid)
        return

    call_id = call["id"]
    now = datetime.utcnow()
    remote_key = AudioStorage().build_remote_key(call_id, now.year, now.month)

    # 1. Download from Twilio
    import os
    import tempfile
    import httpx

    local_path = None
    try:
        mp3_url = twilio_recording_url
        if not mp3_url.endswith(".mp3"):
            mp3_url = mp3_url + ".mp3"

        fd, local_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)

        auth = (settings.twilio_account_sid, settings.twilio_auth_token) if settings.twilio_available else None
        if auth:
            resp = httpx.get(mp3_url, auth=auth, follow_redirects=True, timeout=60)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)
            logger.info("[Voice] Downloaded recording call_id=%s size=%d bytes", call_id, len(resp.content))
        else:
            # Mock: write empty file
            logger.info("[MOCK] Skipping Twilio download — mock mode")
            open(local_path, "wb").close()

        # 2. Upload to B2
        storage = AudioStorage()
        b2_url = storage.upload_audio(local_path, remote_key)

        # 3. Optionally delete from Twilio (save money)
        if settings.twilio_available and auth:
            try:
                from twilio.rest import Client as TwilioClient
                twilio_client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
                twilio_client.recordings(recording_sid).delete()
                logger.info("[Voice] Deleted recording from Twilio: %s", recording_sid)
            except Exception as del_exc:
                logger.warning("[Voice] Could not delete Twilio recording %s: %s", recording_sid, del_exc)

        # 4. Update DB — status=recorded
        update_call_status(
            call_id, "recorded",
            recording_url=b2_url,
            recording_duration=recording_duration,
        )

        # 5. Transcribe then extract (chained)
        _run_transcription(call_id=call_id, remote_key=remote_key)

    except Exception as exc:
        logger.error("[Voice] _process_recording failed call_id=%s: %s", call_id, exc)
        update_call_status(call_id, "failed")
    finally:
        if local_path and os.path.exists(local_path):
            try:
                os.unlink(local_path)
            except OSError:
                pass


def _run_transcription(call_id: str, remote_key: str) -> None:
    """Transcrit l'audio et enchaîne l'extraction structurée."""
    from lib.call_transcription import CallTranscription
    from memory.call_repository import update_call_status

    try:
        result = CallTranscription().transcribe(remote_key, call_id=call_id)
        update_call_status(
            call_id, "transcribed",
            transcript_text=result.text,
            transcript_segments=result.segments,
            duration_seconds=int(result.duration_seconds),
            cost_whisper=result.cost_usd,
        )
        logger.info("[Voice] Transcription OK call_id=%s", call_id)
        _run_extraction(call_id=call_id, transcript=result.text)
    except Exception as exc:
        logger.error("[Voice] Transcription failed call_id=%s: %s", call_id, exc)
        _retry_transcription(call_id=call_id, remote_key=remote_key, attempt=1)


def _retry_transcription(call_id: str, remote_key: str, attempt: int) -> None:
    """Retry transcription jusqu'à 3 tentatives."""
    MAX_ATTEMPTS = 3
    if attempt >= MAX_ATTEMPTS:
        logger.error("[Voice] Transcription failed after %d attempts call_id=%s", MAX_ATTEMPTS, call_id)
        from memory.call_repository import update_call_status
        update_call_status(call_id, "transcription_failed")
        return

    import time
    time.sleep(2 ** attempt)  # exponential backoff: 2s, 4s

    from lib.call_transcription import CallTranscription
    from memory.call_repository import update_call_status

    try:
        result = CallTranscription().transcribe(remote_key, call_id=call_id)
        update_call_status(
            call_id, "transcribed",
            transcript_text=result.text,
            transcript_segments=result.segments,
            duration_seconds=int(result.duration_seconds),
            cost_whisper=result.cost_usd,
        )
        _run_extraction(call_id=call_id, transcript=result.text)
    except Exception:
        _retry_transcription(call_id=call_id, remote_key=remote_key, attempt=attempt + 1)


def _run_extraction(call_id: str, transcript: str) -> None:
    """Lance l'extraction structurée et sauvegarde en DB."""
    from lib.call_extraction_pipeline import CallExtractionPipeline
    from memory.call_repository import save_call_extraction, update_call_status

    try:
        data = CallExtractionPipeline().extract(call_id=call_id, transcript=transcript)
        save_call_extraction(call_id, data)
        update_call_status(call_id, "extracted", cost_claude=data.cost_usd)
        logger.info("[Voice] Extraction OK call_id=%s score=%s", call_id, data.score_qualification)
    except Exception as exc:
        logger.error("[Voice] Extraction failed call_id=%s: %s", call_id, exc)
        # Extraction failure doesn't block the call record
        update_call_status(call_id, "transcribed")  # Keep transcribed status
