# Sprint Dashboard Fixes — PropPilot

## Contexte

Suite au sprint Dashboard MVP (pages Appels, Tâches, Leads enrichie) et au grand
ménage (suppression 6 pages legacy), ce sprint corrige les bugs bloquants identifiés
en production.

---

## Fix 1 — Déconnexion à chaque refresh (bug critique)

**Commits :** `46e6d25` → `fix(auth): persist session across page refresh`  
**Commit final :** voir Fix 1b ci-dessous

### Diagnostic

La lib `extra_streamlit_components.CookieManager` a un comportement en deux renders :

- **Render #1** : le composant React est rendu mais n'a pas encore lu les cookies
  navigateur. `cm.get()` retourne `None` pour tous les champs.
- React se charge (~300 ms), lit les cookies, les envoie à Streamlit → **déclenche render #2**.
- **Render #2** : `stx.CookieManager(key=k)` appelé avec le même `key` retourne la
  valeur stockée dans le registry interne Streamlit → cookies disponibles.

**Bug initial** : le singleton était stocké dans un global module. Au refresh,
`st.session_state` est vidé (nouvelle session WebSocket) mais le module Python ne
l'est pas. `get_cookie_manager()` retournait l'ancien objet sans jamais appeler
`stx.CookieManager()` → le composant React n'était jamais rendu → `cm.get() = None`.

**Bug résiduel après Fix 1** : même en passant le singleton dans `st.session_state`,
le composant React n'était appelé qu'au render #1. En render #2, le singleton existait
→ `stx.CookieManager()` non appelé → l'objet Python avait toujours les valeurs stales
du render #1 (vides). Résultat : `_cookie_load()` retournait `None` en render #2 aussi.

### Solution (Fix 1b)

**`dashboard/auth_cookies.py`** — `get_cookie_manager()` appelle `stx.CookieManager()`
à chaque **nouveau run Streamlit** (détecté via `run_id` de `get_script_run_ctx()`).
Un guard in-render évite le `DuplicateWidgetID` si la fonction est appelée plusieurs
fois dans le même render.

```
render #1 (fresh session)
  └─ get_cookie_manager() → stx.CookieManager() appelé → CM créé, cookies vides
  └─ is_cookie_loading() → True
  └─ _show_cookie_loading_screen() → spinner + st.stop()
  └─ [React lit cookies, envoie à Streamlit, déclenche render #2]

render #2 (déclenché par React)
  └─ get_cookie_manager() → stx.CookieManager() appelé → CM avec vraies valeurs
  └─ is_cookie_loading() → False
  └─ _cookie_load() → dict session complet
  └─ _set_session() → session_state rempli
  └─ st.rerun()

render #3
  └─ authenticated = True → require_auth() retourne → page s'affiche
```

**`dashboard/auth_ui.py`** — `require_auth()` implémente le **3-state auth** :

1. `authenticated = True` → `return` (page s'affiche)
2. `is_cookie_loading() = True` → écran chargement + `st.stop()`
3. Cookie lu, aucune session valide → `show_auth_page()` + `st.stop()`

Le `get_cookie_manager()` n'est appelé que dans le branche "pas encore authentifié"
(optimisation : évite de re-rendre le composant React inutilement sur chaque
navigation entre pages).

### Procédure de test

1. Se connecter avec "Rester connecté 30 jours" coché
2. Refresh (F5) → écran logo + "Chargement de votre session…" (~300 ms)
3. Dashboard s'affiche → **pas de déconnexion**
4. Navigation entre pages → immédiate, pas de spinner
5. Fermer onglet → rouvrir → dashboard direct
6. Déconnexion → login page
7. Se connecter SANS "Rester connecté" → vérifier que session expire à fermeture
   navigateur (cookie sans `expires_at` → session-only)

---

## Fix 2 — Sidebar : boutons obsolètes

**Commit :** `a22c0a8` → `fix(dashboard): replace legacy sidebar buttons with new pages`

- Suppression du bouton "🏠 Accueil" (redondant)
- Masquage CSS complet du `stSidebarNav` auto-generated pour les clients
- Navigation explicite dans l'ordre : Tâches → Leads → Appels → Mes paramètres →
  Abonnement → Intégrations → Déconnexion (en bas)
- ROI retiré de la navigation (relique d'avant-pivot)

---

## Fix 3 — Message "Aucun lead trouvé"

**Commit :** `d1396b4` → `fix(dashboard): render HTML correctly in empty states`

- Message référençant `seed_demo_data.py` (script dev uniquement) remplacé par
  un message production approprié
- Scan automatique de tous les `st.markdown()` avec HTML → `unsafe_allow_html=True`
  présent partout où nécessaire (0 faux positif en production)

---

## Fix 4 — Click-to-call : colonne phone manquante

**Commit :** `5f38da3` → `feat(dashboard): add phone field for click-to-call functionality`

- Migration `004_add_phone_to_users.py` : colonne `phone TEXT` nullable sur `users`
- `06_parametres.py` : section "Mon numéro de téléphone" (format E.164, validation regex)
- `01_mes_leads.py` : bouton "Appeler" conditionnel
  - Agent sans numéro → désactivé + lien "Mes paramètres"
  - Lead sans téléphone → désactivé
  - Tout présent → actif, appel POST `/api/calls/outbound`
- `api/calls.py` lit déjà `users.phone` — la colonne existe maintenant

**Note migration** : lancer `alembic upgrade head` en prod avant de tester le click-to-call.

---

## Limitations connues

- Le délai spinner au refresh (~300 ms) est inhérent à `extra_streamlit_components`
  et au double-render React. Non contournable sans changer de lib.
- Click-to-call en prod nécessite Twilio configuré ; en mode mock : 200 toujours.
- `run_id` provient de `streamlit.runtime.scriptrunner` (API interne Streamlit).
  Stable depuis Streamlit 1.18+, wrappé dans try/except pour sécurité.
