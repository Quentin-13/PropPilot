"""
Portail LeBonCoin Immo — re-export des handlers existants.
Maintenu pour compatibilité structurelle avec integrations/portals/.
L'implémentation réelle est dans integrations/seloger_webhook.py.
"""
from integrations.seloger_webhook import (  # noqa: F401
    handle_leboncoin_lead,
    parse_leboncoin_lead,
)

PORTAL_NAME = "LeBonCoin"
