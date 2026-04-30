# LEGACY_SALVAGE.md — Code récupérable supprimé

## Origine : dashboard/pages/11_integrations.py (supprimé 2026-04-30)

### Pattern Webhook URL

L'URL unique par client pour recevoir des leads depuis des sources externes :

```
https://proppilot-production.up.railway.app/webhooks/{user_id}/leads
```

Ce endpoint existe déjà dans `server.py` (`/webhooks/{client_id}/leads`).
La page Intégrations exposait simplement cette URL à l'utilisateur.
À réintégrer dans la page Paramètres ou une future page dédiée si la feature multi-source est développée.

### Import CSV leads (LeBonCoin, SeLoger, Manuel)

Logique d'appel API pour l'import CSV :

```python
result = _api(
    "post",
    "/api/leads/import",
    token,
    files={"file": (file.name, file.getvalue(), "text/csv")},
    data={"source": "leboncoin"},  # ou "seloger", ou valeur libre
)
imported = result.get("imported", 0)
errors   = result.get("errors", [])
```

Le endpoint `/api/leads/import` accepte :
- `file` : fichier CSV (colonnes : nom, prénom, téléphone, email)
- `source` : string libre identifiant la provenance

À réintégrer si on ajoute une section "Import leads" dans les Paramètres ou un wizard dédié.

### Configuration SeLoger webhook

Étapes à documenter à l'utilisateur pour la configuration SeLoger Pro :
1. Paramètres → Notifications → Webhooks
2. Ajouter un webhook
3. URL : `https://proppilot-production.up.railway.app/webhooks/{user_id}/leads`
4. Événement : "Nouveau contact"
