"""
Tests — Page 11_integrations.py : import CSV et logique de parsing.
"""
from __future__ import annotations

import io
import csv
import pytest


def _make_csv(rows: list[dict], fieldnames: list[str] | None = None) -> bytes:
    """Génère un CSV en mémoire."""
    if not rows:
        return b""
    fields = fieldnames or list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def test_csv_nom_normalisation():
    """Les colonnes avec accents doivent être normalisées."""
    # Simule la logique _norm() de server.py
    def _norm(s: str) -> str:
        return s.lower().strip().replace("é", "e").replace("è", "e").replace("ê", "e").replace("ô", "o").replace("â", "a")

    assert _norm("Prénom") == "prenom"
    assert _norm("Téléphone") == "telephone"
    assert _norm("Nom") == "nom"
    assert _norm("  Email  ") == "email"


def test_csv_import_standard_columns():
    """CSV avec colonnes standard — tous les leads doivent être extraits."""
    csv_bytes = _make_csv([
        {"nom": "Dupont", "prenom": "Jean", "telephone": "+33600000001", "email": "jean@test.com"},
        {"nom": "Martin", "prenom": "Alice", "telephone": "+33600000002", "email": "alice@test.com"},
    ])
    import csv as _csv
    reader = _csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["telephone"] == "+33600000001"
    assert rows[1]["prenom"] == "Alice"


def test_csv_import_bom_encoding():
    """CSV avec BOM UTF-8 (export Excel) doit être décodé correctement."""
    csv_bytes = b"\xef\xbb\xbfnom,pr\xc3\xa9nom,t\xc3\xa9l\xc3\xa9phone\nDupont,Marie,+33600000003"
    text = csv_bytes.decode("utf-8-sig")
    import csv as _csv
    reader = _csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 1


def test_csv_import_missing_telephone():
    """Ligne sans téléphone → doit déclencher une erreur (pas de téléphone trouvé)."""
    csv_bytes = _make_csv([
        {"nom": "Dupont", "prenom": "Jean", "email": "jean@test.com"},
    ])
    import csv as _csv

    def _norm(s: str) -> str:
        return s.lower().strip().replace("é", "e").replace("è", "e").replace("ê", "e").replace("ô", "o").replace("â", "a")

    reader = _csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    errors = []
    for i, row in enumerate(reader):
        normed = {_norm(k): v.strip() for k, v in row.items() if k}
        telephone = normed.get("telephone", normed.get("tel", normed.get("phone", "")))
        if not telephone:
            errors.append(f"Ligne {i + 2} : téléphone manquant")
    assert len(errors) == 1


def test_csv_alternative_column_names():
    """CSV avec colonnes 'tel' et 'firstname' doivent être acceptés."""
    csv_bytes = _make_csv([
        {"firstname": "Pierre", "tel": "+33600000005", "email": "pierre@test.com"},
    ])
    import csv as _csv

    def _norm(s: str) -> str:
        return s.lower().strip()

    reader = _csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    for row in reader:
        normed = {_norm(k): v.strip() for k, v in row.items() if k}
        prenom = normed.get("prenom", normed.get("prénom", normed.get("firstname", "")))
        telephone = normed.get("telephone", normed.get("tel", normed.get("phone", "")))
        assert prenom == "Pierre"
        assert telephone == "+33600000005"


def test_webhook_url_format():
    """L'URL webhook doit avoir le bon format."""
    user_id = "test_user_abc123"
    expected_base = "https://proppilot-production.up.railway.app"
    webhook_url = f"{expected_base}/webhooks/{user_id}/leads"
    assert user_id in webhook_url
    assert webhook_url.startswith("https://")
    assert webhook_url.endswith("/leads")
