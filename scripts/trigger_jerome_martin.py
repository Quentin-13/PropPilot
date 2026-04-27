#!/usr/bin/env python3
"""
Trigger Jérôme Martin — Test end-to-end Twilio pour démo Dumortier.

Simule un lead SeLoger entrant pour Jérôme Martin et déclenche Léa
qui envoie un VRAI SMS sur +33614150263 depuis le numéro Twilio du compte démo.

Usage :
    TESTING=true  python scripts/trigger_jerome_martin.py  # mode mock local
    TESTING=false python scripts/trigger_jerome_martin.py  # mode prod (vrai SMS)

Variables requises en prod :
    DATABASE_URL, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_AVAILABLE_NUMBERS
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Path ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Mode (doit être défini AVANT le premier import de settings) ───────────────
TESTING = os.environ.get("TESTING", "true").lower() in ("1", "true", "yes")
os.environ["TESTING"] = "true" if TESTING else "false"

# ── Invalidation du cache settings si déjà chargé ────────────────────────────
try:
    from config.settings import get_settings as _gs
    _gs.cache_clear()
except Exception:
    pass

# ── Imports ──────────────────────────────────────────────────────────────────
import uuid
from datetime import datetime

from config.settings import get_settings

# ── Constantes ───────────────────────────────────────────────────────────────
DEMO_USER_ID    = "demo-dumortier-gh-st-etienne"
DEMO_EMAIL      = "demo.dumortier@proppilot.fr"
JEROME_TEL      = "+33614150263"
JEROME_PRENOM   = "Jérôme"
JEROME_NOM      = "Martin"
DEMO_TWILIO_NUM = "+33757596114"   # numéro assigné au compte démo

SELOGER_PAYLOAD = {
    "lead_id": f"SL-JEROME-{datetime.now().strftime('%Y%m%d%H%M')}",
    "contact": {
        "firstname": JEROME_PRENOM,
        "lastname": JEROME_NOM,
        "phone": "0614150263",
        "email": "jerome.martin.st42@gmail.com",
    },
    "property": {
        "reference": "SL-VERDUN-42000",
        "type": "maison",
        "price": 350000,
        "area": 110,
    },
    "message": (
        "Bonjour, je suis intéressé par votre maison 4 pièces avenue de Verdun à "
        "Saint-Étienne (350 000€). Pouvez-vous me contacter pour organiser une visite ?"
    ),
    "source": "seloger",
    "created_at": datetime.now().isoformat(),
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers log
# ─────────────────────────────────────────────────────────────────────────────

def step(emoji: str, msg: str) -> None:
    print(f"\n{emoji}  {msg}")


def ok(msg: str) -> None:
    print(f"   ✅ {msg}")


def warn(msg: str) -> None:
    print(f"   ⚠️  {msg}")


def fail(msg: str) -> None:
    print(f"   ❌ {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Validation pré-lancement
# ─────────────────────────────────────────────────────────────────────────────

def check_prerequisites(settings) -> bool:
    step("🔍", "Vérification des prérequis")

    mode_label = "🟡 MOCK (aucun SMS réel)" if TESTING else "🔴 PRODUCTION (vrai SMS Twilio)"
    print(f"   Mode : {mode_label}")

    if not TESTING:
        missing = []
        if not settings.twilio_available_numbers:
            missing.append("TWILIO_AVAILABLE_NUMBERS")
        if not settings.twilio_auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not settings.twilio_account_sid:
            missing.append("TWILIO_ACCOUNT_SID")

        if missing:
            fail(f"Variables manquantes pour le mode prod : {', '.join(missing)}")
            print("\n   Ajoutez-les dans votre .env ou Railway, puis relancez.")
            return False

        # Vérifie que le numéro démo est dans le pool
        if DEMO_TWILIO_NUM not in settings.twilio_available_numbers:
            warn(f"{DEMO_TWILIO_NUM} absent de TWILIO_AVAILABLE_NUMBERS — le numéro expéditeur "
                 "sera TWILIO_SMS_NUMBER par défaut")

    ok("Prérequis OK")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 2. Connexion DB + récupération user
# ─────────────────────────────────────────────────────────────────────────────

def get_demo_user(conn) -> dict | None:
    step("👤", f"Récupération utilisateur {DEMO_EMAIL}")
    row = conn.execute(
        "SELECT id, email, plan, plan_active, twilio_sms_number FROM users WHERE email = %s",
        (DEMO_EMAIL,),
    ).fetchone()

    if not row:
        fail(f"Utilisateur {DEMO_EMAIL} introuvable — lancez d'abord seed_demo_dumortier.py")
        return None

    user = dict(row)
    ok(f"User trouvé : {user['email']} | plan={user['plan']} | actif={user['plan_active']}")
    ok(f"Numéro Twilio assigné : {user['twilio_sms_number'] or '(aucun)'}")
    return user


# ─────────────────────────────────────────────────────────────────────────────
# 3. Récupération lead Jérôme Martin
# ─────────────────────────────────────────────────────────────────────────────

def get_jerome_lead(conn, user_id: str) -> dict | None:
    step("🔎", f"Recherche lead Jérôme Martin ({JEROME_TEL})")
    row = conn.execute(
        "SELECT id, prenom, nom, telephone, statut, score FROM leads "
        "WHERE client_id = %s AND telephone = %s",
        (user_id, JEROME_TEL),
    ).fetchone()

    if not row:
        warn("Lead Jérôme Martin introuvable — il sera créé lors du trigger")
        return None

    lead = dict(row)
    ok(f"Lead trouvé : {lead['prenom']} {lead['nom']} | statut={lead['statut']} | score={lead['score']}")
    return lead


# ─────────────────────────────────────────────────────────────────────────────
# 4. Reset état du lead
# ─────────────────────────────────────────────────────────────────────────────

def reset_jerome(conn, lead: dict | None, user_id: str) -> None:
    step("🔄", "Reset état Jérôme Martin")

    if lead:
        lead_id = lead["id"]

        # Supprime l'historique SMS
        conn.execute(
            "DELETE FROM conversations WHERE lead_id = %s",
            (lead_id,),
        )
        ok("Historique SMS supprimé")

        # Supprime le journey
        conn.execute(
            "DELETE FROM lead_journey WHERE lead_id = %s",
            (lead_id,),
        )
        ok("Journey supprimé")

        # Supprime le lead lui-même pour permettre une recréation propre
        conn.execute(
            "DELETE FROM leads WHERE id = %s",
            (lead_id,),
        )
        ok(f"Lead supprimé (id={lead_id[:8]}…) — sera recréé par Léa")
    else:
        ok("Pas de lead existant — rien à supprimer")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Trigger orchestrateur
# ─────────────────────────────────────────────────────────────────────────────

def trigger_orchestrator(user: dict) -> dict:
    step("📥", "Capture lead SeLoger (Léa supprimée — stockage seul)")

    from integrations.seloger_webhook import handle_seloger_lead

    result = handle_seloger_lead(
        payload=SELOGER_PAYLOAD,
        client_id=user["id"],
        tier=user.get("plan", "Pro"),
    )

    lead_id = result.get("lead_id", "")
    success = result.get("success", False)

    if not success:
        fail(f"Échec capture lead : {result.get('error', 'inconnu')}")
        return {"success": False, "lead_id": lead_id, "message": "", "status": "error"}

    ok(f"Lead capturé : {lead_id[:8] if lead_id else 'N/A'}…")
    return {"success": True, "lead_id": lead_id, "message": "", "status": "entrant"}


# ─────────────────────────────────────────────────────────────────────────────
# 6. Envoi SMS
# ─────────────────────────────────────────────────────────────────────────────

def send_sms(user: dict, message: str) -> dict:
    step("📱", f"Envoi SMS → {JEROME_TEL}")

    from tools.twilio_tool import TwilioTool

    twilio = TwilioTool()

    # Numéro expéditeur : numéro assigné au compte démo en priorité
    from_number = user.get("twilio_sms_number") or DEMO_TWILIO_NUM
    print(f"   Expéditeur : {from_number}")
    print(f"   Destinataire : {JEROME_TEL}")

    result = twilio.send_sms(
        to=JEROME_TEL,
        body=message,
        from_number=from_number,
    )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Résumé final
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(
    sms_result: dict,
    orch_result: dict,
    settings,
) -> None:
    print("\n" + "═" * 60)
    print("  RÉSUMÉ — TEST END-TO-END TWILIO")
    print("═" * 60)

    # Statut SMS
    if sms_result.get("success"):
        is_mock = sms_result.get("mock", False)
        sid     = sms_result.get("sid", "—")
        if is_mock:
            print(f"\n  📨 SMS         : ✅ MOCK simulé (aucun SMS réel envoyé)")
            print(f"  🆔 SID mock    : {sid}")
        else:
            print(f"\n  📨 SMS         : ✅ ENVOYÉ en production")
            print(f"  🆔 SID Twilio  : {sid}")
            print(f"  📶 Statut      : {sms_result.get('status', '—')}")
    else:
        print(f"\n  📨 SMS         : ❌ ÉCHEC")
        print(f"  💥 Erreur      : {sms_result.get('error', 'inconnue')}")

    print(f"\n  👤 Lead ID     : {orch_result.get('lead_id', '—')}")
    print(f"  📊 Statut lead : {orch_result.get('status', '—')}")

    # Instructions test conversation
    print("\n" + "─" * 60)
    print("  POUR TESTER LA CONVERSATION :")
    print("─" * 60)
    print(f"\n  1. Vérifiez la réception du SMS sur +33614150263")
    print(f"  2. Répondez au SMS depuis ce numéro")
    print(f"  3. Léa devrait qualifier en 7 questions")
    print(f"  4. Consultez le dashboard démo :")
    print(f"     → Connexion : {DEMO_EMAIL} / PropPilot2026!")
    print(f"     → Page 'Conversations' → thread Jérôme Martin")
    print(f"\n  Webhook Twilio configuré sur :")
    print(f"     https://[votre-domaine].railway.app/webhooks/sms")
    print(f"  (numéro : {user_sms_num_global or DEMO_TWILIO_NUM})")
    print("\n" + "═" * 60 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

user_sms_num_global: str = ""  # partagé pour le résumé final


def main() -> int:
    global user_sms_num_global

    print("\n" + "═" * 60)
    print("  TRIGGER JÉRÔME MARTIN — PropPilot Démo Dumortier")
    print("═" * 60)

    settings = get_settings()

    # ── 1. Prérequis ────────────────────────────────────────────────────────
    if not check_prerequisites(settings):
        return 1

    # ── 2 + 3 + 4. DB operations ────────────────────────────────────────────
    from memory.database import get_connection

    try:
        with get_connection() as conn:
            user = get_demo_user(conn)
            if not user:
                return 1

            user_sms_num_global = user.get("twilio_sms_number") or ""

            jerome = get_jerome_lead(conn, user["id"])
            reset_jerome(conn, jerome, user["id"])

    except Exception as e:
        fail(f"Erreur DB : {e}")
        return 1

    # ── 5. Orchestrateur ────────────────────────────────────────────────────
    try:
        orch_result = trigger_orchestrator(user)
    except Exception as e:
        fail(f"Erreur orchestrateur : {e}")
        return 1

    if not orch_result["success"]:
        fail("Orchestrateur en échec — SMS non envoyé")
        return 1

    # ── 6. Envoi SMS ────────────────────────────────────────────────────────
    try:
        sms_result = send_sms(user, orch_result["message"])
    except Exception as e:
        fail(f"Erreur envoi SMS : {e}")
        sms_result = {"success": False, "error": str(e)}

    if sms_result.get("success"):
        if sms_result.get("mock"):
            ok("SMS mock envoyé (TESTING=true)")
        else:
            ok(f"SMS réel envoyé — SID: {sms_result.get('sid')}")
    else:
        fail(f"SMS non envoyé : {sms_result.get('error')}")

    # ── Résumé ───────────────────────────────────────────────────────────────
    print_summary(sms_result, orch_result, settings)

    return 0 if sms_result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
