# Sprint Landing Redesign — Suivi de progression

Branche : `feature/landing-redesign`
Démarré : 2026-04-28

---

## Étapes

| # | Titre | Statut |
|---|-------|--------|
| 1 | Setup (branche + backup + ce fichier) | ✅ Terminé |
| 2 | Backend waitlist (migration 003 + endpoint API + emails) | ⬜ À faire |
| 3 | Frontend HTML/CSS structure | ⬜ À faire |
| 4 | Frontend JavaScript + intégration formulaire | ⬜ À faire |
| 5 | Documentation + vérifications finales | ⬜ À faire |

---

## Étape 1 — Setup ✅

- [x] Branche `feature/landing-redesign` créée depuis `main`
- [x] Backup de l'ancien `index.html` → `static/legacy/index_old.html`
- [x] Création de `SPRINT_LANDING_PROGRESS.md`

---

## Étape 2 — Backend waitlist ⬜

### Migration Alembic 003
- [ ] Fichier `alembic/versions/003_add_waitlist_table.py`
- [ ] Table `waitlist` avec colonnes : id, prenom, nom, email (unique), agence,
      type_agence, taille_equipe, crm_utilise, source, ip_address, created_at, updated_at

### Endpoint API
- [ ] `POST /api/waitlist` (validation Pydantic + insert + emails)
- [ ] `GET /api/waitlist/count` (compteur public)
- [ ] Rate limiting (max 5/IP/heure)
- [ ] Honeypot field anti-spam

### Emails SendGrid
- [ ] Email confirmation prospect
- [ ] Email notification admin
- [ ] Variables env : `ADMIN_NOTIFICATION_EMAIL`, `WAITLIST_EMAIL_FROM`

---

## Étape 3 — Frontend HTML/CSS ⬜

- [ ] Section 1 : Hero
- [ ] Section 2 : Le problème
- [ ] Section 3 : La solution (3 piliers)
- [ ] Section 4 : Comment ça marche
- [ ] Section 5 : Avant / Après
- [ ] Section 6 : CRM compatibles
- [ ] Section 7 : Roadmap publique
- [ ] Section 8 : Formulaire waitlist
- [ ] Footer
- [ ] CSS mobile-first responsive
- [ ] SEO meta tags

---

## Étape 4 — JavaScript + intégration ⬜

- [ ] Validation frontend formulaire
- [ ] Fetch async vers `/api/waitlist`
- [ ] Message de confirmation post-submit
- [ ] Animations scroll
- [ ] Compteur dynamique waitlist

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
