# PropPilot — Legacy Salvage

Code et logique préservés lors du sprint de nettoyage (2026-04-26).  
Ce document trace ce qui a été extrait, où ça vit maintenant, et ce qui est en mode dormant.

---

## 1. Extrait de Léa — Système de scoring leads

### Où ça vit maintenant
`lib/lead_extraction/` — module dédié, réutilisable par le futur pipeline de transcription.
- `lib/lead_extraction/schema.py` — `LeadExtractionResult`, constantes, `score_to_action()`
- `lib/lead_extraction/prompts.py` — `EXTRACTION_PROMPT` (adapté pour texte libre)
- `lib/lead_extraction/scoring.py` — `extract_lead_info()`, `apply_extraction_to_lead()`
- `lib/sms_storage.py` — `store_incoming_sms()` utilisé par le webhook `/webhooks/twilio/sms`

### Pourquoi c'est précieux
Le système de scoring 1-10 (urgence/budget/motivation) et le schéma de données structurées
(projet, budget, zone, timing, financement, motivation) seront réutilisés pour extraire
automatiquement des informations depuis les transcriptions d'appels (sprint suivant).

### Ce qui a été extrait

#### `lib/lead_extraction/schema.py`
Schéma de données structurées d'un lead qualifié :
- `LeadExtractionResult` : dataclass avec tous les champs extraits
- `ScoringResult` : score total + sous-scores (urgence, budget, motivation)
- Constantes : `SCORE_SEUIL_RDV=7`, `SCORE_SEUIL_NURTURING_COURT=4`
- Routing logic : `score_to_action(score)` → `rdv|nurturing_14j|nurturing_30j`

#### `lib/lead_extraction/prompts.py`
Prompts d'extraction adaptés pour fonctionner sur du texte libre (transcription ou conversation) :
- `EXTRACTION_PROMPT` — adapté de `LEAD_QUALIFIER_SCORING_PROMPT`
- Le prompt accepte maintenant du texte non structuré (pas seulement des échanges Q/A)
- Compatible avec les transcriptions d'appels Whisper

#### `lib/lead_extraction/scoring.py`
Fonctions réutilisables :
- `extract_lead_info(text, client)` — appelle Claude pour extraire + scorer
- `compute_score_from_fields(urgence, budget, motivation)` — calcul pur sans LLM
- `apply_score_and_route(lead, scoring_result)` — met à jour un objet Lead

### Source originale
- `agents/lead_qualifier.py` méthodes `_compute_score()` et `_apply_score_and_route()`
- `config/prompts.py` constantes `LEAD_QUALIFIER_SCORING_PROMPT`, `LEAD_QUALIFIER_SYSTEM` (section scoring)

### Usage futur (sprint Capture Appels)
```python
from lib.lead_extraction.scoring import extract_lead_info

# Après transcription Whisper d'un appel :
transcription = "Bonjour, je cherche un appartement 3 pièces à Lyon..."
result = extract_lead_info(transcription, anthropic_client)
# → result.score_total, result.projet, result.budget, result.prochaine_action
```

---

## 2. Prompts de qualification conservés dans config/prompts.py

Les prompts suivants sont **conservés** dans `config/prompts.py` même si Léa est supprimée,
car ils seront réutilisés par `lib/lead_extraction/` :

| Prompt | Statut | Usage futur |
|---|---|---|
| `LEAD_QUALIFIER_SCORING_PROMPT` | Conservé, légèrement adapté dans lib/ | Extraction depuis transcriptions |
| `NURTURING_SMS_TEMPLATES` | Conservé | Suggestions de messages dans le dashboard |
| `NURTURING_GENERATION_PROMPT` | Conservé | Génération suggestions relances |
| `LISTING_SYSTEM` | Conservé | Hugo (dormant) |
| `ESTIMATION_SYSTEM` / `ESTIMATION_PROMPT` | Conservé | Thomas (dormant) |
| `ANOMALY_DETECTION_PROMPT` | Conservé | Julie (dormant) |

Les prompts supprimés de `config/prompts.py` :
- `LEAD_QUALIFIER_SYSTEM` (contient les règles comportementales de Léa qui envoie des SMS — obsolète)
- `LEAD_QUALIFIER_FIRST_MESSAGE` (message de bienvenue automatique — plus envoyé)
- `LEAD_QUALIFIER_FIRST_MESSAGE_ANONYMOUS` (idem)

---

## 3. Agents dormants (Option B)

Ces agents restent dans le repo, désactivés via `ENABLE_LEGACY_AGENTS=false`.

### Hugo — ListingGeneratorAgent (`agents/listing_generator.py`)
**Fonction** : Génération d'annonces immobilières SEO (200-400 mots) + version courte (80 mots) + prompts DALL-E.  
**Dashboard** : Page `04_annonce.py` — accessible si `ENABLE_LEGACY_AGENTS=true`  
**Route API** : `POST /api/listings/generate` — désactivée  
**Décision finale** : avant 2026-10-26

### Thomas — EstimationAgent (`agents/estimation.py`)
**Fonction** : Estimation prix bien via méthode DVF + ajustements qualitatifs. Rapport PDF.  
**Dashboard** : Page `05_estimation.py` — accessible si `ENABLE_LEGACY_AGENTS=true`  
**Route API** : `POST /api/estimation` — désactivée  
**Décision finale** : avant 2026-10-26

### Julie — AnomalyDetectorAgent (`agents/anomaly_detector.py`)
**Fonction** : Détection anomalies dossiers (financement insuffisant, titre manquant, incohérence prix).  
**Dashboard** : Intégrée dans le dashboard leads — désactivée si `ENABLE_LEGACY_AGENTS=false`  
**Route API** : `POST /api/anomaly` — désactivée  
**Décision finale** : avant 2026-10-26

