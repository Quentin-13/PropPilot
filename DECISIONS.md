# PropPilot — Décisions Architecturales — Sprint Nettoyage

**Date** : 2026-04-26  
**Branche** : `cleanup-pivot`  
**Contexte** : Pivot stratégique vers une plateforme de capture multi-canal. PropPilot ne répond plus aux leads à la place de l'agent — il capture, transcrit, structure et alimente le CRM. L'agent humain garde la relation.

---

## Vision cible

| Avant (IA parle au lead) | Après (IA capture + structure) |
|---|---|
| SMS auto de qualification (Léa) | Capture SMS entrant → tâche dashboard agent |
| Relances SMS auto (Marc) | Rappels intelligents dans le dashboard |
| Appels IA Retell | Enregistrement Twilio + transcription Whisper |
| Réponse voix ElevenLabs | Supprimé |
| SMSPartner alternatif | Supprimé (Twilio uniquement) |

---

## Décisions validées

### D1 — Retell AI : SUPPRESSION COMPLÈTE

**Périmètre supprimé :**
- Webhook `POST /webhooks/retell`
- Agent `VoiceInboundAgent` (`agents/voice_inbound.py`)
- Variables d'env : `RETELL_API_KEY`, `RETELL_AGENT_ID`
- Référence dans `cost_logger.py`

**Préservé intentionnellement :**
- Colonne `calls.retell_call_id` en DB — sera renommée `recording_url` dans le sprint Capture Appels, pas de DROP maintenant

**Raison :** Retell gérait les appels IA entrants. La nouvelle archi enregistre les appels réels de l'agent via Twilio Recording + transcription Whisper.

---

### D2 — Léa (qualification SMS automatique) : SUPPRESSION COMPLÈTE

**Périmètre supprimé :**
- `agents/lead_qualifier.py` — `LeadQualifierAgent`
- `orchestrator.py` — LangGraph StateGraph complet (drove Léa)
- SMS sortants automatiques de qualification depuis le webhook `/webhooks/twilio/sms`
- Prompts : `LEAD_QUALIFIER_SYSTEM`, `LEAD_QUALIFIER_FIRST_MESSAGE`, `LEAD_QUALIFIER_FIRST_MESSAGE_ANONYMOUS` dans `config/prompts.py`

**Logique réutilisable extraite** (voir LEGACY_SALVAGE.md) :
- Système de scoring 1-10 (urgence/budget/motivation) → `lib/lead_extraction/scoring.py`
- Schéma de données structurées leads → `lib/lead_extraction/schema.py`
- Prompt d'extraction info depuis texte → `lib/lead_extraction/prompts.py`

**Comportement du webhook `/webhooks/twilio/sms` après nettoyage :**
- SMS entrant reçu → stocké en DB (table `conversations`)
- Tâche "Nouveau SMS de [numéro]" créée dans `reminders` pour le dashboard agent
- Aucune réponse SMS sortante automatique

**Raison :** L'IA répondant au lead à la place de l'agent créait de la friction et de la méfiance. L'agent doit rester maître de sa relation client.

---

### D3 — Marc (relances automatiques) : TRANSFORMATION

**Ce qui reste :**
- `agents/nurturing.py` — `NurturingAgent` (renommé mentalement "Système de rappels")
- Logique de scheduling APScheduler
- Logique de détection des leads à relancer (statut, dernière interaction)

**Ce qui change :**
- `send_followup()` : au lieu d'envoyer un SMS via Twilio, crée une entrée dans la table `reminders`
- `process_due_followups()` : toujours déclenché par le cron, mais produit des tâches au lieu de SMS

