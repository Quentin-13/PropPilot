"""
Auto-refresh intelligent pour les pages dashboard — sans perte de saisie.

Conditions de déclenchement (toutes requises) :
  - Onglet en arrière-plan (document.hidden) OU inactivité > interval_seconds
  - ET aucun input/textarea/contenteditable n'est focus
  - ET aucun champ de texte n'a de contenu non vide

Condition bloquante : dès qu'un input a du contenu ou est focus → jamais de refresh.
"""
from __future__ import annotations

import streamlit.components.v1 as components


def inject_smart_refresh(interval_seconds: int = 60) -> None:
    """
    Injecte un composant JS invisible (iframe hauteur=0) qui recharge la page
    Streamlit uniquement quand c'est sûr de le faire.

    Placer cet appel en DERNIER dans la page pour ne pas interrompre
    les form_submit ou les on_select en cours d'exécution.
    """
    ms = interval_seconds * 1000
    js = f"""
<script>
(function () {{
    var INTERVAL = {ms};
    var lastActivity = Date.now();

    // Suivre toute interaction dans la page parente
    function _track() {{ lastActivity = Date.now(); }}
    try {{
        var p = window.parent;
        ['mousemove', 'keydown', 'click', 'touchstart', 'scroll'].forEach(function (e) {{
            p.document.addEventListener(e, _track, true);
        }});
    }} catch (ignored) {{}}

    function isSafeToRefresh() {{
        try {{
            var pd = window.parent.document;
            // Vérifier l'élément actif
            var el = pd.activeElement;
            if (el) {{
                var tag = (el.tagName || '').toLowerCase();
                if (tag === 'input' || tag === 'textarea') return false;
                if (el.contentEditable === 'true') return false;
            }}
            // Vérifier si des inputs ont du texte
            var fields = pd.querySelectorAll('input[type="text"], textarea');
            for (var i = 0; i < fields.length; i++) {{
                if (fields[i].value && fields[i].value.trim().length > 0) return false;
            }}
        }} catch (e) {{
            // En cas d'erreur cross-origin inattendue, ne pas rafraîchir
            return false;
        }}
        return true;
    }}

    setInterval(function () {{
        try {{
            var hidden = window.parent.document.hidden;
            var inactive = (Date.now() - lastActivity) > INTERVAL;
            if ((hidden || inactive) && isSafeToRefresh()) {{
                window.parent.location.reload();
            }}
        }} catch (e) {{}}
    }}, INTERVAL);
}})();
</script>
"""
    components.html(js, height=0)
