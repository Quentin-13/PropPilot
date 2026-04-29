# Sprint Dashboard MVP — État d'Avancement

**Branche** : `feature/dashboard-mvp`
**Statut** : ✅ Terminé — 5 étapes complètes, 5 commits atomiques
**Démarré** : 2026-04-29

---

## Architecture dashboard existante (état initial)

### Pages actuelles
| Fichier | Titre | Rôle |
|---|---|---|
| `app.py` | Accueil | KPIs, agents IA, activité récente |
| `00_proprietaire.py` | Propriétaire | Vue admin Quentin |
| `01_mes_leads.py` | Mes leads | Pipeline + tableau + actions rapides |
| `02_utilisation.py` | Utilisation | Quotas d'usage par tier |
| `03_roi.py` | ROI | Calcul retour sur investissement |
| `04_annonce.py` | Annonce | Générateur d'annonces (Hugo) |
| `05_estimation.py` | Estimation | Estimateur DVF (Thomas) |
| `06_parametres.py` | Paramètres | Config agence, numéros, webhooks |
| `07_admin.py` | Admin | Admin clients (obsolète) |
| `08_agenda.py` | Agenda | Calendrier Google |
| `09_facturation.py` | Facturation | Stripe + statut abonnement |
| `10_conversations.py` | Conversations | Historique SMS/WhatsApp |
| `11_integrations.py` | Intégrations | CRM, SeLoger, etc. |

### Patterns clés
- Auth via `dashboard/auth_ui.py` : `require_auth()` + `render_sidebar_logout()`
- `client_id = st.session_state.get("user_id", settings.agency_client_id)`
- DB directement via `memory/` — pas via l'API
- Mode démo : `st.session_state.get("is_demo", False)`
- ROOT = `Path(__file__).parent.parent.parent` dans les pages

### Tables Sprint A disponibles
- `calls` : enrichie avec call_sid, from_number, to_number, status, transcript_text, recording_url, etc.
- `call_extractions` : données Claude extraites (score, résumé, budget, zone, etc.)
- `agency_phone_numbers` : mapping numéro Twilio → agence/agent
- `reminders` : tâches planifiées par l'agent Marc

---

## Plan d'attaque

### Étape 1 — Préparation ✅
- [x] Branche `feature/dashboard-mvp` créée
- [x] `SPRINT_DASHBOARD_PROGRESS.md` créé
- [x] Architecture existante analysée

### Étape 2 — Page "Appels capturés" ✅
- [x] `memory/call_repository.py` enrichi : `get_calls_by_client`, `count_calls_by_client`
- [x] `dashboard/pages/calls.py` créé
- [x] Commit f74018e + push

### Étape 3 — Page "Mes leads" enrichie ✅
- [x] `memory/call_repository.py` : `get_calls_by_lead`, `get_extractions_by_lead`
- [x] `memory/reminder_repository.py` créé (CRUD reminders)
- [x] `dashboard/pages/01_mes_leads.py` enrichi :
  - Timeline multi-canal (SMS/WhatsApp/email + appels mélangés, triés date desc)
  - Click-to-call réel (POST /api/calls/outbound avec JWT)
  - Section "Données extraites" agrégées depuis call_extractions
- [x] Commits 472cebd + c118084

### Étape 4 — Page "Mes tâches du jour" ✅
- [x] `dashboard/pages/tasks.py` créé
- [x] Sections : En retard / Aujourd'hui / À venir (expander)
- [x] Reminders depuis table `reminders` (agent Marc)
- [x] Boutons : Marquer comme fait + Reporter (date picker inline)
- [x] Lien lead clickable → switch_page vers fiche lead
- [x] Commit d961bf7

### Étape 5 — Navigation ✅
- [x] 3 boutons explicites dans la sidebar : Tâches / Leads / Appels
- [x] CSS pour masquer ces pages de l'auto-nav Streamlit (évite doublon)
- [x] Compatible mode démo (CSS ajouté pour les 2 modes)
- [x] Commit 661059b