**Schéma `reminders` (nouvelle table)** :
```sql
CREATE TABLE IF NOT EXISTS reminders (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    lead_id     TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    type        TEXT NOT NULL,          -- callback, follow_up, new_sms, new_call
    title       TEXT NOT NULL,
    body        TEXT DEFAULT '',
    scheduled_at TIMESTAMPTZ NOT NULL,
    status      TEXT DEFAULT 'pending', -- pending, done, dismissed
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

**Raison :** Les SMS automatiques de relance étaient perçus comme du spam. Les rappels dans le dashboard donnent à l'agent le contrôle total sur ce qu'il envoie et quand.

---

### D4 — Hugo (annonces), Thomas (estimation), Julie (anomalies) : DÉSACTIVATION

**Option retenue : Option B — code dormant**

**Périmètre désactivé :**
- Routes API servies par ces agents conditionnées à `ENABLE_LEGACY_AGENTS=false` (défaut)
- Pages dashboard retirées de la navigation Streamlit
- Code conservé dans le repo

**Ce qui reste accessible manuellement :**
- `agents/listing_generator.py` — `ListingGeneratorAgent` (Hugo)
- `agents/estimation.py` — `EstimationAgent` (Thomas)
- `agents/anomaly_detector.py` — `AnomalyDetectorAgent` (Julie)
- Pages dashboard : `04_annonce.py`, `05_estimation.py` (accessible si ENABLE_LEGACY_AGENTS=true)

**Décision finale** : dans 6 mois (avant 2026-10-26), évaluer si ces features sont réactivées ou supprimées définitivement.

**Raison :** Ces agents ont de la valeur mais ne font pas partie du MVP capture multi-canal. Les désactiver évite la confusion sans perdre le travail réalisé.

---

### D5 — ElevenLabs : SUPPRESSION COMPLÈTE

**Périmètre supprimé :**
- `tools/elevenlabs_tool.py`
- Variables d'env : `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`
- Settings : `elevenlabs_api_key`, `elevenlabs_voice_id`, `elevenlabs_model_id`, `elevenlabs_available`
- 147 fichiers MP3 dans `data/audio/`

**Raison :** ElevenLabs servait la voix de Léa/Sophie pour les appels IA Retell. Retell supprimé → ElevenLabs inutile. La voix TTS dans les appels sera gérée par Twilio nativement (sprint suivant).

---

### D6 — SMSPartner : SUPPRESSION DU CODE

**Périmètre supprimé :**
- `tools/smspartner_tool.py`
- `validate_smspartner_request()` dans `tools/security.py`
- Variables d'env : `SMSPARTNER_API_KEY`
- Settings : `smspartner_api_key`, `smspartner_webhook_secret`

**Préservé intentionnellement :**
- Colonne `users.smspartner_number` en DB — marquée deprecated, pas de DROP

**Raison :** SMSPartner permettait d'optimiser les coûts SMS en France. Dans la nouvelle archi, les agents ont leur propre numéro Twilio et les SMS sont de l'agent vers le lead (pas de l'IA). Coût SMS réduit car volume faible.  
**Note :** Peut être rebranché si les coûts Twilio SMS deviennent un problème (voir LEGACY_SALVAGE.md).

---

### D7 — Routes SMS doublons : NETTOYAGE

**Supprimé :**
- `POST /webhooks/sms` — ancienne architecture mono-client sans lookup numéro
- `POST /webhooks/sms/status` — callback statut associé

**Conservé :**
- `POST /webhooks/twilio/sms` — route principale multi-clients, lookup par `twilio_sms_number`

**Action manuelle requise :** Vérifier dans la console Twilio que tous les numéros sont bien configurés sur `POST /webhooks/twilio/sms` et non sur l'ancienne URL `/webhooks/sms`.

---

## Migrations DB pendantes (sprints futurs)

| Colonne | Action future | Sprint |
|---|---|---|
| `calls.retell_call_id` | Renommer en `recording_url` | Sprint Capture Appels |
| `users.smspartner_number` | DROP après vérification que la colonne est bien vide | Sprint DB Cleanup |

---

## Alembic

Alembic initialisé dans ce sprint avec une migration baseline qui reflète le schéma actuel **sans** supprimer les colonnes legacy. Les suppressions de colonnes seront dans des migrations futures séparées.
