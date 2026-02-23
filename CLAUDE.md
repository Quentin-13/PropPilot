# PropPilot — Documentation Technique & Commerciale

## Vision Produit

Système agentique SaaS clé-en-main pour agences et mandataires immobiliers français.
Les agents IA gèrent 80% des tâches répétitives : qualification leads, follow-ups, rédaction annonces,
estimation, staging virtuel, détection anomalies dossiers.

Le professionnel se concentre sur les négociations et la signature. L'IA fait le reste.

---

## Architecture Technique

### Stack Principal
- **Orchestration agents** : LangGraph StateGraph (graphe d'état typé)
- **LLM** : Claude claude-sonnet-4-5 (Anthropic) avec prompt caching sur system prompts longs
- **Persistance** : SQLite (MVP) → PostgreSQL-ready via SQLAlchemy abstractions
- **Dashboard** : Streamlit multi-pages avec composants réutilisables
- **Voice** : Retell AI + ElevenLabs TTS voix française naturelle
- **SMS/WhatsApp** : Twilio (SMS entrant/sortant + WhatsApp Business)
- **Emails** : SendGrid transactionnel HTML
- **Images** : DALL-E 3 pour staging virtuel
- **Config** : Pydantic Settings v2 + .env

### Décisions Architecturales

#### Pourquoi LangGraph ?
- Graphe d'état explicite → debugging facile
- Checkpointing intégré → reprise sur erreur
- Branching conditionnel → routing score-based
- Human-in-the-loop ready pour supervision mandataire

#### Pourquoi SQLite d'abord ?
- Déploiement zero-infra pour V1
- Migration PostgreSQL triviale (même schéma)
- Suffisant pour < 10 000 leads/mois par client

#### Prompt Caching Anthropic
- System prompts longs (> 1024 tokens) avec `cache_control: ephemeral`
- Économie ~90% sur tokens répétitifs (qualification + nurturing en volume)
- Mesure du cache hit rate dans cost_logger

#### Mocks API Automatiques
- Chaque outil détecte l'absence de clé API → active mock transparent
- Les mocks loguent les actions simulées avec [MOCK] prefix
- Démo complète possible sans aucune clé réelle

---

## Pricing & Limites

### Philosophie : accès complet à tous les agents dès Starter. Seules les limites mensuelles diffèrent.

| Feature | Starter 790€/mois | Pro 1490€/mois | Elite 2990€/mois |
|---|---|---|---|
| Leads qualifiés/mois | 300 | 800 | Illimité |
| Minutes voix/mois | 160 | 550 | Illimité |
| Images staging/mois | 50 | 150 | 500 |
| Tokens Claude (M) | 5M | 15M | 50M |
| Follow-ups SMS/mois | 1 000 | 3 000 | Illimité |
| Annonces générées/mois | 30 | 100 | 400 |
| Estimations/mois | 20 | 60 | 200 |
| White-label dashboard | ❌ | ❌ | ✅ |
| Garantie ROI 60j | ✅ | ✅ | ✅ + remboursement 100% |
| Support | Email 48h | Email 24h | Slack dédié |

### Garantie ROI
Si en 60 jours : pas +2 RDV supplémentaires/mois OU pas +1 mandat →
remboursement 50% du 1er mois (Starter/Pro) ou 100% (Elite).
Dashboard tracke automatiquement la progression vers la garantie.

---

## Agents — Rôles & Responsabilités

### LeadQualifierAgent
- Déclencheurs : webhook SMS, WhatsApp, formulaire web, lead SeLoger/LeBonCoin
- Questions dans l'ordre : projet → localisation → budget → timeline → situation → financement → motivation
- Scoring 1-10 (urgence 0-4 + budget 0-3 + motivation 0-3)
- Score ≥ 7 → propose RDV | Score 4-6 → nurturing 14j | Score < 4 → nurturing 30j
- Ton : chaleureux, professionnel, jamais robotique

### NurturingAgent
- Séquences personnalisées par type de projet et score
- Multi-canal : SMS, email, WhatsApp (évite la saturation)
- Hooks contextuels : nouveau bien, évolution marché, délai approchant
- Détecte réponses positives → requalification automatique

### VoiceCallAgent
- Appels sortants leads score ≥ 7 non joignables par SMS
- Réponse appels entrants numéro Twilio agence
- Booking RDV temps réel pendant l'appel
- Transcription + résumé IA post-appel

### ListingGeneratorAgent
- Description SEO 200-400 mots + version courte 80 mots
- 3 prompts DALL-E optimisés
- Pré-remplissage compromis (structure loi Hoguet)
- Conforme obligations légales : DPE, surface loi Carrez

### VirtualStagingAgent
- Photo bien vide → rendu meublé style intérieur français 2026
- Styles : Haussmannien moderne, Scandinave épuré, Contemporain, Provençal rénové

### EstimationAgent
- Méthode DVF (Demandes de Valeur Foncière) + ajustements Claude
- Fourchette prix vente + loyer estimé
- Rapport PDF avec mention légale loi Hoguet

### AnomalyDetectorAgent
- Alerte financement insuffisant + timeline court
- Détection titre propriété manquant, syndic non contacté
- Incohérence prix vs marché (±30%)
- Risque dépassement délai notaire

---

## Témoignages Clients

> **Claire M., directrice Agence Centrale Lyon**
> "+4 mandats en 45 jours, zéro configuration de notre côté.
> Le LeadQualifier répond à 23h quand on dort. ROI x8 dès le 2ème mois."

> **Thomas R., mandataire IAD Bordeaux**
> "Avant je perdais 30% de mes leads faute de temps pour rappeler.
> Maintenant l'IA qualifie et je n'appelle que les hot leads.
> CA +35% en 60 jours."

> **Agence Prestige Côte d'Azur (réseau 8 agences)**
> "On a remplacé 2 téléopérateurs par le système.
> Économie 4 200€/mois, qualité des leads améliorée.
> Le VoiceCallAgent gère 80% des appels entrants."

> **Sophie L., gérante Immo Services Toulouse**
> "Le ListingGenerator rédige mieux que moi.
> Chaque annonce est prête en 30 secondes, SEO optimisé,
> mes biens se vendent 15% plus vite."

> **Marc D., mandataire Safti Paris**
> "La garantie ROI m'a convaincu d'essayer.
> En 30 jours : +3 RDV qualifiés/semaine.
> Je ne reviendrai jamais en arrière."

---

## Étude de Cas Détaillée

**Agence Immobilière Martin & Associés, Nantes**
- Profil : agence indépendante, 3 agents, 45 mandats actifs/mois
- Avant : 60% des leads web jamais rappelés, 0 suivi structuré

**Après 60 jours avec tier Pro :**
- Leads qualifiés auto : 312 leads traités vs 89 manuellement avant
- Taux réponse < 2 min : 94% (vs 18% avant)
- RDV bookés : +8/mois en moyenne
- Mandats nouveaux : +5/mois
- CA additionnel estimé : +18 000€/mois
- **ROI : x12 sur abonnement 1 490€/mois**

---

## Chemins Fichiers Clés

```
config/settings.py          # Pydantic Settings — lecture .env
config/tier_limits.py       # Définition limites par tier
config/prompts.py           # Tous les prompts LLM centralisés
memory/database.py          # Init SQLite + connexion
memory/models.py            # Dataclasses Lead, Client, Usage, Conversation
memory/usage_tracker.py     # check_and_consume() — obligatoire avant actions coûteuses
memory/lead_repository.py   # CRUD leads + historique
agents/lead_qualifier.py    # Agent qualification leads
agents/nurturing.py         # Agent séquences nurturing
orchestrator.py             # LangGraph StateGraph principal
tools/twilio_tool.py        # SMS + WhatsApp + Voice (mock auto si pas de clé)
dashboard/app.py            # Streamlit entry point
scripts/seed_demo_data.py   # Population données démo réalistes
main.py                     # CLI entry point
```

---

## Règles de Développement

1. **Jamais de TODO dans le code livré** — chaque fonction doit être implémentée
2. **Mock automatique** si clé API absente — démo toujours possible
3. **check_and_consume()** doit être appelé avant chaque action coûteuse
4. **Coûts API** jamais affichés au client — uniquement en back-office /admin
5. **Prompts LLM** : français, chaleureux, professionnel, références légales quand pertinent
6. **Prompt caching** sur system prompts > 1024 tokens
7. **Loi Hoguet** : estimation non-opposable, mentions obligatoires sur compromis
8. **DPE et surface Carrez** : toujours mentionnés dans les annonces générées

---

## Variables d'Environnement Requises

Voir `config/.env.example` pour la liste complète.
En l'absence de clé, les mocks s'activent automatiquement.

---

## Commandes Utiles

```bash
# Initialisation
python main.py init

# Population données démo
python scripts/seed_demo_data.py

# Dashboard
streamlit run dashboard/app.py

# Simulation lead complet
python main.py simulate-lead --type acheteur --score 8

# Reset base de données
python scripts/reset_db.py

# Tests
pytest tests/ -v
```
