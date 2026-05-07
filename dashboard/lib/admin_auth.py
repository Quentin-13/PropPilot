"""
Helper partagé — détection super-admin.

Utilisé par :
- dashboard/app.py          (redirection post-login)
- dashboard/pages/99_admin.py (garde d'accès)
"""
from __future__ import annotations

import os


def get_admin_emails() -> list[str]:
    """Retourne la liste des emails super-admin depuis SUPER_ADMIN_EMAILS (env, CSV)."""
    raw = os.environ.get("SUPER_ADMIN_EMAILS", "contact@proppilot.fr")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def is_super_admin(email: str) -> bool:
    """Retourne True si l'email est dans la liste SUPER_ADMIN_EMAILS."""
    if not email:
        return False
    return email.strip().lower() in get_admin_emails()
