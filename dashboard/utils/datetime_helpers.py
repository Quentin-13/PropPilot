"""Helpers pour l'affichage des dates en timezone Europe/Paris."""
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

PARIS_TZ = ZoneInfo("Europe/Paris")


def to_paris_tz(dt: Optional[datetime]) -> Optional[datetime]:
    """Convertit un datetime UTC (naive ou aware) en Europe/Paris aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Datetime naive → on suppose UTC (convention DB du projet)
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(PARIS_TZ)


def fmt_paris_datetime(dt: Optional[datetime], pattern: str = "%d/%m/%Y %H:%M") -> str:
    """Formate un datetime en heure de Paris. Retourne '—' si None."""
    if dt is None:
        return "—"
    return to_paris_tz(dt).strftime(pattern)
