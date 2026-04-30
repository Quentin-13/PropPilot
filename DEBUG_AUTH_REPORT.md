# Diagnostic Auth — Perte de session au refresh

## 1. Cause confirmée du bug

**`extra_streamlit_components` n'est pas installé dans l'environnement Python.**

```
$ python3 -c "import extra_streamlit_components"
ModuleNotFoundError: No module named 'extra_streamlit_components'
```

Seul `streamlit 1.54.0` est présent. Le package est listé dans `requirements.txt`
mais absent de l'environnement (`pip3 list` ne le montre pas).

---

## 2. Architecture auth actuelle (avec lignes)

### Flux login réussi

```
dashboard/auth_ui.py:229  if submitted:
dashboard/auth_ui.py:234    result = _do_login(email, password)  ← httpx POST /auth/login (FastAPI)
dashboard/auth_ui.py:244    _set_session(token, uid, ...)        ← écrit dans st.session_state
dashboard/auth_ui.py:254    _cookie_save(uid, token, ...)        ← censé écrire les cookies
dashboard/auth_ui.py:257    st.rerun()
```

### Flux restore au refresh (require_auth)

```
dashboard/auth_ui.py:366    if st.session_state.get("authenticated"):  → pas là après refresh
dashboard/auth_ui.py:375    get_cookie_manager()                        ← rend le composant React
dashboard/auth_ui.py:377    if is_cookie_loading():                     → render #1 : spinner
dashboard/auth_ui.py:385    saved = _cookie_load()                      ← render #2+ : lit les cookies
dashboard/auth_ui.py:386    if saved: _set_session(...); st.rerun()     → réhydrate la session
```

### Ce que fait get_cookie_manager() (auth_cookies.py:55)

```python
try:
    import extra_streamlit_components as stx   # ← ModuleNotFoundError ici
    cm = stx.CookieManager(key="proppilot_cookies")
    st.session_state[_CM_KEY] = cm
except Exception as e:
    logger.warning("CookieManager indisponible : %s", e)
    st.session_state[_CM_KEY] = None           # ← cm = None silencieusement
    cm = None
```

---

## 3. Cascade d'effets du bug

| Fonction | Comportement actuel | Effet |
|---|---|---|
| `get_cookie_manager()` | retourne `None` (import raté) | aucun composant React rendu |
| `is_cookie_loading()` | retourne `False` (car cm est None, ligne 98-99) | pas de spinner, auth page directe |
| `save_session()` | `if not cm: return` (ligne 119) | aucun cookie écrit après login |
| `load_session()` | `if not cm: return None` (ligne 146) | aucune session restorée au refresh |

**Résultat :** La session vit uniquement dans `st.session_state`, effacé à chaque refresh.
Le login fonctionne (httpx vers FastAPI OK), mais la persistance est 100% inopérante.

---

## 4. Pourquoi aucun cookie visible dans DevTools

Confirmé par le diagnostic : `cm.set()` n'est jamais appelé. Il n'y a pas de
composant React en DOM. Aucune écriture navigateur n'a lieu.

---

## 5. Pourquoi "aucune requête HTTP" visible dans Network

Normal : Streamlit gère les soumissions de formulaires via WebSocket, pas HTTP.
L'appel httpx à FastAPI s'exécute côté serveur Python — il n'apparaît pas dans
les DevTools navigateur. Ce n'est pas un symptôme du bug.

---

## 6. Fix proposé : migrer vers streamlit-cookies-controller

### Pourquoi pas juste `pip install extra-streamlit-components` ?

- Dernière release : 2023 (abandonné)
- Bugs connus avec Streamlit ≥ 1.35 (composant React déprécie des APIs)
- Stocker 8 cookies séparés déclenche 8 reruns via `cm.set()` — instable
- Pas de garantie que les 8 `cm.set()` passent avant le `st.rerun()` qui suit

### Solution choisie : `streamlit-cookies-controller`

- Maintenu activement, compatible Streamlit 1.x
- API propre : `controller.get()`, `controller.set()`, `controller.remove()`
- Stocke une session JSON en **1 seul cookie** → 1 seul `set()` → stable
- Même comportement double-render géré proprement

### Changements prévus

**`requirements.txt`**
```diff
-extra-streamlit-components>=0.1.60
+streamlit-cookies-controller>=0.2.0
```

**`dashboard/auth_cookies.py`** — réécriture complète :
- Remplace `stx.CookieManager` par `CookieController` (streamlit_cookies_controller)
- Stocke la session comme un seul JSON signé : `proppilot_session`
- Conserve la même API publique (`get_cookie_manager`, `is_cookie_loading`,
  `save_session`, `load_session`, `clear_session`) → `auth_ui.py` inchangé
- Gère le double-render : `controller.getAll() is None` = render #1

**`dashboard/auth_ui.py`** — aucun changement requis.

### Logique du double-render avec le nouveau composant

```
Render #1 : controller.getAll() → None  → is_cookie_loading() = True  → spinner
Render #2 : controller.getAll() → {}    → is_cookie_loading() = False → load_session()
```

### Cookie unique (plus stable)

Au lieu de 8 cookies séparés :
```python
# Avant (8 cm.set() = 8 reruns potentiels)
proppilot_user_id, proppilot_token, proppilot_agency_name, ...

# Après (1 set() = stable)
proppilot_session = '{"user_id": "...", "token": "...", "hmac": "...", ...}'
```

---

## 7. Périmètre du fix

| Fichier | Action |
|---|---|
| `requirements.txt` | `-extra-streamlit-components` / `+streamlit-cookies-controller` |
| `dashboard/auth_cookies.py` | réécriture (API publique préservée) |
| `dashboard/auth_ui.py` | aucun changement |
| `dashboard/pages/*.py` | aucun changement |

Pas de commit, pas de push avant validation.
