# Dashboard super-admin PropPilot

## Accès

URL directe : `/99_admin` dans le dashboard Streamlit.
Aucun lien visible dans les pages client — accessible uniquement si tu connais l'URL.

Authentification en deux temps :
1. Login normal via `/auth/login` (compte `contact@proppilot.fr`)
2. Vérification email contre `SUPER_ADMIN_EMAILS` en tête de page → `st.stop()` si refusé

Chaque accès est logué dans la table `admin_access_log`.

## Variables d'env Railway à ajouter

| Variable | Valeur | Description |
|---|---|---|
| `SUPER_ADMIN_EMAILS` | `contact@proppilot.fr` | CSV pour ajouter d'autres admins plus tard |
| `INFRA_FIXED_COST_EUR_MONTHLY` | `20` | Coût Railway + autres infra (à ajuster) |

## Migration à appliquer

```bash
alembic upgrade 013
```

Crée 3 tables :
- `twilio_usage` — coûts Twilio par client (vide tant que non instrumenté)
- `user_activity` — activité dashboard par user (vide tant que non instrumenté)
- `admin_access_log` — log des accès à cette page admin

## 5 onglets

### Business
- MRR calculé depuis `users.plan × tarif_fixe` (Starter=790€, Pro=1490€, Elite=2990€)
- Clients payants = `plan_active=True AND subscription_status='active'`
- Pilotes = `plan_active=True AND subscription_status!='active'`
- Churn = `plan_active=False` (pas de date précise — voir TODO)
- Courbe clients actifs par mois depuis `usage_tracking`

### Coûts & Marge
- Coûts Claude depuis `api_actions.cost_euros` — **opérationnel**
- Coûts Twilio depuis `twilio_usage` — **vide** (voir TODO ci-dessous)
- Marge = MRR − tokens − Twilio − infra fixe
- Top 10 clients par coût tokens — **opérationnel**

### Santé produit
- Leads extraits 1j/7j/30j depuis `leads` — **opérationnel**
- Taux failed depuis `leads.extraction_status` — **opérationnel**
- Alertes automatiques : failed > 5% → `st.error`, 0 leads en heures ouvrées → `st.warning`
- Distribution lead_type / scores — **opérationnel**
- Tableau extractions échouées avec filtre par client — **opérationnel**

### Activité utilisateurs
- Depuis `user_activity` — **vide** (voir TODO ci-dessous)
- Clients silencieux avec bouton "Check-in" (disabled — placeholder)

### Détail par client
- Vue 360° : coûts tokens filtrés par client depuis `api_actions` — **opérationnel**
- Coût Twilio par client — **vide**
- 20 derniers leads — **opérationnel**
- Export CSV leads — **opérationnel**

## TODOs pour rendre tout opérationnel

### Priorité 1 — Twilio costs
Instrumenter les webhooks Twilio dans `server.py` pour insérer dans `twilio_usage` :
```python
# Dans le handler de status callback Twilio
with get_connection() as conn:
    conn.execute(
        "INSERT INTO twilio_usage (client_id, type, cost_eur, metadata) VALUES (%s, %s, %s, %s)",
        (client_id, "sms_out", cost_eur, json.dumps(metadata)),
    )
```

### Priorité 2 — user_activity (logins)
Instrumenter `auth_ui.py` après login réussi :
```python
# Dans _set_session(), après st.session_state["authenticated"] = True
with get_connection() as conn:
    conn.execute(
        "INSERT INTO user_activity (user_id, client_id, action) VALUES (%s, %s, 'login')",
        (user_id, user_id),
    )
```

### Priorité 3 — MRR snapshot mensuel
Ajouter un CRON qui insère un snapshot MRR chaque 1er du mois dans une table `mrr_snapshots`
pour une courbe MRR exacte (actuellement approximée depuis `usage_tracking`).

### Priorité 4 — churn_at
Ajouter colonne `churned_at TIMESTAMP` à `users` pour un churn mensuel précis.

### Priorité 5 — latence extraction
Stocker `duration_ms` dans `api_actions.metadata` lors des appels Claude
pour mesurer la latence réelle d'extraction.

## Sécurité

- Toutes les fonctions `admin_get_*` font des SELECT sans filtre `client_id` — intentionnel et documenté.
- Ces fonctions ne doivent **jamais** être importées dans des pages client.
- La garde `SUPER_ADMIN_EMAILS` est vérifiée à chaque render Streamlit.
- Les accès sont loggés dans `admin_access_log`.
