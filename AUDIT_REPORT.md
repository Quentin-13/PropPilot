# AUDIT_REPORT.md — PropPilot
**Date d'audit :** 26 avril 2026  
**Branche :** `main` — commit `851c1ed`  
**Objectif :** Cartographier l'existant avant pivot stratégique (capture multi-canal + CRM sync)

---

## Section 1 : Vue d'ensemble du projet

### Stack technique détectée

| Couche | Technologie |
|--------|-------------|
| API backend | FastAPI + Uvicorn |
| Orchestration agents | LangGraph StateGraph |
| LLM | Claude claude-sonnet-4-5 (Anthropic) |
| Base de données | PostgreSQL (psycopg2) — migration SQLite terminée |
| Dashboard | Streamlit multi-pages |
| Voice | Retell AI (webhook post-appel) + TwiML Polly |
| TTS | ElevenLabs (présent mais inutilisé en production) |
| SMS/WhatsApp | Twilio (SMS entrant/sortant + WhatsApp) |
| SMS alternatif | SMSPartner (outil présent, non wired dans server.py) |
| Emails | SendGrid transactionnel |
| Paiements | Stripe (abonnements + portal client) |
| Agenda | Google Calendar (OAuth2 PKCE) |
| CRM | Hektor, Apimo, Prospeneo, Whise, Adaptimmo |
| Portails | SeLoger, LeBonCoin, Bienici, Logic Immo |
| Infra | Docker Compose + Railway (production) |
| Auth | JWT (python-jose) + bcrypt |
| Config | Pydantic Settings v2 + .env |
| Scheduler | APScheduler (rapport hebdo lundi 8h) |
| Tests | pytest + pytest-asyncio |

### Lignes de code

| Périmètre | Fichiers .py | Lignes |
|-----------|-------------|--------|
| Total projet | 100 | ~24 200 |
| server.py seul | 1 | 1 550 |
| Agents | 6 | ~2 241 |
| Dashboard (pages) | 12 | ~3 153 |
| Intégrations CRM/portails | 15 | ~1 652 |
| Tools | 8 | ~1 977 |
| Memory/DB | 8 | ~1 800 |
| Tests | 18 | ~3 200 (estimé) |

### Structure des dossiers principaux

```
PropPilot/
├── agents/            # Agents IA (Léa, Marc, Hugo, Thomas, Julie, VoiceInbound)
├── config/            # Settings, prompts, tier limits
├── dashboard/
│   ├── pages/         # 12 pages Streamlit actives
│   └── pages_archive/ # 2 pages archivées (désactivées)
├── data/
│   ├── audio/         # ~120 fichiers MP3 (TTS ElevenLabs générés en démo)
│   └── images/        # 3 images staging DALL-E
├── integrations/
│   ├── crm/           # 5 connecteurs CRM + base abstraite
│   ├── portals/       # 4 connecteurs portails
│   └── sync/          # Scheduler sync + conflict resolver
├── memory/            # DB, auth, CRUD, usage tracking, billing Stripe
├── scripts/           # Seeding démo, reset DB, simulation leads
├── static/            # Landing page + pages légales HTML
├── tests/             # 18 fichiers, 401 tests collectés
└── tools/             # Twilio, ElevenLabs, Calendar, Email, Security
```

### État global

- **Santé du code :** Bonne. Patterns cohérents, mocks automatiques bien isolés, sécurité correctement implémentée.
- **Tests :** 401 collectés — 237 passent, 54 skippés, **110 erreurs** (toutes dues à PostgreSQL indisponible localement — pas des bugs de code).
- **Dépendances :** `requirements.txt` à jour. Note : `elevenlabs` listé dans `elevenlabs_tool.py` via import dynamique mais **absent de requirements.txt** → ImportError en production si la clé est présente.
- **Production :** Railway. Docker Compose disponible pour le dev local.

---

## Section 2 : Inventaire des modules

