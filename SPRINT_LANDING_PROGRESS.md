# Sprint Landing Redesign — Suivi de progression

Branche : `feature/landing-redesign`
Démarré : 2026-04-28

---

## Étapes

| # | Titre | Statut |
|---|-------|--------|
| 1 | Setup (branche + backup + ce fichier) | ✅ Terminé |
| 2 | Backend waitlist (migration 003 + endpoint API + emails) | ✅ Terminé |
| 3 | Frontend HTML/CSS structure | ✅ Terminé |
| 4 | Frontend JavaScript + intégration formulaire | ✅ Terminé |
| 5 | Documentation + vérifications finales | ⬜ À faire |

---

## Étape 1 — Setup ✅

- [x] Branche `feature/landing-redesign` créée depuis `main`
- [x] Backup de l'ancien `index.html` → `static/legacy/index_old.html`
- [x] Création de `SPRINT_LANDING_PROGRESS.md`

---

## Étape 2 — Backend waitlist ✅

### Migration Alembic 003
- [x] Fichier `alembic/versions/003_add_waitlist_table.py`
- [x] Table `waitlist` avec colonnes : id, prenom, nom, email (unique), agence,
      type_agence, taille_equipe, crm_utilise, source, ip_address, created_at, updated_at

### Endpoint API
- [x] `POST /api/waitlist` (validation Pydantic + insert + emails)
- [x] `GET /api/waitlist/count` (compteur public)
- [x] Rate limiting (max 5/IP/heure)
- [x] Honeypot field anti-spam

### Emails SendGrid
- [x] Email confirmation prospect (HTML responsive)
- [x] Email notification admin (tableau détails inscription)
- [x] Variables env : `ADMIN_NOTIFICATION_EMAIL`, `WAITLIST_EMAIL_FROM`

---

## Étape 3 — Frontend HTML/CSS ✅

- [x] Section 1 : Hero (mockup pipeline animé)
- [x] Section 2 : Le problème (3 stats clés)
- [x] Section 3 : La solution (3 piliers)
- [x] Section 4 : Comment ça marche (3 étapes)
- [x] Section 5 : Avant / Après (tableau comparatif)
- [x] Section 6 : CRM compatibles (6 badges)
- [x] Section 7 : Roadmap publique (4 phases V1-V4)
- [x] Section 8 : Formulaire waitlist (7 champs)
- [x] Footer avec liens légaux
- [x] CSS mobile-first responsive (breakpoints 600/768/900px)
- [x] SEO meta tags (og:, twitter:, description)

---

## Étape 4 — JavaScript + intégration ✅

- [x] Validation frontend formulaire (blur + submit)
- [x] Fetch async vers `/api/waitlist`
- [x] Message de confirmation post-submit
- [x] Animations scroll (IntersectionObserver)
- [x] Compteur dynamique waitlist (`/api/waitlist/count`)

---

## Étape 5 — Documentation + déploiement ⬜

- [ ] README mis à jour
- [ ] Tests responsive mobile/desktop
- [ ] Tests multi-navigateurs
- [ ] Récap final + captures d'écran

---

## Décisions & notes

- Design : dark mode (cohérent avec l'ancienne landing `#09090b`)
- Accent : vert lime (`#a3e635`) — identité PropPilot maintenue
- Copywriting : placeholders `[À VALIDER]` jusqu'à validation des textes définitifs
- Pas de framework JS, pas d'analytics dans ce sprint
