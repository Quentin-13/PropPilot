# CRM Connectors — PropPilot v1

> Sens unique : PropPilot → CRM. Chaque lead qualifié est automatiquement pushé vers le CRM configuré.

---

## Architecture

```
lib/crm_connectors/
├── base.py           → Interface CRMConnector (push_lead, test_connection)
├── apimo_mapping.py  → Mapping champs PropPilot → Apimo (ajustable sans casser le code)
├── apimo.py          → Connecteur Apimo (POST /contacts + POST /contacts/{id}/notes)
├── email_parsing.py  → Connecteur email universel (plain text SendGrid)
└── factory.py        → Sélection du connecteur selon crm_type du client
```

### Flux de données

```
Lead extrait (SMS ou appel)
    │
    ├─► compute_next_action(lead_id)    → stocke next_action_* dans leads
    │
    └─► push_lead_to_crm(client_id, lead_data)
              │
              ├── crm_type = 'apimo'  → ApimoConnector.push_lead()
              ├── crm_type = 'email'  → EmailParsingConnector.push_lead()
              └── crm_type = 'none'   → rien
```

Le push est **non-bloquant** : une erreur CRM ne perturbe pas le pipeline lead.

---

## Chantier 1 — Migration DB (015)

La migration 015 ajoute :

**Table `users`** (= clients PropPilot) :
| Colonne | Type | Description |
|---|---|---|
| `crm_type` | VARCHAR(32) | `apimo` \| `email` \| `none` |
| `crm_config` | JSONB | Credentials spécifiques (voir ci-dessous) |
| `crm_last_sync_at` | TIMESTAMP | Dernière sync réussie |
| `crm_last_error` | TEXT | Dernière erreur (effacée en cas de succès) |

**Table `leads`** :
| Colonne | Type | Description |
|---|---|---|
| `next_action_label` | TEXT | Action courte (≤ 80 car.) |
| `next_action_priority` | VARCHAR(16) | `haute` \| `moyenne` \| `basse` |
| `next_action_reason` | TEXT | Explication pour l'agent |
| `next_action_deadline` | TIMESTAMP | Date limite suggérée |
| `next_action_computed_at` | TIMESTAMP | Timestamp du dernier calcul |

**Nouvelle table `crm_sync_log`** :
| Colonne | Type | Description |
|---|---|---|
| `id` | SERIAL | Auto-increment |
| `client_id` | TEXT | ID client PropPilot |
| `lead_id` | TEXT | ID lead |
| `connector_type` | TEXT | `apimo` \| `email` |
| `status` | TEXT | `success` \| `error` |
| `error` | TEXT | Message d'erreur si status=error |
| `sent_at` | TIMESTAMP | Date de l'envoi |

---

## Chantier 2 — Connecteur Apimo

### Configuration côté client (crm_config JSONB)

```json
{
  "provider_id": "12345",
  "api_token": "votre_token_apimo"
}
```

