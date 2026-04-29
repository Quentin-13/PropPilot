# Sprint Dashboard MVP — État d'Avancement

**Branche** : `feature/dashboard-mvp`
**Statut** : 🔄 En cours — Étape 2 (Page Appels)
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

### Étape 2 — Page "Appels capturés" 🔄
- [x] `memory/call_repository.py` enrichi : `get_calls_by_client`, `count_calls_by_client`
- [x] `dashboard/pages/calls.py` créé
- [ ] Commit + push
- [ ] Validation Quentin

### Étape 3 — Page "Mes leads" enrichie ⬜
- [ ] Enrichir `dashboard/pages/01_mes_leads.py`
- Timeline multi-canal (SMS + appels)
- Click-to-call → POST /api/calls/outbound
- Sections "Données extraites" agrégées depuis call_extractions

### Étape 4 — Page "Mes tâches du jour" ⬜
- [ ] `dashboard/pages/tasks.py` créé
- Sections : À faire aujourd'hui / En retard / À venir
- Reminders créés par Marc (table `reminders`)
- Boutons : Marquer comme fait / Reporter

### Étape 5 — Navigation + tests visuels ⬜
- [ ] Réorganiser la navigation (tasks en premier)
- [ ] Vérifier mode démo compatible
- [ ] Tests manuels documentés

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

### Étape 2
- `memory/call_repository.py` — ajout `get_calls_by_client`, `count_calls_by_client`
- `dashboard/pages/calls.py` — page appels capturés (nouvelle)
- `SPRINT_DASHBOARD_PROGRESS.md` — ce fichier

---

## Procédure de test manuel (à compléter)

À remplir après chaque étape.
