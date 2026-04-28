# Sprint A — MVP Capture d'Appels : État d'Avancement

**Branche** : `feature/mvp-call-capture`
**Statut** : ✅ Terminé
**Date** : 2026-04-28

---

## Récapitulatif des Livrables

### Variables d'Environnement Ajoutées

| Variable | Défaut | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Clé API OpenAI pour Whisper |
| `B2_ACCOUNT_ID` | — | ID compte Backblaze B2 |
| `B2_APPLICATION_KEY` | — | Clé application Backblaze B2 |
| `B2_BUCKET_NAME` | `proppilot-calls` | Nom du bucket B2 |
| `B2_BUCKET_ID` | — | ID du bucket B2 |
| `B2_ENDPOINT` | `https://s3.eu-central-003.backblazeb2.com` | Endpoint S3 B2 |
| `LEGAL_NOTICE_AUDIO_URL` | — | URL audio pré-enregistré (optionnel) |
| `FALLBACK_USE_TTS` | `true` | Utiliser TTS Twilio si pas d'audio |
| `LEGAL_NOTICE_TEXT` | *(voir .env.example)* | Mention légale appels entrants |
| `LEGAL_NOTICE_SHORT_TEXT` | `Appel enregistré via PropPilot.` | Mention courte appels sortants |
| `TWILIO_AVAILABLE_NUMBERS` | — | Pool numéros Twilio (virgule-séparés) |

---

### Routes API Ajoutées

#### Webhooks Twilio Voice
| Méthode | Route | Description |
|---|---|---|
| POST | `/webhooks/twilio/voice/incoming` | Appel entrant — TwiML mention légale + record + dial |
| POST | `/webhooks/twilio/voice/voicemail` | Pas de réponse — boîte vocale |
| POST | `/webhooks/twilio/voice/recording` | Fin d'enregistrement — pipeline B2 + Whisper + Claude |
| POST | `/webhooks/twilio/voice/status` | Mise à jour statut appel |

#### API Calls (authentifiée JWT)
| Méthode | Route | Description |
|---|---|---|
| POST | `/api/calls/outbound` | Initier un appel sortant (click-to-call) |
| GET | `/api/calls/outbound/twiml` | TwiML pour l'agent sortant |
| GET | `/api/calls/{call_id}` | Détails d'un appel |
| GET | `/api/calls/{call_id}/extraction` | Extraction structurée d'un appel |
| GET | `/api/calls` | Liste des appels (paginée) |

---

### Tables DB Créées/Modifiées

#### `calls` (enrichie — colonnes ajoutées)
`call_sid` (UNIQUE), `agency_id`, `agent_id`, `mode`, `from_number`, `to_number`,
`twilio_number`, `started_at`, `answered_at`, `ended_at`, `duration_seconds`,
`recording_url`, `recording_duration`, `transcript_text`, `transcript_segments` (JSONB),
`status`, `cost_twilio`, `cost_whisper`, `cost_claude`, `updated_at`

> Les colonnes Retell existantes (`retell_call_id`, `statut`, `duree_secondes`, etc.) sont conservées.

#### `call_extractions` (nouvelle)
`id`, `call_id` (FK → calls), `lead_id`, `type_projet`, `budget_min/max`,
`zone_geographique`, `type_bien`, `surface_min/max`, `criteres` (JSONB),
`timing` (JSONB), `financement` (JSONB), `motivation`, `score_qualification`,
`prochaine_action_suggeree`, `resume_appel`, `points_attention` (JSONB),
`extraction_model`, `extraction_prompt_version`, `extracted_at`

#### `agency_phone_numbers` (nouvelle)
`id`, `twilio_number` (UNIQUE), `agency_id`, `agent_id`, `agent_phone`, `label`, `active`

---

### Fichiers Créés

| Fichier | Rôle |
|---|---|
| `alembic/versions/002_calls_voice_capture.py` | Migration Alembic (upgrade + downgrade) |
| `lib/audio_storage.py` | Upload/Download/Delete Backblaze B2 (mock auto) |
| `lib/call_transcription.py` | Transcription Whisper (mock auto, retry ×3) |
| `lib/call_extraction_pipeline.py` | Extraction Claude 13 champs (mock auto) |
| `memory/call_repository.py` | CRUD calls + extractions + agency_phone_numbers |
| `webhooks/__init__.py` | Module webhooks |
| `webhooks/twilio_voice.py` | Router FastAPI webhooks voix |
| `api/__init__.py` | Module API |
| `api/calls.py` | Router FastAPI appels (click-to-call + consultation) |

### Fichiers Modifiés

| Fichier | Modification |
|---|---|
| `config/settings.py` | +OpenAI, +Backblaze B2, +mentions légales, `openai_available`, `b2_available` |
| `config/.env.example` | Documentation des nouvelles variables |
| `requirements.txt` | `openai>=1.30.0`, `boto3>=1.34.0` |
| `server.py` | Inclusion des routers `voice_router` + `calls_router` |

---

### Coût Estimé par Appel

| Composant | Coût estimé | Hypothèse |
|---|---|---|
| Twilio (enregistrement + stockage) | ~0,01-0,05 $/min | Tarif Twilio EU |
| Backblaze B2 (stockage) | ~0,001 $/Mo | 0,006 $/Go/mois |
| Whisper API | ~0,006 $/min | whisper-1 |
| Claude (extraction) | ~0,002-0,005 $ | ~500 tokens input + 100 output |
| **Total par appel de 5 min** | **~0,10-0,30 $** | — |

---

### Statuts des Appels (machine d'état)

```
initiated → ringing → answered → recorded → transcribed → extracted
                              ↓
                         no_answer / failed / voicemail / abandoned_legal_notice
                                                                   ↓
                                                         transcription_failed (retry ×3)
```