---

## 4. SMSPartner — Rebrancher si besoin

**Code supprimé** : `tools/smspartner_tool.py`  
**DB préservée** : colonne `users.smspartner_number` (deprecated, ne pas supprimer)

**Pour rebrancher :**
1. Récupérer `smspartner_tool.py` depuis git (`git show HEAD~:tools/smspartner_tool.py`)
2. Ajouter `SMSPARTNER_API_KEY` dans `.env.example`
3. Remettre `smspartner_api_key` dans `config/settings.py`
4. Point d'intégration : `agents/nurturing.py` méthode `_send_message()` (actuellement n'envoie que des reminders)

**Cas d'usage** : Si les coûts Twilio SMS (France, ~0.08€/SMS) deviennent significatifs, SMSPartner est ~0.04€/SMS.

---

## 5. ElevenLabs — Voix synthétisées

**Code supprimé** : `tools/elevenlabs_tool.py`  
**MP3 supprimés** : 147 fichiers dans `data/audio/` (tous générés, aucun asset manuel)

**Pour rebrancher :**
- Récupérer depuis git si besoin d'une voix TTS française dans un futur produit vocal
- Les voix françaises utilisées : Thomas (ID dans elevenlabs_tool.py), Rachel, Charlotte
- Alternative gratuite pour les appels : Twilio TTS natif (suffit pour l'archi actuelle)

---

## 6. Orchestrator LangGraph — Ce qui est supprimé

`orchestrator.py` était le StateGraph LangGraph qui pilotait l'ensemble du pipeline SMS :
```
check_existing_lead → qualify_new_lead / continue_qualification
                   → route_lead → trigger_nurturing / propose_rdv
                   → handle_rdv_confirmation
```

**Ce qui est récupérable si besoin :**
- Structure du graphe : utile comme référence pour un futur pipeline de traitement des transcriptions
- `make_initial_state()` : initialisation de l'état conversationnel
- `node_propose_rdv()` et `node_handle_rdv_confirmation()` : logique de booking RDV (peut resservir)

Ces nœuds sont archivés dans git. Pour les retrouver :
```
git show cleanup-pivot~N:orchestrator.py  # remplacer N par le commit avant suppression
```

---

## 7. Retell — Notes pour le sprint Capture Appels

**Code supprimé** : `agents/voice_inbound.py`, route `/webhooks/retell`  
**DB préservée** : colonne `calls.retell_call_id`

**Pour le sprint Capture Appels, réutiliser :**
- La structure de table `calls` (id, lead_id, client_id, direction, statut, duration, created_at)
- `_save_call_to_db()` et `_update_call_in_db()` du VoiceInboundAgent — logique DB réutilisable
- `_analyze_call_transcript()` — le prompt d'analyse sera adapté pour Whisper

**Migration à planifier :**
```sql
ALTER TABLE calls 
    ADD COLUMN IF NOT EXISTS recording_url TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS transcript TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS whisper_model TEXT DEFAULT NULL;
-- Plus tard : DROP COLUMN retell_call_id (après migration données)
```

---

## 4. Dashboard — Pages supprimées (Grand ménage 2026-04-29)

### Pages supprimées

| Page | Fichier | Raison |
|---|---|---|
| Utilisation | `dashboard/pages/02_utilisation.py` | Métriques liées aux agents morts (listings, estimations, staging, tokens Léa) |
| Générer une annonce | `dashboard/pages/04_annonce.py` | Hugo désactivé (`ENABLE_LEGACY_AGENTS=false`) |
| Estimer un bien | `dashboard/pages/05_estimation.py` | Thomas désactivé (DVF + Claude) |
| Admin | `dashboard/pages/07_admin.py` | Doublon de `00_proprietaire.py`, déjà masqué en prod |
| Calendrier | `dashboard/pages/08_agenda.py` | Google Calendar OAuth — à rebrancher sur le nouveau produit plus tard |
| Conversations | `dashboard/pages/10_conversations.py` | Historique SMS brut absorbé par la timeline dans `01_mes_leads.py` |

### Mode démo désactivé

`dashboard/auth_ui.py` — `_DEMO_ENABLED = False`

**Pourquoi :** le jeu de données démo (demo.dumortier@proppilot.fr) était
constitué de données liées à l'ancien produit (leads SMS, qualification Léa,
annonces Hugo). Il ne reflète plus le nouveau produit (capture appels, mémoire
commerciale).

**Pour réactiver :**
1. Passer `_DEMO_ENABLED = True` dans `dashboard/auth_ui.py`
2. Créer un nouveau seed dans `scripts/seed_demo_data.py` avec :
   - Des appels avec transcriptions et extractions Claude
   - Des reminders créés par Marc
   - Des leads avec historique multi-canal
3. Seeder la base : `python scripts/seed_demo_data.py`
4. Reconfigurer la visibilité des pages en mode démo dans le bloc `elif is_demo:`

### Pages conservées (navigation post-pivot)

**Boutons explicites en sidebar (ordre prioritaire) :**
- 📋 Mes tâches du jour → `tasks.py`
- 👥 Mes leads → `01_mes_leads.py`
- 📞 Appels capturés → `calls.py`

**Auto-nav Streamlit (outils secondaires) :**
- 💰 ROI & Performance → `03_roi.py`
- ⚙️ Configuration → `06_parametres.py`
- 💳 Abonnement → `09_facturation.py`
- 🔗 Intégrations → `11_integrations.py`

**Admin uniquement :**
- 🔐 Propriétaire → `00_proprietaire.py`
