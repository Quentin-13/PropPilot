"""
Stockage audio sur Backblaze B2 (API S3-compatible).

Utilise boto3 avec l'endpoint B2 EU. En l'absence de credentials,
les opérations sont simulées (mock) avec log [MOCK].

Usage :
    from lib.audio_storage import AudioStorage
    storage = AudioStorage()
    url = storage.upload_audio("/tmp/call_abc.mp3", "calls/2026/04/abc.mp3")
    local = storage.download_audio("calls/2026/04/abc.mp3", "/tmp/abc.mp3")
    storage.delete_audio("calls/2026/04/abc.mp3")
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _make_s3_client():
    """Construit un client boto3 configuré pour Backblaze B2."""
    import boto3
    from botocore.config import Config
    from config.settings import get_settings

    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.b2_endpoint,
        aws_access_key_id=s.b2_account_id,
        aws_secret_access_key=s.b2_application_key,
        config=Config(signature_version="s3v4"),
    )


class AudioStorage:
    """Wrapper Backblaze B2 avec mock automatique si clé absente."""

    def __init__(self) -> None:
        from config.settings import get_settings
        self._settings = get_settings()
        self._mock = not self._settings.b2_available

    # ── Public API ───────────────────────────────────────────────────────────

    def upload_audio(self, local_path: str, remote_key: str) -> str:
        """
        Upload un fichier audio vers B2.
        Retourne l'URL publique (ou une URL mock).
        """
        if self._mock:
            url = f"https://mock-b2/{self._settings.b2_bucket_name}/{remote_key}"
            logger.info("[MOCK] AudioStorage.upload_audio %s → %s", local_path, url)
            return url

        try:
            s3 = _make_s3_client()
            bucket = self._settings.b2_bucket_name
            with open(local_path, "rb") as f:
                s3.upload_fileobj(f, bucket, remote_key, ExtraArgs={"ContentType": "audio/mpeg"})
            url = f"{self._settings.b2_endpoint}/{bucket}/{remote_key}"
            logger.info("[B2] Upload OK — %s", remote_key)
            return url
        except Exception as exc:
            logger.error("[B2] upload_audio failed for %s: %s", remote_key, exc)
            raise

    def download_audio(self, remote_key: str, dest_path: Optional[str] = None) -> str:
        """
        Télécharge un fichier audio depuis B2.
        Si dest_path est None, crée un fichier temporaire.
        Retourne le chemin local du fichier téléchargé.
        """
        if dest_path is None:
            suffix = Path(remote_key).suffix or ".mp3"
            fd, dest_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)

        if self._mock:
            # Crée un fichier vide pour les tests
            Path(dest_path).write_bytes(b"")
            logger.info("[MOCK] AudioStorage.download_audio %s → %s", remote_key, dest_path)
            return dest_path

        try:
            s3 = _make_s3_client()
            bucket = self._settings.b2_bucket_name
            s3.download_file(bucket, remote_key, dest_path)
            logger.info("[B2] Download OK — %s → %s", remote_key, dest_path)
            return dest_path
        except Exception as exc:
            logger.error("[B2] download_audio failed for %s: %s", remote_key, exc)
            raise

    def delete_audio(self, remote_key: str) -> None:
        """Supprime un fichier audio de B2."""
        if self._mock:
            logger.info("[MOCK] AudioStorage.delete_audio %s", remote_key)
            return

        try:
            s3 = _make_s3_client()
            s3.delete_object(Bucket=self._settings.b2_bucket_name, Key=remote_key)
            logger.info("[B2] Delete OK — %s", remote_key)
        except Exception as exc:
            logger.error("[B2] delete_audio failed for %s: %s", remote_key, exc)
            raise

    def build_remote_key(self, call_id: str, year: int, month: int) -> str:
        """Clé B2 structurée : calls/{year}/{month:02d}/{call_id}.mp3"""
        return f"calls/{year}/{month:02d}/{call_id}.mp3"
