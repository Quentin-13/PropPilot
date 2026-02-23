"""
Google Calendar Tool — Booking RDV automatique.
Mock automatique si GOOGLE_SERVICE_ACCOUNT_JSON absent.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)

# Créneaux disponibles par défaut (heures de bureau)
DEFAULT_SLOT_START = 9   # 9h
DEFAULT_SLOT_END = 18    # 18h
SLOT_DURATION_MIN = 30   # 30 min par créneau


class CalendarTool:
    """
    Wrapper Google Calendar API avec mock automatique.
    Utilisé par VoiceCallAgent pour booking RDV en temps réel.
    """

    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = not bool(self.settings.google_service_account_json)
        self._service = None
        if self.mock_mode:
            logger.info("[Calendar] Mode mock activé")

    def _get_service(self):
        if self._service is None and not self.mock_mode:
            import json as json_lib
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            creds_dict = json_lib.loads(self.settings.google_service_account_json)
            creds = Credentials.from_service_account_info(
                creds_dict,
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def get_available_slots(
        self,
        days_ahead: int = 7,
        slot_duration_min: int = SLOT_DURATION_MIN,
        start_hour: int = DEFAULT_SLOT_START,
        end_hour: int = DEFAULT_SLOT_END,
    ) -> list[dict]:
        """
        Retourne les créneaux disponibles dans les N prochains jours.

        Returns:
            [{"start": datetime, "end": datetime, "label": str, "label_short": str}]
        """
        if self.mock_mode:
            return self._mock_available_slots(days_ahead, slot_duration_min, start_hour, end_hour)

        try:
            service = self._get_service()
            calendar_id = self.settings.google_calendar_id

            now = datetime.utcnow()
            time_max = now + timedelta(days=days_ahead)

            # Récupérer les événements existants
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=now.isoformat() + "Z",
                timeMax=time_max.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            busy_times = []
            for event in events_result.get("items", []):
                start = event["start"].get("dateTime")
                end = event["end"].get("dateTime")
                if start and end:
                    busy_times.append((
                        datetime.fromisoformat(start.replace("Z", "+00:00")),
                        datetime.fromisoformat(end.replace("Z", "+00:00")),
                    ))

            # Générer les créneaux libres
            return self._compute_free_slots(now, days_ahead, slot_duration_min, start_hour, end_hour, busy_times)

        except Exception as e:
            logger.error(f"Erreur Calendar get_slots : {e}")
            return self._mock_available_slots(days_ahead, slot_duration_min, start_hour, end_hour)

    def book_slot(
        self,
        start_dt: datetime,
        title: str,
        description: str = "",
        attendee_email: Optional[str] = None,
        attendee_name: str = "",
        duration_min: int = SLOT_DURATION_MIN,
    ) -> dict:
        """
        Crée un RDV dans Google Calendar.

        Returns:
            {"success": bool, "event_id": str, "event_link": str, "mock": bool}
        """
        end_dt = start_dt + timedelta(minutes=duration_min)

        if self.mock_mode:
            event_id = f"mock_event_{start_dt.strftime('%Y%m%d_%H%M')}"
            logger.info(f"[MOCK Calendar] RDV créé : {title} | {start_dt.strftime('%d/%m %H:%M')}")
            return {
                "success": True,
                "event_id": event_id,
                "event_link": "",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "title": title,
                "mock": True,
            }

        try:
            service = self._get_service()
            calendar_id = self.settings.google_calendar_id

            event_body = {
                "summary": title,
                "description": description,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Paris"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Paris"},
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "email", "minutes": 60},
                        {"method": "popup", "minutes": 15},
                    ],
                },
            }

            if attendee_email:
                event_body["attendees"] = [{"email": attendee_email, "displayName": attendee_name}]

            event = service.events().insert(
                calendarId=calendar_id,
                body=event_body,
                sendUpdates="all" if attendee_email else "none",
            ).execute()

            logger.info(f"RDV créé : {event['id']} | {title}")
            return {
                "success": True,
                "event_id": event["id"],
                "event_link": event.get("htmlLink", ""),
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "title": title,
                "mock": False,
            }

        except Exception as e:
            logger.error(f"Erreur Calendar book_slot : {e}")
            return {"success": False, "error": str(e), "mock": False}

    def cancel_slot(self, event_id: str) -> dict:
        """Annule un RDV."""
        if self.mock_mode or event_id.startswith("mock_"):
            logger.info(f"[MOCK Calendar] RDV annulé : {event_id}")
            return {"success": True, "mock": True}

        try:
            service = self._get_service()
            service.events().delete(
                calendarId=self.settings.google_calendar_id,
                eventId=event_id,
            ).execute()
            return {"success": True, "mock": False}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_next_slots_for_voice(self, n: int = 2) -> list[str]:
        """
        Retourne N créneaux formatés pour lecture à voix haute.
        Utilisé par VoiceCallAgent pendant les appels.

        Returns: ["mardi à 10h30", "jeudi à 14h00"]
        """
        slots = self.get_available_slots(days_ahead=7)
        result = []
        for slot in slots[:n]:
            start = slot["start"]
            day_name = _french_day(start.weekday())
            time_str = start.strftime("%Hh%M").replace("h00", "h")
            result.append(f"{day_name} à {time_str}")
        return result or ["mardi à 10h", "jeudi à 14h"]

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _compute_free_slots(
        self,
        now: datetime,
        days_ahead: int,
        slot_duration_min: int,
        start_hour: int,
        end_hour: int,
        busy_times: list,
    ) -> list[dict]:
        """Calcule les créneaux libres en soustrayant les occupés."""
        free_slots = []
        current = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

        for _ in range(days_ahead * 2):
            if current.weekday() >= 5:  # week-end
                current += timedelta(hours=1)
                continue

            if current.hour < start_hour:
                current = current.replace(hour=start_hour, minute=0)
            elif current.hour >= end_hour:
                current = (current + timedelta(days=1)).replace(hour=start_hour, minute=0)
                continue

            slot_end = current + timedelta(minutes=slot_duration_min)

            # Vérifier si occupé
            is_busy = any(
                not (slot_end <= busy_start or current >= busy_end)
                for busy_start, busy_end in busy_times
            )

            if not is_busy:
                free_slots.append({
                    "start": current,
                    "end": slot_end,
                    "label": f"{_french_day(current.weekday())} {current.strftime('%d/%m')} à {current.strftime('%H:%M')}",
                    "label_short": f"{_french_day(current.weekday())} à {current.strftime('%Hh%M').replace('h00', 'h')}",
                })
                if len(free_slots) >= 20:
                    break

            current += timedelta(minutes=slot_duration_min)

        return free_slots

    def _mock_available_slots(
        self, days_ahead: int, slot_duration_min: int, start_hour: int, end_hour: int
    ) -> list[dict]:
        """Créneaux mock réalistes sur 7 jours."""
        slots = []
        now = datetime.now()

        # Trouver le prochain lundi
        days_to_monday = (7 - now.weekday()) % 7
        if days_to_monday == 0:
            days_to_monday = 7
        next_week_start = now + timedelta(days=days_to_monday)

        sample_times = [
            (0, 9, 30),   # Lundi 9h30
            (0, 14, 0),   # Lundi 14h
            (1, 10, 0),   # Mardi 10h
            (1, 15, 30),  # Mardi 15h30
            (2, 9, 0),    # Mercredi 9h
            (3, 11, 0),   # Jeudi 11h
            (3, 14, 30),  # Jeudi 14h30
            (4, 10, 30),  # Vendredi 10h30
        ]

        for day_offset, hour, minute in sample_times:
            slot_start = next_week_start.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
            slot_end = slot_start + timedelta(minutes=slot_duration_min)
            if slot_start > now:
                slots.append({
                    "start": slot_start,
                    "end": slot_end,
                    "label": f"{_french_day(slot_start.weekday())} {slot_start.strftime('%d/%m')} à {slot_start.strftime('%H:%M')}",
                    "label_short": f"{_french_day(slot_start.weekday())} à {slot_start.strftime('%Hh%M').replace('h00', 'h')}",
                })

        return slots


FRENCH_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

def _french_day(weekday: int) -> str:
    return FRENCH_DAYS[weekday]
