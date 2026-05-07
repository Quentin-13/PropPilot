# PropPilot — Pilot Readiness

Branch `feat/pilot-readiness` — 5 chantiers, 5 commits, prêt à merger.

---

## Ce qui est prêt

### Chantier 1 — Scoring deux grilles (commit `8bca208`)
- **Acheteur** : urgence×3, capacité_fin×2, engagement×2, motivation×1 → max 24
- **Vendeur** : urgence×3, maturité×3, qualité_bien×2, motivation×1 → normalisé 24
- Redistribution pondérée si un axe est inconnu (null ≠ 0)
- Seuils : ≥18 chaud, ≥11 tiède, <11 froid
- Migrations : `010_add_lead_type_to_leads.py`, `011_add_extraction_status.py`
- Tests : `tests/test_scoring.py` (23 tests)

### Chantier 2 — Filet de sécurité extraction (commit `d86f178`)
- Retry 3× avec backoff 1s / 3s / 9s
- Validation Pydantic : `lead_type` obligatoire dans `{acheteur, vendeur, locataire}`
- `extraction_status = 'failed'` si toutes les tentatives échouent
- `save_call_extraction()` / `save_sms_extraction()` : ne jamais écraser les données lead sur échec
- Logs structurés JSON sur chaque échec
- Tests : `tests/test_extraction_retry.py` (16 tests)

### Chantier 3 — Admin health + alerting (commit `4979100`)
- `GET /admin/health` sécurisé `X-Admin-Key` → métriques complètes + alertes actives
- Alertes : `NO_ACTIVITY_6H`, `EXTRACTION_FAILED_N`, `SMS_QUEUE_DELAYED_NMin`, `DB_DOWN`, `TWILIO_DOWN`
- `run_health_alert_job()` toutes les 15 min → SMS sur `ADMIN_PHONE` si alerte
- `_check_no_vendeur_7j()` : alerte si agence active sans lead vendeur depuis 7j
- Variable d'env : `ADMIN_PHONE`
- Tests : `tests/test_admin_health.py` (17 tests)

### Chantier 4 — Isolation multi-tenant (commit `584560b`)
- `get_lead(lead_id, client_id=None)` : filtre par agence si `client_id` fourni
- `GET /api/calls/{call_id}` : 403 si appel d'une autre agence
- `GET /api/calls/{call_id}/extraction` : 403 idem
- `POST /api/calls/outbound` : vérifie appartenance du lead avant de donner le téléphone
- Migration `012_add_client_id_to_conversation_extractions.py` + backfill
- Tests : `tests/test_multitenant_isolation.py` (8 tests)

### Chantier 5 — Dashboard pilot-ready (commit `4e63f4f`)
- `01_mes_leads.py` : 4 KPI cards (🔥 À rappeler, 🏠 Vendeurs chauds, 🔑 Acheteurs chauds, ⚠️ À vérifier), filtre `lead_type`, score `/24`, badge type, bouton ☎️ Rappelé
- `02_a_verifier.py` : page "À vérifier manuellement" — transcript brut + saisie manuelle score/type/statut
- `05_pipeline.py` : vue pipeline avec onglets vendeur/acheteur/locataire, filtre période, cards triées score desc

---

## Migrations à appliquer en prod (dans l'ordre)

```bash
alembic upgrade 010  # lead_type sur leads
alembic upgrade 011  # extraction_status sur leads + conversation_extractions
alembic upgrade 012  # client_id sur conversation_extractions
```

Ou en une fois :
```bash
alembic upgrade head
```

---

## Variables d'env nouvelles

```env
ADMIN_PHONE=+33600000000   # Numéro SMS pour les alertes monitoring
```

---

## Ce qui n'a pas été fait (hors scope)

- Tests end-to-end avec deux vraies agences en DB (les tests d'isolation sont mockés)
- Backfill `lead_type` sur les leads historiques (migration 010 backfille vente→vendeur, location→locataire, reste→acheteur)
- Rate-limiting par IP sur les webhooks (non demandé dans le scope)
- Tests Streamlit (pas de framework de test headless configuré)

---

## À tester manuellement avant onboarding pilote

1. Envoyer un SMS → vérifier `lead_type` détecté, score /24 dans le dashboard
2. Forcer une extraction failed (couper ANTHROPIC_API_KEY) → vérifier page "À vérifier"
3. Appeler `/admin/health` avec `X-Admin-Key` → vérifier JSON structuré
4. Créer 2 comptes → vérifier que leads/appels d'un compte ne sont pas visibles depuis l'autre
5. Vérifier que les migrations 010-012 passent sur la DB prod avant le premier pilote