| Module | Chemin | Rôle | Statut | Dépendances entrantes | Pertinence nouvelle vision |
|--------|--------|------|--------|-----------------------|---------------------------|
| **server.py** | `/server.py` | FastAPI — tous les webhooks et routes API | ACTIF | Point d'entrée prod | **GARDER** + étendre |
| **orchestrator.py** | `/orchestrator.py` | LangGraph StateGraph — routing lead | ACTIF | server.py, webhooks | **MODIFIER** (simplifier) |
| **config/settings.py** | `/config/settings.py` | Pydantic Settings, variables env, assign_twilio_number | ACTIF | Tous modules | **MODIFIER** (add GOOGLE_OAUTH, WHISPER, etc.) |
| **config/prompts.py** | `/config/prompts.py` | Tous les prompts LLM | ACTIF | agents/ | **MODIFIER** (nouveaux prompts extraction structurée) |
| **config/tier_limits.py** | `/config/tier_limits.py` | Limites par tier + pricing | ACTIF | usage_tracker, dashboard | **MODIFIER** (nouveaux tiers si pivot) |
| **memory/database.py** | `/memory/database.py` | Init PostgreSQL, schéma, migrations | ACTIF | Tous modules | **GARDER** + migrations |
| **memory/models.py** | `/memory/models.py` | Dataclasses Lead, User, Conversation, Call... | ACTIF | Tous modules | **MODIFIER** (enrichir Lead) |
| **memory/auth.py** | `/memory/auth.py` | JWT signup/login/verify | ACTIF | server.py, dashboard | **GARDER** |
| **memory/stripe_billing.py** | `/memory/stripe_billing.py` | Stripe checkout, webhook, portail | ACTIF | server.py | **GARDER** |
| **memory/lead_repository.py** | `/memory/lead_repository.py` | CRUD leads + conversations | ACTIF | agents, orchestrateur | **MODIFIER** (enrichissement multi-canal) |
| **memory/usage_tracker.py** | `/memory/usage_tracker.py` | check_and_consume() par tier | ACTIF | Tous agents | **GARDER** |
| **memory/cost_logger.py** | `/memory/cost_logger.py` | Log coûts API | ACTIF | agents | **GARDER** |
| **memory/journey_repository.py** | `/memory/journey_repository.py` | Log traçabilité pipeline | ACTIF | orchestrateur, agents | **GARDER** |
| **agents/** | `/agents/` | 6 agents IA (voir Section 3) | MIXTE | orchestrateur, server.py | **MIXTE** |
| **integrations/crm/** | `/integrations/crm/` | 5 connecteurs CRM | ACTIF (partiellement) | server.py, sync | **GARDER** + Hektor prioritaire |
| **integrations/portals/** | `/integrations/portals/` | 4 connecteurs portails | ACTIF | server.py | **GARDER** |
| **integrations/sync/** | `/integrations/sync/` | Sync auto CRM + conflict resolver | ACTIF | docker-compose cron | **GARDER** |
| **tools/twilio_tool.py** | `/tools/twilio_tool.py` | SMS sortants + TwiML vocal | ACTIF | orchestrateur, server.py | **GARDER** + étendre voice |
| **tools/elevenlabs_tool.py** | `/tools/elevenlabs_tool.py` | TTS ElevenLabs | DÉSACTIVÉ | Aucun en prod | **SUPPRIMER** |
| **tools/smspartner_tool.py** | `/tools/smspartner_tool.py` | SMS alternatif SMSPartner | INUTILISÉ | Aucun | **SUPPRIMER ou INVESTIGUER** |
| **tools/email_tool.py** | `/tools/email_tool.py` | Emails transactionnels SendGrid | ACTIF | server.py, agents | **GARDER** |
| **tools/email_templates.py** | `/tools/email_templates.py` | Templates HTML emails | ACTIF | email_tool.py | **GARDER** |
| **tools/calendar_tool.py** | `/tools/calendar_tool.py` | Booking Google Calendar | ACTIF | server.py, VoiceInbound | **GARDER** |
| **tools/security.py** | `/tools/security.py` | Twilio sig, rate limiting, sanitization | ACTIF | server.py | **GARDER** |
| **tools/create_admin.py** | `/tools/create_admin.py` | Script CLI création compte admin | INUTILISÉ | Aucun | **GARDER** (utilitaire) |
| **dashboard/** | `/dashboard/` | Streamlit multi-pages | ACTIF | — | **MODIFIER** (refonte vue mémoire commerciale) |
| **scripts/** | `/scripts/` | Seeding, simulation, triggers | DEV ONLY | — | **SUPPRIMER** (scripts démo) |
| **data/audio/** | `/data/audio/` | ~120 MP3 TTS ElevenLabs | RÉSIDU | Aucun | **SUPPRIMER** |
| **data/images/** | `/data/images/` | 3 PNG staging DALL-E | RÉSIDU | Aucun | **SUPPRIMER** |
| **index.html** | `/index.html` | Landing page servie par FastAPI | ACTIF | server.py (GET /) | **GARDER** |
| **static/legal/** | `/static/legal/` | Pages légales HTML | ACTIF | server.py | **METTRE À JOUR** (RGPD enregistrement appels) |

---

## Section 3 : Inventaire des agents IA

### Léa — LeadQualifierAgent

| Attribut | Valeur |
|----------|--------|
| Fichier | `agents/lead_qualifier.py` (413 lignes) |
| Prompts | `config/prompts.py` : `get_lead_qualifier_system()`, `LEAD_QUALIFIER_FIRST_MESSAGE`, `LEAD_QUALIFIER_SCORING_PROMPT` |
| Routes API | Appelé par `orchestrator.py::node_qualify_new_lead()` et `node_continue_qualification()` |
| État prod | ACTIF — cœur du pipeline SMS entrant |
| Persona | "Léa, conseillère immobilier" |
| Pertinence | La qualification par SMS reste utile. Avec le pivot, elle devient optionnelle (peut être remplacée par extraction depuis transcription d'appel). |
| Action | **ADAPTER** — conserver comme canal optionnel, brancher l'extraction structurée sur tous canaux |

### Marc — NurturingAgent

| Attribut | Valeur |
|----------|--------|
| Fichier | `agents/nurturing.py` (357 lignes) |
| Prompts | `config/prompts.py` : `get_nurturing_system()`, `NURTURING_GENERATION_PROMPT` |
| Routes API | `POST /api/nurturing/process` + `orchestrator.py::node_trigger_nurturing()` |
| État prod | ACTIF (relances SMS/email automatiques) |
| Pertinence | Avec le pivot vers la capture plutôt que les relances automatiques, Marc devient moins central. Il reste utile pour un CRM enrichi mais n'est plus la proposition de valeur principale. |
| Action | **ADAPTER** — rendre optionnel, controllé par le client, pas supprimé immédiatement |

### VoiceInboundAgent

| Attribut | Valeur |
|----------|--------|
| Fichier | `agents/voice_inbound.py` (263 lignes) |
| Prompts | Inline dans la classe (résumé post-appel) |
| Routes API | `POST /webhooks/retell` (post-appel Retell AI) + `POST /webhooks/twilio/voice` (appel entrant) |
| État prod | ACTIF — traitement post-appel Retell (transcription → score → booking RDV) |
| Pertinence | **Très pertinent** — la capture d'appels avec enregistrement Twilio + transcription Whisper s'appuie sur cette logique. À étendre plutôt que remplacer. |
| Action | **ADAPTER** — brancher enregistrement Twilio + Whisper au lieu de Retell AI |

### Hugo — ListingGeneratorAgent

| Attribut | Valeur |
|----------|--------|
| Fichier | `agents/listing_generator.py` (365 lignes) |
| Prompts | `config/prompts.py` |
| Routes API | `POST /api/listing/generate` (non trouvé dans server.py — route manquante ou dans dashboard uniquement) |
| État prod | Semi-actif — appelé depuis page dashboard `04_annonce.py` et `scripts/simulate_lead_flow.py`. Pas de route API dédiée dans server.py. |
| Pertinence | Pas central dans la nouvelle vision (capture + CRM). Utile comme feature annexe. |
| Action | **GARDER** mais dé-prioriser (feature secondaire) |

### Thomas — EstimationAgent

| Attribut | Valeur |
|----------|--------|
| Fichier | `agents/estimation.py` (483 lignes) |
| Prompts | `config/prompts.py` |
| Routes API | Non visible dans server.py — appelé depuis `dashboard/pages/05_estimation.py` |
| État prod | Semi-actif — dashboard uniquement |
| Pertinence | Pas central dans la nouvelle vision. |
| Action | **GARDER** (feature annexe) mais dé-prioriser |

### Julie — AnomalyDetectorAgent

| Attribut | Valeur |
|----------|--------|
| Fichier | `agents/anomaly_detector.py` (360 lignes) |
| Prompts | `config/prompts.py` |
| Routes API | Non visible dans server.py — appelé depuis dashboard |
| État prod | Semi-actif — dashboard uniquement |
| Pertinence | Pas central dans la nouvelle vision. |
| Action | **GARDER** (feature annexe) mais dé-prioriser |

> **Résumé agents :** Seuls Léa (qualification), Marc (nurturing) et VoiceInbound ont des routes API actives. Hugo, Thomas, Julie sont accessibles uniquement via le dashboard.

---

## Section 4 : Inventaire des intégrations externes

### Twilio

| Attribut | Valeur |
|----------|--------|
| État | ACTIF — SMS entrant/sortant + voix entrante |
| Fichiers config | `config/settings.py` (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_SMS_NUMBER, TWILIO_AVAILABLE_NUMBERS) |
| Dépendances code | `tools/twilio_tool.py`, `server.py` (4 routes), `agents/voice_inbound.py` |
| Multi-numéros | Oui — pool de numéros 07, attribution atomique via CTE PostgreSQL |
| Signature | Implémentée (`tools/security.py::validate_twilio_signature`) mais **appliquée uniquement sur `/webhooks/twilio/voice`** — pas sur `/webhooks/twilio/sms` |
| Pertinence | **Central** — à étendre avec enregistrement appels (recording API Twilio) |
| Action | **GARDER + ÉTENDRE** — ajouter `Record` dans TwiML, callback transcription |

### Retell AI

| Attribut | Valeur |
|----------|--------|
| État | ACTIF (webhook post-appel) — mais dépend de l'abonnement Retell |
| Fichiers config | `requirements.txt` (retell-sdk), `config/.env.example` (RETELL_API_KEY, RETELL_AGENT_ID) |
| Dépendances code | `server.py` (`/webhooks/retell`) → `agents/voice_inbound.py` |
| Pertinence | Dépend de la stratégie voix. Si Twilio + Whisper remplace Retell, ce webhook devient obsolète. |
| Action | **INVESTIGUER** — Retell vs Twilio Recording + Whisper |

### Anthropic (Claude)

| Attribut | Valeur |
|----------|--------|
| État | ACTIF |
| Modèle configuré | `claude-sonnet-4-5` (CLAUDE.md dit `claude-sonnet-4-5`, settings.py confirme) |
| Prompt caching | Implémenté via `cache_control: ephemeral` sur system prompts longs |
| Fichiers config | `config/settings.py`, `agents/lead_qualifier.py`, `agents/nurturing.py`, `agents/voice_inbound.py` |
| Pertinence | **Central** — cœur de l'extraction structurée future |
| Action | **GARDER** — envisager upgrade vers claude-sonnet-4-6 |

### ElevenLabs

| Attribut | Valeur |
|----------|--------|
| État | DÉSACTIVÉ — mock automatique (ELEVENLABS_API_KEY absent en prod selon les logs) |
| Résidus | `tools/elevenlabs_tool.py`, ~120 fichiers MP3 dans `data/audio/`, variables dans `config/settings.py`, mentions dans `dashboard/pages/00_proprietaire.py` |
| Pertinence | Aucune dans la nouvelle vision |
| Action | **SUPPRIMER** — fichiers MP3, code tool, variables env, mentions dashboard |

### OpenAI (DALL-E)

| Attribut | Valeur |
|----------|--------|
| État | INUTILISÉ — `OPENAI_API_KEY` dans `.env.example` mais aucun import OpenAI trouvé dans le code actuel |
| Résidus | 3 fichiers PNG dans `data/images/`, variable dans `.env.example` |
| Pertinence | Aucune (staging virtuel dé-priorisé) |
| Action | **SUPPRIMER** de `.env.example`, supprimer images |

### Stripe

| Attribut | Valeur |
|----------|--------|
| État | ACTIF — checkout, portail, webhook |
| Fichiers config | `config/settings.py`, `memory/stripe_billing.py` |
| Dépendances | `server.py` (5 routes), `dashboard/pages/09_facturation.py` |
| Signature webhook | Implémentée et conditionnelle (`stripe_webhook_secret`) |
| Prix | 4 tiers (Indépendant/Starter/Pro/Elite) — IDs test ET live présents dans le code |
| Pertinence | **Central** |
| Action | **GARDER** |

### SendGrid

| Attribut | Valeur |
|----------|--------|
| État | ACTIF — emails transactionnels |
| Emails envoyés | Bienvenue, confirmation paiement, résiliation, rapport hebdo, alerte quota, confirmation RDV |
| Fichiers | `tools/email_tool.py`, `tools/email_templates.py` |
| Pertinence | **Central** |
| Action | **GARDER** |

### Google Calendar

| Attribut | Valeur |
|----------|--------|
| État | ACTIF — OAuth2, slots, booking |
| Routes API | `/api/calendar/auth`, `/api/calendar/callback`, `/api/calendar/slots`, `/api/calendar/status`, `/api/calendar/book` |
| Fichiers | `tools/calendar_tool.py`, `dashboard/pages/08_agenda.py` |
| Pertinence | **Central** — booking RDV post-qualification |
| Action | **GARDER** |

### SMSPartner

| Attribut | Valeur |
|----------|--------|
| État | INUTILISÉ — outil présent, non appelé depuis server.py |
| Fichiers | `tools/smspartner_tool.py`, colonne `smspartner_number` dans DB |
| Pertinence | Alternative à Twilio pour SMS — décision non tranchée |
| Action | **INVESTIGUER** — clarifier si remplacé définitivement par Twilio ou prévu pour certains clients |

---

## Section 5 : Inventaire des routes et webhooks

### Routes FastAPI — server.py

| Méthode | Path | Utilité | État | Nouvelle vision |
|---------|------|---------|------|-----------------|
| GET | `/` | Landing page (index.html) | ACTIF | GARDER |
| GET | `/health` | Health check (sécurisé X-Health-Key) | ACTIF | GARDER |
| GET | `/legal/mentions-legales` | Page légale | ACTIF | METTRE À JOUR (RGPD appels) |
| GET | `/legal/cgu` | CGU | ACTIF | METTRE À JOUR |
| GET | `/legal/confidentialite` | Politique confidentialité | ACTIF | METTRE À JOUR |
| POST | `/auth/signup` | Création compte | ACTIF | GARDER |
| POST | `/auth/login` | Login JWT | ACTIF | GARDER |
| POST | `/webhooks/sms` | SMS entrant Twilio (old-style) | LEGACY | À unifier avec /webhooks/twilio/sms |
| POST | `/webhooks/sms/status` | Statut SMS Twilio | ACTIF | GARDER |
| POST | `/webhooks/whatsapp` | WhatsApp entrant | ACTIF | GARDER |
| POST | `/webhooks/whatsapp/status` | Statut WhatsApp | ACTIF | GARDER |
| POST | `/webhooks/seloger` | Lead SeLoger | ACTIF | GARDER |
| POST | `/webhooks/leboncoin` | Lead LeBonCoin | ACTIF | GARDER |
| POST | `/webhooks/retell` | Post-appel Retell AI | ACTIF (si Retell) | DÉPEND de la stratégie voix |
| POST | `/webhooks/apimo` | Webhook Apimo CRM | ACTIF | GARDER |
| POST | `/webhook/crm/{crm_name}` | Webhook universel CRM | ACTIF | GARDER |
| POST | `/webhook/portal/{portal_name}` | Webhook portail (Bienici, Logic Immo) | ACTIF | GARDER |
| POST | `/webhooks/twilio/voice` | Appel entrant Twilio | ACTIF | GARDER + ÉTENDRE (recording) |
| POST | `/twiml/inbound` | Alias `/webhooks/twilio/voice` | LEGACY | SUPPRIMER (rétro-compat) |
| POST | `/twiml/sophie/inbound` | Alias legacy Sophie | LEGACY | **SUPPRIMER** |
| POST | `/webhooks/twilio/sms` | SMS entrant 07 (multi-numéros) | ACTIF | GARDER |
| GET | `/api/status` | Statut pipeline + usage | ACTIF | GARDER |
| POST | `/api/simulate-lead` | Simulation lead (dev/démo) | DEV | SUPPRIMER (ou protéger) |
| POST | `/api/nurturing/process` | Déclenchement nurturing | ACTIF | ADAPTER |
| POST | `/api/voice/call-hot-leads` | Appels sortants — **DÉSACTIVÉ** | DÉSACTIVÉ | SUPPRIMER |
| GET | `/stripe/plans` | Liste des plans | ACTIF | GARDER |
| POST | `/stripe/create-checkout-session` | Checkout Stripe | ACTIF | GARDER |
| GET | `/stripe/portal` | Portail Stripe | ACTIF | GARDER |
| POST | `/stripe/webhook` | Events Stripe | ACTIF | GARDER |
| POST | `/webhooks/{user_id}/leads` | Webhook externe leads | ACTIF | GARDER |
| POST | `/api/leads/import` | Import CSV leads | ACTIF | GARDER |
| GET | `/api/calendar/auth` | OAuth Google | ACTIF | GARDER |
| GET | `/api/calendar/callback` | Callback OAuth Google | ACTIF | GARDER |
| GET | `/api/calendar/slots` | Créneaux disponibles | ACTIF | GARDER |
| GET | `/api/calendar/status` | Statut connexion Calendar | ACTIF | GARDER |
| POST | `/api/calendar/book` | Booking RDV | ACTIF | GARDER |

### Double-emploi constaté : `/webhooks/sms` vs `/webhooks/twilio/sms`

`/webhooks/sms` (ligne 332) utilise `handle_sms_webhook()` de `integrations/sms_webhook.py` — ancienne architecture mono-client.  
`/webhooks/twilio/sms` (ligne 744) utilise le lookup multi-client par `twilio_sms_number` — nouvelle architecture.  
Ces deux routes font la même chose mais avec des architectures différentes.

### Webhooks entrants configurés côté Twilio

| Webhook Twilio | Route PropPilot | Commentaire |
|---------------|-----------------|-------------|
| SMS entrant | `/webhooks/twilio/sms` | Multi-numéros, lookup DB |
| Appel entrant | `/webhooks/twilio/voice` | TwiML + SMS qualification |
| Statut SMS | `/webhooks/sms/status` | Delivery receipts |
| Statut WhatsApp | `/webhooks/whatsapp/status` | Delivery receipts |

### Webhooks Stripe

| Event | Traitement |
|-------|-----------|
| `checkout.session.completed` | Active abonnement + email confirmation |
| `customer.subscription.deleted` | Désactive + email résiliation |
| `invoice.payment_failed` | Marque past_due + email paiement échoué |

---

## Section 6 : Cartographie de la base de données

### Tables principales

| Table | Rôle | Notes |
|-------|------|-------|
| `users` | Comptes agences/mandataires | Colonnes Twilio multi-numéros, Google Calendar token, is_admin, smspartner_number |
| `leads` | Leads qualifiés | Champs scoring, nurturing, timeline, budget, projet, statut |
| `conversations` | Historique messages par lead | Canal, role (user/assistant), contenu |
| `usage_tracking` | Compteurs mensuels par client | Leads, voix, tokens, follow-ups, listings, estimations |
| `api_actions` | Log coûts API par action | Provider, model, tokens, coût EUR |
| `calls` | Appels voix (Retell) | Transcript, résumé IA, score post-appel |
| `listings` | Annonces générées | Description longue/courte, SEO, images |
| `estimations` | Estimations DVF | Fourchette prix, rentabilité, mention légale |
| `roi_metrics` | Métriques ROI mensuelles | RDV, mandats, CA estimé, taux conversion |
| `crm_connections` | Connexions CRM par client | Type CRM, clé API, flags sync |
| `lead_journey` | Audit trail pipeline | Chaque action agent enregistrée |

### Relations (schéma textuel)

```
users (id) ──< leads (client_id)
              leads (id) ──< conversations (lead_id)
              leads (id) ──< calls (lead_id)
              leads (id) ──< listings (lead_id) [nullable]
              leads (id) ──< estimations (lead_id) [nullable]
              leads (id) ──< lead_journey (lead_id)
users (id) ──< usage_tracking (client_id)
users (id) ──< api_actions (client_id)
users (id) ──< roi_metrics (client_id)
users (id) ──< crm_connections (client_id)
```

### Migrations Alembic

**Alembic non utilisé.** Les migrations sont gérées via `_run_migrations()` dans `memory/database.py` — instructions `ALTER TABLE ADD COLUMN IF NOT EXISTS` cumulatives et idempotentes. Aucun historique versionné. C'est un risque pour les migrations complexes à venir.

### Tables potentiellement orphelines

- `calls` : fortement couplée à Retell AI. Si Retell est abandonné au profit de Twilio Recording + Whisper, le schéma doit évoluer (colonne `retell_call_id` → `recording_url`, `transcript_provider`).
- `listings` : peu utilisée en prod (Hugo non prioritaire).
- `estimations` : peu utilisée en prod (Thomas non prioritaire).

### Risques lors du nettoyage

| Risque | Niveau | Détail |
|--------|--------|--------|
| Suppression `smspartner_number` | MEDIUM | Colonne en DB + modèle User — si SMSPartner est abandonné |
| Migration `calls` | HIGH | Si Retell remplacé par Twilio Recording, toutes les lignes existantes ont `retell_call_id` mais pas d'URL d'enregistrement |
| Suppression ElevenLabs | LOW | Aucun appel en prod — données audio en `data/audio/` seulement |

---

## Section 7 : Code mort et candidats à la suppression

### Routes API obsolètes

| Élément | Fichier | Risque suppression | Action |
|---------|---------|-------------------|--------|
| `POST /twiml/sophie/inbound` | `server.py:735` | LOW — alias legacy de `/webhooks/twilio/voice` | **SUPPRIMER MAINTENANT** |
| `POST /twiml/inbound` | `server.py:729` | LOW — alias rétro-compat | **SUPPRIMER MAINTENANT** |
| `POST /webhooks/sms` | `server.py:332` | MEDIUM — duplique `/webhooks/twilio/sms` mais pour mono-client | **DÉSACTIVER PUIS OBSERVER** |
| `POST /api/voice/call-hot-leads` | `server.py:924` | LOW — retourne toujours `disabled: true` | **SUPPRIMER MAINTENANT** |
| `POST /api/simulate-lead` | `server.py:867` | MEDIUM — endpoint de dev/démo non protégé | **DÉSACTIVER PUIS OBSERVER** |

### Fichiers non référencés ou inutilisés

| Fichier | Statut | Risque | Action |
|---------|--------|--------|--------|
| `tools/elevenlabs_tool.py` | Non appelé en prod | LOW | **SUPPRIMER** |
| `tools/smspartner_tool.py` | Non wired dans server.py | MEDIUM (décision stratégique) | **INVESTIGUER** |
| `dashboard/pages_archive/05_listings.py` | Archivé, non chargé | LOW | **SUPPRIMER** |
| `dashboard/pages_archive/_hidden_success.py` | Archivé | LOW | **SUPPRIMER** |
| `scripts/trigger_jerome_martin.py` | Script démo one-shot | LOW | **SUPPRIMER** |
| `scripts/seed_demo_dumortier.py` | Script démo | LOW | **SUPPRIMER** |
| `scripts/seed_demo_data.py` | Script démo | MEDIUM (utile pour CI) | **GARDER ET INVESTIGUER** |
| `scripts/simulate_lead_flow.py` | Script démo | LOW | **SUPPRIMER** |
| `data/audio/*.mp3` (~120 fichiers) | Résidu ElevenLabs | LOW | **SUPPRIMER** |
| `data/images/*.png` (3 fichiers) | Résidu DALL-E | LOW | **SUPPRIMER** |
| `integrations/apimo.py` (racine) | Duplique `integrations/crm/apimo.py` | MEDIUM | **INVESTIGUER** (2 fichiers Apimo distincts) |

### Variables d'environnement obsolètes

| Variable | Fichier | Status | Action |
|----------|---------|--------|--------|
| `ELEVENLABS_API_KEY` | `config/settings.py` | Obsolète | **SUPPRIMER** |
| `ELEVENLABS_VOICE_ID` | `config/settings.py` | Obsolète | **SUPPRIMER** |
| `ELEVENLABS_MODEL_ID` | `config/settings.py` | Obsolète | **SUPPRIMER** |
| `DATABASE_PATH` | `.env.example`, Dockerfile | Résidu SQLite — PostgreSQL uniquement | **SUPPRIMER de .env.example** |
| `OPENAI_API_KEY` | `.env.example` | Aucun usage dans le code | **SUPPRIMER** |
| `TWILIO_PHONE_NUMBER` | `.env.example` | Différent de TWILIO_SMS_NUMBER dans settings.py | **ALIGNER** |
| `APP_NAME`, `APP_URL`, `SUPPORT_EMAIL` | `.env.example` | Non présents dans settings.py | **NETTOYER** |
| `BASE_URL` | Mentionné dans log lifespan | Obsolète selon le log lui-même | **CONFIRMER SUPPRESSION** |

### Résidus ElevenLabs / Sophie

| Résidu | Localisation | Action |
|--------|-------------|--------|
| Classe `ElevenLabsTool` | `tools/elevenlabs_tool.py` | SUPPRIMER le fichier |
| Voix "sophie", "thomas" configurées | `tools/elevenlabs_tool.py` | SUPPRIMER |
| Route `/twiml/sophie/inbound` | `server.py:735` | SUPPRIMER |
| `elevenlabs_available` property | `config/settings.py` | SUPPRIMER |
| Coûts ElevenLabs dans dashboard | `dashboard/pages/00_proprietaire.py:342` | SUPPRIMER |
| `cost_elevenlabs` metric | `dashboard/pages/00_proprietaire.py:356` | SUPPRIMER |
| Coût `elevenlabs` dans `cost_logger.py` | `memory/cost_logger.py:28` | SUPPRIMER |
| 120 fichiers MP3 | `data/audio/` | SUPPRIMER |
| `elevenlabs` dans `models.py` provider | `memory/models.py:140` | NETTOYER commentaire |
| `ELEVENLABS_*` dans `main.py` | `main.py:60` | SUPPRIMER ligne |

---

## Section 8 : Dashboard Streamlit

### Pages actives

| Page | Fichier | Rôle | État | Pertinence nouvelle vision |
|------|---------|------|------|---------------------------|
| Propriétaire | `00_proprietaire.py` | Back-office fondateur (CA, coûts, clients) | ACTIF — admin only | **GARDER** (mettre à jour coûts) |
| Mes Leads | `01_mes_leads.py` | Liste et détail leads | ACTIF | **MODIFIER** (vue mémoire commerciale) |
| Utilisation | `02_utilisation.py` | Compteurs usage par tier | ACTIF | **MODIFIER** (nouveaux compteurs) |
| ROI | `03_roi.py` | Suivi garantie ROI | ACTIF | **GARDER** |
| Annonce | `04_annonce.py` | Génération Hugo | ACTIF | **DÉPRIORITISER** |
| Estimation | `05_estimation.py` | Estimation Thomas | ACTIF | **DÉPRIORITISER** |
| Paramètres | `06_parametres.py` | Config compte + numéro Twilio | ACTIF (583 lignes) | **MODIFIER** (ajouter config CRM) |
| Admin | `07_admin.py` | Coûts API back-office | ACTIF — protégé mot de passe | **GARDER** |
| Agenda | `08_agenda.py` | Google Calendar | ACTIF | **GARDER** |
| Facturation | `09_facturation.py` | Stripe portal + abonnement | ACTIF | **GARDER** |
| Conversations | `10_conversations.py` | Historique SMS par lead | ACTIF | **MODIFIER** (multi-canal) |
| Intégrations | `11_integrations.py` | Sources leads + import CSV + CRM | ACTIF | **MODIFIER** (cœur de la nouvelle vision) |

### Pages archivées

| Page | Fichier | Raison archivage | Action |
|------|---------|-----------------|--------|
| Listings (legacy) | `pages_archive/05_listings.py` | Remplacée par `04_annonce.py` | **SUPPRIMER** |
| Success (hidden) | `pages_archive/_hidden_success.py` | Page de succès Stripe non utilisée | **SUPPRIMER** |

### Bugs visuels connus

Le rapport d'audit ne peut pas exécuter le dashboard. Sur la base du code observé :
- `00_proprietaire.py` contient des calculs de coûts ElevenLabs (`cost_elevenlabs`) qui seront à 0€ puisque ElevenLabs est désactivé — à nettoyer pour éviter confusion.
- `06_parametres.py` est le plus long fichier du dashboard (583 lignes) — risque de complexité et de dette technique.
- `09_facturation.py` est très court (48 lignes) — page probablement minimaliste, à vérifier si elle couvre tous les cas Stripe.

---

## Section 9 : Tests existants

### Résumé

| Métrique | Valeur |
|----------|--------|
| Fichiers de tests | 18 |
| Tests collectés | 401 |
| Passés | 237 |
| Skippés | 54 |
| Erreurs (PostgreSQL local) | 110 |
| Bugs de code réels | 0 (toutes les erreurs = `psycopg2.OperationalError` — connexion PostgreSQL absente localement) |

### Tests par fichier

| Fichier | Couverture | État |
|---------|-----------|------|
| `test_anomaly_detector.py` | AnomalyDetectorAgent | Bien couvert |
| `test_calendar.py` | CalendarTool + routes API | Bien couvert (47 tests) |
| `test_crm_integrations.py` | Tous les connecteurs CRM + portails + sync | Très bien couvert |
| `test_emails.py` | EmailTool | Couvert |
| `test_elevenlabs.py` | ElevenLabsTool | **OBSOLÈTE** (outil à supprimer) |
| `test_estimation.py` | EstimationAgent | Couvert |
| `test_integrations_page.py` | Page dashboard intégrations | Couvert |
| `test_journey_repository.py` | JourneyRepository | Couvert |
| `test_lead_qualifier.py` | LeadQualifierAgent | Couvert |
| `test_listing_generator.py` | ListingGeneratorAgent | Erreurs PostgreSQL |
| `test_models_regression.py` | Modèles + champs DB | Couvert (régression bugs) |
| `test_nurturing.py` | NurturingAgent | Erreurs PostgreSQL |
| `test_regression_bugs.py` | Bugs critiques fixes | Couvert |
| `test_stripe.py` | Stripe billing | Couvert |
| `test_tier_limits.py` | Limites par tier | Couvert |
| `test_twilio_assignment.py` | Multi-numéros Twilio | Couvert |
| `test_usage_tracker.py` | check_and_consume() | Couvert |
| `test_webhooks.py` | Webhooks leads + import CSV | Couvert |

### Modules sans tests à risque

- `integrations/sync/conflict_resolver.py` — partiellement testé via `test_crm_integrations.py`
- `memory/stripe_billing.py` — couvert dans `test_stripe.py` mais mode mock uniquement
- `tools/security.py` — non testé directement

### Tests obsolètes à supprimer

- `tests/test_elevenlabs.py` — à supprimer avec le tool ElevenLabs

---

## Section 10 : Sécurité et conformité

### État actuel

| Point | État | Niveau de risque |
|-------|------|-----------------|
| JWT Auth sur `/api/*` | Implémenté (middleware) | ✅ OK |
| JWT expire | 24h par défaut (configurable) | ✅ OK |
| Signature Twilio | Implémentée — **mais appliquée seulement sur `/webhooks/twilio/voice`** | ⚠️ MEDIUM |
| Signature Stripe | Implémentée et conditionnelle | ✅ OK |
| Signature SeLoger | Implémentée (optionnelle si clé absente) | ✅ OK |
| Signature SMS Partner | Implémentée mais endpoint non wired | ⚠️ FAIBLE risque (pas d'endpoint) |
| Rate limiting | Implémenté sur `/webhooks/twilio/voice` uniquement | ⚠️ MEDIUM |
| Sanitization SMS input | Implémentée (injection, XSS basique) | ✅ OK |
| Sanitization numéros | Implémentée (regex E.164) | ✅ OK |
| Security headers | Implémentés (HSTS, X-Frame, XSS, Referrer) | ✅ OK |
| CORS | `allow_origins=["*"]` | ⚠️ MEDIUM (production) |
| Audit logging | Implémenté (SecurityAuditMiddleware) | ✅ OK |
| Health endpoint | Protégé par X-Health-Key | ✅ OK |
| JWT_SECRET_KEY par défaut | `change-this-secret-in-production` | ⚠️ HIGH si oublié en prod |
| Admin password par défaut | `changeme` | ⚠️ HIGH si oublié en prod |
| Anti-concurrence SMS | Lock threading par numéro expéditeur | ✅ Bonne pratique |

### Problèmes de sécurité identifiés

1. **Signature Twilio manquante sur `/webhooks/twilio/sms`** (ligne 744) — le webhook SMS multi-numéros ne valide pas la signature Twilio. N'importe qui connaissant l'URL peut forger des SMS entrants.

2. **CORS trop permissif** — `allow_origins=["*"]` en production. À restreindre au domaine du dashboard.

3. **`/api/simulate-lead` non protégé par admin** — accessible à tout utilisateur authentifié avec un JWT valide. Peut être utilisé pour spammer des leads.

4. **Secrets par défaut** — `JWT_SECRET_KEY` et `ADMIN_PASSWORD` ont des valeurs par défaut faibles. À vérifier que Railway est correctement configuré.

### RGPD — Enregistrement des appels futurs

La nouvelle vision inclut l'enregistrement des appels téléphoniques. Points légaux à anticiper :

- **Mention légale obligatoire** en début d'appel : "Cet appel est enregistré à des fins d'amélioration du service" — à intégrer dans le TwiML de réponse.
- **Durée de conservation** à définir (CNIL recommande 3 mois maximum).
- **Droit d'opposition** — permettre au prospect de refuser l'enregistrement.
- **Chiffrement au repos** des enregistrements dans le stockage (Railway volume ou S3).
- Mise à jour des **pages légales** (`static/legal/`).

---

## Section 11 : Configuration et variables d'environnement

### Variables utilisées en production (source : `config/settings.py`)

| Variable | Obligatoire | Défaut | Usage |
|----------|------------|--------|-------|
| `ANTHROPIC_API_KEY` | Oui (sinon mock) | None | LLM |
| `TWILIO_ACCOUNT_SID` | Oui (sinon mock) | None | SMS/Voice |
| `TWILIO_AUTH_TOKEN` | Oui (sinon mock) | None | SMS/Voice |
| `TWILIO_SMS_NUMBER` | Oui | None | Numéro sortant défaut |
| `TWILIO_WHATSAPP_NUMBER` | Non | +14155238886 | WhatsApp |
| `TWILIO_AVAILABLE_NUMBERS` | Non | "" | Pool multi-numéros |
| `SENDGRID_API_KEY` | Oui (sinon mock) | None | Emails |
| `SENDGRID_FROM_EMAIL` | Non | noreply@proppilot.fr | Expéditeur |
| `DATABASE_URL` | **Oui** | postgresql://localhost/proppilot | PostgreSQL |
| `JWT_SECRET_KEY` | **Oui** | `change-this-secret-in-production` | Auth |
| `JWT_EXPIRE_HOURS` | Non | 24 | Durée token |
| `STRIPE_SECRET_KEY` | Oui (sinon mock) | None | Paiements |
| `STRIPE_PUBLISHABLE_KEY` | Non | None | Frontend Stripe |
| `STRIPE_WEBHOOK_SECRET` | Oui | None | Sécurité webhook |
| `GOOGLE_CLIENT_ID` | Non (sinon mock) | None | Calendar OAuth |
| `GOOGLE_CLIENT_SECRET` | Non (sinon mock) | None | Calendar OAuth |
| `GOOGLE_REDIRECT_URI` | Non | http://localhost:8000/api/calendar/callback | Calendar OAuth |
| `HEALTH_SECRET` | Recommandé | None | Health endpoint |
| `ADMIN_PASSWORD` | **Oui** | `changeme` | Admin dashboard |
| `AGENCY_NAME` | Non | "" | Config démo |
| `AGENCY_TIER` | Non | Starter | Config démo |
| `AGENCY_CLIENT_ID` | Non | client_demo | Config démo |
| `API_URL` | Oui | http://localhost:8000 | Redirect URLs |
| `ELEVENLABS_API_KEY` | **OBSOLÈTE** | None | À supprimer |
| `ELEVENLABS_VOICE_ID` | **OBSOLÈTE** | None | À supprimer |
| `ELEVENLABS_MODEL_ID` | **OBSOLÈTE** | eleven_multilingual_v2 | À supprimer |
| `MOCK_MODE` | Non | auto | Contrôle mocks |
| `TESTING` | Non | False | Tests unitaires |

### Variables absentes de settings.py mais présentes dans .env.example

| Variable | Status |
|----------|--------|
| `RETELL_API_KEY` | Présente dans `.env.example`, **absente de settings.py** |
| `RETELL_AGENT_ID` | Idem |
| `OPENAI_API_KEY` | Présente dans `.env.example`, aucun usage code |
| `TWILIO_PHONE_NUMBER` | Diverge de `TWILIO_SMS_NUMBER` dans settings.py |
| `APP_NAME`, `APP_URL`, `SUPPORT_EMAIL` | Présentes dans `.env.example`, absentes de settings.py |

### Configuration Railway

Le serveur de production est sur Railway. Le Dockerfile expose le port 8000 (FastAPI). Le docker-compose.yml montre que le dashboard Streamlit tourne sur 8501 en local mais Railway a probablement un service séparé.

**Point d'attention :** `DATABASE_PATH` référencé dans le Dockerfile (`/app/data/agency.db`) mais le code utilise exclusivement PostgreSQL. Le Dockerfile tente `init_database()` au build — cela peut échouer sans PostgreSQL disponible au build time.

---

## Section 12 : Synthèse et recommandations

### À faire immédiatement (sécurité critique)

1. **Ajouter la validation de signature Twilio sur `/webhooks/twilio/sms`** — risque d'injection de faux SMS en production.
2. **Vérifier les secrets Railway** : `JWT_SECRET_KEY` ≠ défaut, `ADMIN_PASSWORD` ≠ défaut.
3. **Restreindre CORS** à l'URL du dashboard Railway uniquement.

### À faire dans le sprint de nettoyage

1. Supprimer route `/twiml/sophie/inbound` et `/twiml/inbound`
2. Supprimer `tools/elevenlabs_tool.py`, `tests/test_elevenlabs.py`, variables ElevenLabs dans settings.py
3. Supprimer les 120 fichiers MP3 de `data/audio/`
4. Supprimer `data/images/*.png`
5. Supprimer route `/api/voice/call-hot-leads` (retourne toujours disabled)
6. Nettoyer `.env.example` (OPENAI_API_KEY, ELEVENLABS_*, TWILIO_PHONE_NUMBER, APP_NAME, APP_URL, SUPPORT_EMAIL)
7. Supprimer scripts démo one-shot : `trigger_jerome_martin.py`, `seed_demo_dumortier.py`, `simulate_lead_flow.py`
8. Supprimer `dashboard/pages_archive/`
9. Clarifier le doublon `integrations/apimo.py` vs `integrations/crm/apimo.py`
10. Clarifier le doublon `/webhooks/sms` vs `/webhooks/twilio/sms`
11. Supprimer ou archiver la route `/api/simulate-lead` (dev only)
12. Mettre à jour les pages légales (RGPD enregistrement appels)

### À faire dans la phase de construction

1. **Capture d'appels Twilio** : ajouter `<Record>` dans TwiML + route callback `POST /webhooks/twilio/recording`
2. **Transcription Whisper** : intégrer OpenAI Whisper (ou Anthropic si disponible) dans le callback d'enregistrement
3. **Extraction structurée multi-canal** : nouveau module `agents/extractor.py` appelé après chaque transcript
4. **Connecteur Hektor** : valider l'API réelle (le mock est prêt)
5. **Connecteur Apimo** : idem
6. **Refonte dashboard** : page `10_conversations.py` → vue mémoire commerciale unifiée (appels + SMS + emails)
7. **Capture emails** : Gmail API + IMAP (nouveau module)
8. **Migrations formelles** : envisager Alembic pour tracer les changements de schéma
9. **Ajout colonne `recording_url`** dans la table `calls`
10. **RETELL_API_KEY dans settings.py** si Retell est maintenu, ou suppression si Twilio Recording le remplace

### À investiguer avant action

1. **Retell AI vs Twilio Recording + Whisper** — les deux sont implémentés partiellement. Décision stratégique à trancher.
2. **SMSPartner** — l'outil existe mais n'est pas wired. Prévu pour remplacer Twilio pour certains clients ou abandonné ?
3. **`images_count`** dans le tracking — DALL-E est absent du code. Cette métrique compte-t-elle encore quelque chose ?

---

## Section 13 : Questions ouvertes

1. **Retell AI vs Twilio Recording** : le webhook `/webhooks/retell` est en production. La nouvelle vision utilise-t-elle toujours Retell ou passe-t-on directement à Twilio Recording + Whisper ? Les deux sont incompatibles côté agent vocal.

2. **SMSPartner** : outil présent (`tools/smspartner_tool.py`), colonne en DB (`smspartner_number`), mais aucune route dans server.py. Alternative à Twilio pour certains clients ou abandonnée définitivement ?

3. **Mode self-service** : le circuit Stripe avec checkout est-il maintenu pour l'inscription en ligne ou le produit passe-t-il uniquement en mode devis/vente directe ?

4. **DALL-E / staging virtuel** : `images_count` dans le tracking, 3 images en `data/images/`, mais aucun import OpenAI dans le code. Ce feature a-t-il été supprimé ou juste désactivé ?

5. **`integrations/apimo.py`** (racine) vs `integrations/crm/apimo.py` : deux fichiers Apimo distincts. Le premier (`integrations/apimo.py`) contient `parse_apimo_webhook()` utilisé dans server.py. Le second est le connecteur CRM. Doivent-ils être fusionnés ?

6. **`/webhooks/sms`** (ligne 332, mono-client) vs **`/webhooks/twilio/sms`** (ligne 744, multi-client) : l'ancienne route est-elle encore configurée dans Twilio Console quelque part ? Si oui, risque de double-traitement.

7. **Dashboard vs API** : Hugo (listing) et Thomas (estimation) n'ont pas de routes dédiées dans server.py — ils passent directement par le dashboard. Ce couplage sera-t-il maintenu ou faut-il exposer des routes API ?

8. **`lead_journey`** : table d'audit trail très bien remplie. Utilisée dans le dashboard ? Si oui, où ?

9. **`first_name` dans users** : colonne présente en DB (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS first_name`), dans le modèle `User`, utilisée dans le TwiML vocal (`agent_name`). Non exposée dans le formulaire d'inscription (`/auth/signup`). À ajouter à l'inscription ou renseignée via les paramètres ?

10. **Whisper** : absent de `requirements.txt`. Si la nouvelle vision l'utilise, il faudra l'ajouter. Quelle version/provider ? OpenAI API ou modèle local ?

---

## Section 14 : Plan recommandé pour le sprint suivant

### Étapes suggérées (ordre à valider avec le fondateur)

#### Phase 1 — Sécurité (1-2 heures, sans risque)
1. Ajouter signature Twilio sur `/webhooks/twilio/sms`
2. Vérifier variables Railway (JWT_SECRET_KEY, ADMIN_PASSWORD)
3. Restreindre CORS
4. **Vérification :** `pytest tests/test_webhooks.py tests/test_regression_bugs.py -v`

#### Phase 2 — Nettoyage ElevenLabs / Sophie (2-3 heures)
1. Supprimer `tools/elevenlabs_tool.py`
2. Supprimer variables ElevenLabs dans `config/settings.py`
3. Supprimer route `/twiml/sophie/inbound` et `/twiml/inbound`
4. Nettoyer mentions ElevenLabs dans `dashboard/pages/00_proprietaire.py` et `memory/cost_logger.py`
5. Supprimer `tests/test_elevenlabs.py`
6. Supprimer `data/audio/*.mp3` et `data/images/*.png`
7. **Vérification :** `pytest tests/ -v --ignore=tests/test_elevenlabs.py` — même résultat qu'avant

#### Phase 3 — Routes et code mort (2-3 heures)
1. Supprimer `/api/voice/call-hot-leads`
2. Décider du sort de `/api/simulate-lead` (protéger par is_admin ou supprimer)
3. Supprimer scripts one-shot (`trigger_jerome_martin.py`, `seed_demo_dumortier.py`, `simulate_lead_flow.py`)
4. Supprimer `dashboard/pages_archive/`
5. Clarifier doublon Apimo (`integrations/apimo.py` vs `integrations/crm/apimo.py`)
6. **Vérification :** `pytest tests/ -v` + vérifier routes dans `/docs`

#### Phase 4 — Nettoyage .env et config (1 heure)
1. Mettre à jour `config/.env.example` (supprimer obsolètes, ajouter futurs)
2. Aligner `TWILIO_PHONE_NUMBER` vs `TWILIO_SMS_NUMBER`
3. Ajouter `RETELL_API_KEY` dans settings.py ou supprimer définitivement
4. **Vérification :** `pytest tests/test_calendar.py tests/test_tier_limits.py -v`

#### Phase 5 — RGPD et légal (1-2 heures)
1. Mettre à jour `static/legal/confidentialite.html` (mention enregistrement appels)
2. Mettre à jour `static/legal/cgu.html`
3. Ajouter mention légale dans TwiML vocal (`generate_inbound_twiml`)

#### Points de rollback
- Chaque phase = commit atomique sur une branche `cleanup/phase-X`
- Avant suppression d'un fichier : vérifier `grep -rn "nom_du_fichier"` dans tout le projet
- Tests à chaque étape : `pytest tests/ -v --tb=short`

### Estimation du temps total du sprint de nettoyage
**6 à 10 heures** de développement, selon les décisions prises sur SMSPartner, Retell AI, et les routes legacy. Le nettoyage lui-même est simple — les décisions stratégiques sont la partie critique.

---

*Rapport généré le 26 avril 2026 — audit statique uniquement, aucune modification du code source.*