---

### Architecture du Pipeline (appel entrant)

```
Twilio appel entrant
       │
       ▼
/webhooks/twilio/voice/incoming
  → TwiML: mention légale (TTS) + <Dial record=…> vers agent
       │
       ▼ (fin appel)
/webhooks/twilio/voice/recording (BackgroundTask)
  → Download audio depuis Twilio (httpx)
  → Upload sur Backblaze B2 (boto3 S3)
  → Suppression chez Twilio
  → DB: status=recorded, recording_url=B2_URL
       │
       ▼ (chaîné)
lib/call_transcription.py
  → Download B2 → Whisper API → segments timestampés
  → DB: status=transcribed, transcript_text, transcript_segments
       │
       ▼ (chaîné)
lib/call_extraction_pipeline.py
  → Claude prompt 13 champs → CallExtractionData
  → DB call_extractions: type_projet, budget, score, résumé…
  → DB: status=extracted
```

---

### Procédure de Test End-to-End (appel réel)

#### Prérequis
1. Toutes les variables d'env configurées (Twilio, B2, OpenAI, Anthropic)
2. Migration Alembic appliquée : `alembic upgrade head`
3. Serveur démarré : `uvicorn server:app --reload`
4. Numéro Twilio configuré :
   - Aller dans **Twilio Console > Phone Numbers > [votre numéro] > Voice**
   - Webhook URL : `https://votre-domaine.fr/webhooks/twilio/voice/incoming`

#### Configurer le mapping numéro → agent (Mode 1)
```python
from memory.call_repository import upsert_phone_number
upsert_phone_number(
    twilio_number="+33757596114",
    agency_id="votre-user-id",
    agent_id="votre-user-id",
    agent_phone="+33XXXXXXXXX",  # portable de l'agent
    label="Numéro principal",
)
```

#### Test Mode 1 — Numéro dédié
1. Appeler le numéro Twilio depuis un téléphone externe
2. Vérifier : mention légale lue, transfert vers le portable de l'agent
3. Décrocher, parler 30s, raccrocher
4. Vérifier en DB : `SELECT * FROM calls WHERE call_sid = '...' \g`
5. Attendre ~2 min : statut devrait passer `recorded → transcribed → extracted`
6. Vérifier : `SELECT * FROM call_extractions WHERE call_id = '...' \g`

#### Test Mode 2 — Renvoi du numéro principal
1. Configurer le renvoi d'appel sur le numéro habituel vers le numéro Twilio
2. Appeler le numéro habituel
3. Vérifier que l'appel est bien capturé (mode=forwarded → même pipeline)

#### Test Click-to-Call sortant
```bash
curl -X POST http://localhost:8000/api/calls/outbound \
  -H "Authorization: Bearer <votre-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"lead_id": "<id-lead>", "agent_id": "<votre-user-id>", "lead_phone": "+33XXXXXXXXX"}'
```
- Twilio appelle l'agent
- Quand l'agent décroche : mention courte puis composition du lead
- Vérifier enregistrement en DB

---

### Configuration des 5 Numéros Twilio Actifs

Pour chaque numéro, configurer dans Twilio Console (Voice URL + méthode POST) :

| Numéro | URL à configurer |
|---|---|
| +33757596114 | `https://votre-domaine/webhooks/twilio/voice/incoming` |
| +33757596190 | idem |
| +33757595675 | idem |
| +33757596799 | idem |
| +33757598770 | idem |

---

### Risques et Points d'Attention

1. **B2 Endpoint** : vérifier que l'endpoint correspond à la région du bucket (EU ≠ US West). Aller dans Backblaze Console > Bucket > Endpoint pour obtenir la valeur exacte.

2. **Backblaze compte** : créer un compte sur backblaze.com > "B2 Cloud Storage" > Créer bucket (région EU, type : Private). Générer des Application Keys avec accès readFile + writeFile sur ce bucket.

3. **Coûts Twilio + durée** : Twilio facture le stockage des enregistrements. Le pipeline les supprime après upload B2. Si le webhook recording n'est pas appelé (timeout réseau), les enregistrements restent chez Twilio. À monitorer.

4. **Timeout webhook Twilio** : Twilio attend max 15s pour la réponse TwiML (`/incoming`). Le `_persist_incoming_call` est en BackgroundTask (non bloquant). OK.

5. **Retry transcription** : 3 tentatives avec backoff exponentiel (2s, 4s). Si les 3 échouent → status `transcription_failed`. Pas de notification encore (Sprint C).

6. **Mode 2 (renvoi)** : le mode est actuellement hardcodé `dedicated_number`. Si le numéro est configuré en renvoi, mettre à jour `mode='forwarded'` manuellement ou ajouter un paramètre URL au webhook.

---

### TODO (hors sprint A)

- [ ] Dashboard mémoire commerciale (Sprint C)
- [ ] Push extractions vers Hektor (Sprint B)
- [ ] Notifications email/SMS quand extraction terminée
- [ ] Recherche full-text dans les transcriptions
- [ ] Suppression auto des audios B2 après X jours (configurable)
- [ ] Mode 2 détection automatique (renvoi vs dédié)
- [ ] Monitoring coûts B2 + Whisper + Claude en dashboard admin
- [ ] `tests/test_call_repository.py` : tests CRUD avec DB réelle (nécessite PostgreSQL en CI)

---

### Commits du Sprint

```
80104fc Sprint A — Étapes 6-8 : tests unitaires + intégration (28 tests, 0 failure)
4344c7e Sprint A — Étapes 1-5 : migration + helpers + webhooks voix + click-to-call
```