---

## Décisions produit (Étape 2)

### Layout appels capturés
- Filtre période en en-tête (Aujourd'hui / 7j / 30j / Personnalisé)
- `st.dataframe` avec sélection de ligne pour la liste
- Panneau détail en dessous du tableau quand ligne sélectionnée
- `st.audio` pour la lecture audio (URL B2 ou signée si B2 disponible)
- `st.text_area` read-only pour la transcription complète
- Pagination Prev/Next avec 20 appels par page

### Gestion cas limites
- Pas d'enregistrement : message "Enregistrement non disponible"
- Transcription vide ou en cours : message approprié
- Extraction absente : section masquée
- URL B2 mock (démo) : audio masqué avec avertissement
- Colonnes Sprint A absentes : message d'erreur explicite

### Compatibilité mode démo
- La page se charge normalement en mode démo
- Les données fictives dans la table calls s'affichent
- Si aucun appel en base : message vide avec CTA

---

## Fichiers créés/modifiés

| Fichier | Type | Rôle |
|---|---|---|
| `memory/call_repository.py` | modifié | +get_calls_by_client, +count_calls_by_client, +get_calls_by_lead, +get_extractions_by_lead |
| `memory/reminder_repository.py` | nouveau | CRUD reminders (get, mark_done, snooze) |
| `dashboard/pages/calls.py` | nouveau | Page Appels capturés |
| `dashboard/pages/01_mes_leads.py` | modifié | Timeline + click-to-call + extractions agrégées |
| `dashboard/pages/tasks.py` | nouveau | Page Mes tâches du jour |
| `dashboard/auth_ui.py` | modifié | Navigation : boutons Tâches/Leads/Appels + CSS anti-doublon |
| `SPRINT_DASHBOARD_PROGRESS.md` | nouveau | Ce fichier |

---

## Procédure de test manuel

### Prérequis
1. Migration Sprint A appliquée : `alembic upgrade head`
2. Serveur FastAPI démarré : `uvicorn server:app --reload`
3. Dashboard démarré : `streamlit run dashboard/app.py`
4. Se connecter avec un compte client (pas admin)

### Test page Tâches du jour
1. Cliquer "📋 Tâches du jour" dans la sidebar
2. Vérifier les 3 sections (En retard / Aujourd'hui / À venir)
3. Si vide : "Aucune tâche planifiée" → normal si pas de reminders en base
4. Cliquer "✅ Fait" sur un reminder → disparaît, message succès
5. Cliquer "⏰ Reporter" → formulaire date/heure apparaît → saisir + confirmer
6. Cliquer "👤 [Nom lead]" → bascule vers la fiche lead

### Test page Mes leads (enrichie)
1. Cliquer "👥 Mes leads" dans la sidebar
2. Sélectionner un lead dans le tableau
3. Vérifier la section "Historique des interactions" (SMS + appels chronologiques)
4. Vérifier la section "Données extraites des appels" (si appels analysés)
5. Cliquer "📞 Appeler" → en mode mock : message "Appel initié (mock)"

### Test page Appels capturés
1. Cliquer "📞 Appels capturés" dans la sidebar
2. Vérifier les filtres (Aujourd'hui / 7j / 30j / Custom) et Direction
3. Sélectionner un appel dans le tableau
4. Vérifier l'affichage détail : audio (si recording_url), transcription, extraction
5. Cliquer "👤 Voir la fiche lead" → bascule vers fiche lead

### Limitations connues
- **Click-to-call** : requiert que la colonne `phone` existe dans `users` (pas dans le schéma actuel → 400 en mode réel, mock OK)
- **Audio B2** : les buckets privés nécessitent les credentials B2 pour générer une URL signée
- **Reminders** : créés uniquement par l'agent Marc (nurturing) — table vide si pas de leads traités
- **Signed URL** : expire après 1h — rafraîchir la page si l'audio ne se lit plus
