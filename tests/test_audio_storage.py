"""
Tests — lib/audio_storage.py

Vérifie le comportement mock (pas de credentials B2) et les helpers.
Les tests réels B2 sont hors scope (end-to-end manuel).
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    """Force le mode mock (pas de credentials B2)."""
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_upload_mock_returns_url():
    from lib.audio_storage import AudioStorage
    storage = AudioStorage()
    assert storage._mock is True
    url = storage.upload_audio("/tmp/fake.mp3", "calls/2026/04/abc.mp3")
    assert "calls/2026/04/abc.mp3" in url
    assert "mock-b2" in url


def test_download_mock_creates_file(tmp_path):
    from lib.audio_storage import AudioStorage
    dest = str(tmp_path / "audio.mp3")
    storage = AudioStorage()
    result = storage.download_audio("calls/2026/04/abc.mp3", dest)
    assert result == dest
    assert Path(dest).exists()


def test_download_mock_temp_file():
    """Sans dest_path, crée un fichier temporaire."""
    from lib.audio_storage import AudioStorage
    storage = AudioStorage()
    result = storage.download_audio("calls/2026/04/abc.mp3")
    assert Path(result).exists()
    # Cleanup
    Path(result).unlink(missing_ok=True)


def test_delete_mock_noop():
    from lib.audio_storage import AudioStorage
    storage = AudioStorage()
    # Ne doit pas lever d'exception
    storage.delete_audio("calls/2026/04/abc.mp3")


def test_build_remote_key():
    from lib.audio_storage import AudioStorage
    storage = AudioStorage()
    key = storage.build_remote_key("my-call-id", 2026, 4)
    assert key == "calls/2026/04/my-call-id.mp3"


def test_build_remote_key_zero_padded():
    from lib.audio_storage import AudioStorage
    storage = AudioStorage()
    key = storage.build_remote_key("abc123", 2026, 1)
    assert key == "calls/2026/01/abc123.mp3"


def test_upload_real_calls_s3(monkeypatch, tmp_path):
    """Vérifie que le chemin boto3 est appelé avec les bons paramètres."""
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("MOCK_MODE", "never")
    monkeypatch.setenv("B2_ACCOUNT_ID", "fake-account")
    monkeypatch.setenv("B2_APPLICATION_KEY", "fake-key")
    monkeypatch.setenv("B2_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("B2_ENDPOINT", "https://fake.b2.endpoint")
    from config.settings import get_settings
    get_settings.cache_clear()

    mock_s3 = MagicMock()
    audio_file = tmp_path / "call.mp3"
    audio_file.write_bytes(b"FAKEMP3")

    with patch("lib.audio_storage._make_s3_client", return_value=mock_s3):
        from lib.audio_storage import AudioStorage
        storage = AudioStorage()
        assert storage._mock is False
        url = storage.upload_audio(str(audio_file), "calls/2026/04/test.mp3")

    mock_s3.upload_fileobj.assert_called_once()
    assert "calls/2026/04/test.mp3" in url

    get_settings.cache_clear()