**Comment obtenir les credentials Apimo :**
1. Connectez-vous à [apimo.pro](https://apimo.pro)
2. Paramètres → API → Créer un token
3. Notez le **Provider ID** (visible dans l'URL de votre agence) et le **Token**

### Ce que PropPilot pousse vers Apimo

1. **Contact** (`POST /providers/{provider_id}/contacts`) :
   - `first_name`, `last_name`, `phone`, `email`
   - `comment` : résumé court (score + type projet)

2. **Note** (`POST /providers/{provider_id}/contacts/{id}/notes`) :
   - Score PropPilot + tag (`#proppilot-chaud` / `#proppilot-tiede` / `#proppilot-froid`)
   - Détails : projet, budget, zone, type de bien, surface, motivation
   - Résumé IA
   - Action recommandée

### Gestion des erreurs

| Situation | Comportement |
|---|---|
| HTTP 401 | Pas de retry. `crm_last_error` mis à jour. Admin notifié via logs. |
| Erreur réseau | Retry 3x avec backoff 1s / 3s / 9s |
| HTTP 500 | Retry 3x, puis `crm_last_error` mis à jour. Lead reste dans PropPilot. |
| Mock mode (token vide ou `test_*`) | Log `[MOCK]` + retourne True sans appel réel |

---

## Chantier 3 — Connecteur Email parsing universel

Compatible avec tous les CRM qui importent des leads via leur boîte mail :
**Netty, Hektor (La Boîte Immo), Modelo Office, Périclès, Krea**, et tout autre CRM avec email d'import.

### Configuration côté client (crm_config JSONB)

```json
{
  "target_email": "import@mon-crm.fr",
  "crm_label": "Netty"
}
```

### Format de l'email généré

**Sujet :**
```
[Lead PropPilot] Marie Dupont - Achat - Chaud [ACTION: Rappeler avant 18h]
```

**Corps (plain text, PAS HTML) :**
```
=== LEAD PROPPILOT ===

Nom: Dupont
Prénom: Marie
Téléphone: +33612345678
Email: marie.dupont@test.fr

Type projet: achat
Budget: 300 000 € — 400 000 €
Zone: Lyon 6ème
Type bien: T3
Surface: 65 — 80 m²
Motivation: mutation_pro
Score: chaud
Résumé: Acheteur T3 Lyon 6, mutation professionnelle, budget 300-400k.
Source: PropPilot

=== ACTION RECOMMANDÉE ===
Action recommandée: Rappeler avant 18h
Pourquoi: Lead chaud non recontacté depuis 24h.

=== FIN ===
```

**Reply-To :** email du conseiller PropPilot (pour recevoir les réponses directement)

### Trouver l'email d'import de votre CRM

| CRM | Où trouver l'email d'import |
|---|---|
| Netty | Paramètres → Import → Email d'import leads |
| Hektor | Administration → Import → Email entrant |
| Modelo Office | Paramètres → Intégrations → Email |
| Périclès | Contact support Périclès pour activer |
| Autre | Documentation de votre CRM → "import email" |

---

## Chantier 6 — Action recommandée (next_action)

### Comment ça marche

À chaque extraction SMS ou appel, PropPilot :
1. Charge l'historique complet du lead (toutes conversations + appels)
2. Calcule le silence depuis le dernier contact agent → prospect
3. Appelle Claude pour générer une action courte et actionnable
4. Stocke le résultat dans `leads.next_action_*`

**Cache anti-doublon :** si le dernier calcul date de moins de 30 minutes ET qu'il n'y a pas eu de nouveau message, on réutilise l'action existante (économie tokens).

### Priorités

| Score | Priorité par défaut |
|---|---|
| ≥ 18/24 (chaud) | haute |
| 11–17/24 (tiède) | moyenne |
| < 11/24 (froid) | basse |

La priorité peut être réévaluée à la baisse si le lead est déjà en nurturing ou en silène court.

---

## Ajouter un nouveau connecteur CRM (après validation Apimo + email)

1. Créer `lib/crm_connectors/moncrm.py` avec une classe héritant de `CRMConnector`
2. Implémenter `push_lead(lead_data: dict) -> bool` et `test_connection() -> dict`
3. Ajouter le mapping dans `lib/crm_connectors/moncrm_mapping.py`
4. Ajouter le cas dans `factory._get_connector_and_type()`
5. Ajouter l'option dans le dashboard `dashboard/pages/06_parametres.py`
6. Écrire les tests dans `tests/test_crm_push_connectors.py`

Le `crm_config` JSONB accueille les credentials sans migration supplémentaire.

---

## Commandes de test

```bash
# Tests unitaires
pytest tests/test_crm_push_connectors.py -v

# Test manuel push Apimo (mock)
python -c "
from lib.crm_connectors.apimo import ApimoConnector
c = ApimoConnector('', '')  # mock auto
c.push_lead({'id':'test','prenom':'Jean','nom':'Test','score_label':'chaud','type_projet':'achat'})
"

# Test manuel push email (mock)
python -c "
from lib.crm_connectors.email_parsing import EmailParsingConnector
c = EmailParsingConnector('import@test.fr')
c.push_lead({'id':'test','prenom':'Jean','nom':'Test','score_label':'chaud','type_projet':'achat'})
"
```
