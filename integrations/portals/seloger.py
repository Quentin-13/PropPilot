"""
Portail SeLoger — re-export des handlers existants.
Maintenu pour compatibilité structurelle avec integrations/portals/.
L'implémentation réelle est dans integrations/seloger_webhook.py.
"""
from integrations.seloger_webhook import (  # noqa: F401
    handle_seloger_lead,
    parse_seloger_lead,
    verify_seloger_signature,
)

PORTAL_NAME = "SeLoger"
