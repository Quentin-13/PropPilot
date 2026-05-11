"""
Calcul contextuel de la prochaine action recommandée pour un lead.

Prend en compte l'historique complet (SMS + appels), le silence depuis le dernier
contact, et le statut pipeline pour produire une action courte, actionnable, en
français naturel.

Cache anti-doublon : si la dernière action calculée date de moins de 30 minutes
ET qu'il n'y a pas eu de nouveau message depuis, on réutilise la précédente.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_TTL_MINUTES = 30
_CLAUDE_COST_INPUT_PER_TOKEN = 3e-6
_CLAUDE_COST_OUTPUT_PER_TOKEN = 15e-6


@dataclass
class NextAction:
    label: str                          # Court, actionnable, ≤ 80 car.
    priority: str                       # haute | moyenne | basse
    reason: str                         # Explication pour l'agent
    deadline: Optional[datetime]        # Date/heure limite suggérée
    from_cache: bool = False            # True si résultat mis en cache


def compute_next_action(lead_id: str) -> Optional[NextAction]:
    """
    Calcule (ou retourne depuis cache) la prochaine action pour ce lead.
    Retourne None si le lead n'existe pas ou si l'extraction échoue.
    Ne propage jamais d'exception.
    """
    try:
        lead_row = _fetch_lead(lead_id)
        if not lead_row:
            return None

        latest_activity = _latest_activity_at(lead_id)

        # Vérification cache
        computed_at = lead_row.get("next_action_computed_at")
        if _is_cached(computed_at, latest_activity):
            label = lead_row.get("next_action_label")
            if label:
                logger.debug("[NextAction] Cache hit lead_id=%s", lead_id)
                return NextAction(
                    label=label,
                    priority=lead_row.get("next_action_priority") or "moyenne",
                    reason=lead_row.get("next_action_reason") or "",
                    deadline=lead_row.get("next_action_deadline"),
                    from_cache=True,
                )

        # Calcul LLM
        action = _compute_via_llm(lead_row, lead_id)
        if action:
            _save_next_action(lead_id, action)
        return action

    except Exception as e:
        logger.error("[NextAction] compute_next_action lead_id=%s: %s", lead_id, e)
        return None


# ─── Récupération données ──────────────────────────────────────────────────────

def _fetch_lead(lead_id: str) -> Optional[dict]:
    from memory.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, client_id, prenom, nom, projet, score, statut, motivation,
                      next_action_label, next_action_priority, next_action_reason,
                      next_action_deadline, next_action_computed_at, created_at
               FROM leads WHERE id = ?""",
            (lead_id,),
        ).fetchone()
    return dict(row) if row else None


def _latest_activity_at(lead_id: str) -> Optional[datetime]:
    """Retourne la date du message le plus récent (conversations + calls)."""
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            row_conv = conn.execute(
                "SELECT MAX(created_at) as latest FROM conversations WHERE lead_id = ?",
                (lead_id,),
            ).fetchone()
            row_call = conn.execute(
                "SELECT MAX(started_at) as latest FROM calls WHERE lead_id = ?",
                (lead_id,),
            ).fetchone()

        dates = []
        for row in (row_conv, row_call):
            if row and row["latest"]:
                val = row["latest"]
                if isinstance(val, str):
                    val = datetime.fromisoformat(val)
                dates.append(val)

        return max(dates) if dates else None
    except Exception:
        return None


def _is_cached(computed_at, latest_activity) -> bool:
    if not computed_at:
        return False
    now = datetime.now()
    if isinstance(computed_at, str):
        computed_at = datetime.fromisoformat(computed_at)

    age_minutes = (now - computed_at).total_seconds() / 60
    if age_minutes > _CACHE_TTL_MINUTES:
        return False

    # Cache valide seulement si pas de nouvelle activité depuis le calcul
    if latest_activity:
        if isinstance(latest_activity, str):
            latest_activity = datetime.fromisoformat(latest_activity)
        # Rendre les deux tz-naïves pour la comparaison
        ca = computed_at.replace(tzinfo=None) if computed_at.tzinfo else computed_at
        la = latest_activity.replace(tzinfo=None) if latest_activity.tzinfo else latest_activity
        if la > ca:
            return False

    return True


# ─── Appel LLM ────────────────────────────────────────────────────────────────

def _compute_via_llm(lead_row: dict, lead_id: str) -> Optional[NextAction]:
    from config.settings import get_settings
    s = get_settings()

    if not s.anthropic_available or s.testing or s.mock_mode == "always":
        return _mock_action(lead_row)

    context = _build_context(lead_row, lead_id)
    prompt = _build_prompt(context)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        response = client.messages.create(
            model=s.claude_model,
            max_tokens=512,
            system=[{
                "type": "text",
                "text": (
                    "Tu es un expert en suivi commercial immobilier. "
                    "Tu analyses le contexte d'un lead et proposes UNE action concrète, "
                    "courte et actionnable pour l'agent immobilier. "
                    "Tu réponds UNIQUEMENT en JSON valide."
                ),
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        data = json.loads(raw)
        deadline = _parse_deadline(data.get("action_deadline_iso"))

        return NextAction(
            label=(data.get("action_label") or "")[:80],
            priority=(data.get("action_priority") or "moyenne").lower(),
            reason=data.get("action_reason") or "",
            deadline=deadline,
        )
    except Exception as e:
        logger.warning("[NextAction] LLM échoué lead_id=%s: %s", lead_id, e)
        return _mock_action(lead_row)


def _build_context(lead_row: dict, lead_id: str) -> dict:
    """Assemble toutes les données contextuelles pour le prompt."""
    score = lead_row.get("score") or 0
    score_label = "chaud" if score >= 18 else "tiède" if score >= 11 else "froid"

    conversations = []
    try:
        from memory.lead_repository import get_conversation_history
        convs = get_conversation_history(lead_id, limit=30)
        for c in convs:
            role = "Agent" if c.canal.value == "assistant" else "Prospect"
            if hasattr(c, "role"):
                role = "Agent" if c.role == "assistant" else "Prospect"
            created = c.created_at
            ts = created.strftime("%d/%m %H:%M") if created else ""
            conversations.append({"ts": ts, "role": role, "contenu": c.contenu[:300]})
    except Exception:
        pass

    calls_summary = []
    try:
        from memory.call_repository import get_calls_by_lead
        calls = get_calls_by_lead(lead_id)
        for call in calls[:5]:
            dur = call.get("duration_seconds") or 0
            resume = call.get("resume_appel") or ""
            started = call.get("started_at") or call.get("created_at")
            ts = started.strftime("%d/%m %H:%M") if isinstance(started, datetime) else str(started)[:16]
            calls_summary.append(f"[{ts}] Appel {dur//60}m — {resume[:200]}")
    except Exception:
        pass

    # Dernier contact agent → prospect
    last_agent_at = None
    last_prospect_at = None
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                """SELECT MAX(created_at) as latest FROM conversations
                   WHERE lead_id = ? AND role = 'assistant'""",
                (lead_id,),
            ).fetchone()
            if row and row["latest"]:
                last_agent_at = row["latest"]
            row2 = conn.execute(
                """SELECT MAX(created_at) as latest FROM conversations
                   WHERE lead_id = ? AND role = 'user'""",
                (lead_id,),
            ).fetchone()
            if row2 and row2["latest"]:
                last_prospect_at = row2["latest"]
    except Exception:
        pass

    now = datetime.now()
    silence_jours = None
    if last_agent_at:
        la = last_agent_at.replace(tzinfo=None) if hasattr(last_agent_at, "tzinfo") and last_agent_at.tzinfo else last_agent_at
        if isinstance(la, str):
            la = datetime.fromisoformat(la)
        silence_jours = (now - la).days

    return {
        "lead_id": lead_id,
        "prenom": lead_row.get("prenom") or "Prospect",
        "nom": lead_row.get("nom") or "",
        "type_projet": lead_row.get("projet") or "inconnu",
        "score_label": score_label,
        "score": score,
        "statut": lead_row.get("statut") or "entrant",
        "motivation": lead_row.get("motivation") or "",
        "created_at": lead_row.get("created_at"),
        "last_agent_at": last_agent_at,
        "last_prospect_at": last_prospect_at,
        "silence_jours": silence_jours,
        "conversations": conversations,
        "calls_summary": calls_summary,
    }


def _build_prompt(ctx: dict) -> str:
    conv_text = "\n".join(
        f"  [{m['ts']}] {m['role']} : {m['contenu']}"
        for m in ctx["conversations"][-20:]
    ) or "  (aucune conversation enregistrée)"

    calls_text = "\n".join(f"  {c}" for c in ctx["calls_summary"]) or "  (aucun appel)"

    silence_text = (
        f"{ctx['silence_jours']} jour(s) sans recontact de l'agent"
        if ctx["silence_jours"] is not None
        else "Délai inconnu"
    )

    return f"""Analyse ce lead immobilier et propose UNE action prioritaire pour l'agent.

PROFIL LEAD :
- Prénom/Nom : {ctx['prenom']} {ctx['nom']}
- Projet : {ctx['type_projet']}
- Score : {ctx['score_label']} ({ctx['score']}/24)
- Statut pipeline : {ctx['statut']}
- Motivation : {ctx['motivation'] or 'non précisée'}
- Silence depuis dernier contact agent : {silence_text}

CONVERSATIONS SMS (chronologique) :
{conv_text}

APPELS TÉLÉPHONIQUES :
{calls_text}

Réponds avec ce JSON exact (aucun texte autour) :
{{
  "action_label": "<Action courte ≤80 car, en français naturel, actionnable>",
  "action_priority": "<haute|moyenne|basse>",
  "action_reason": "<Explication 1 phrase — pourquoi cette action maintenant>",
  "action_deadline_iso": "<ISO 8601 ou null — ex: 2026-05-11T18:00:00+02:00>"
}}

Règles :
- action_label doit être une instruction directe à l'agent (ex: "Rappeler avant 18h", "Envoyer SMS de réactivation")
- haute = lead chaud non recontacté depuis > 24h OU silence > 48h OU urgence signalée
- moyenne = action utile mais pas critique
- basse = lead froid ou en nurturing long terme
- deadline seulement si pertinente (rappel urgent, délai évoqué par le prospect)"""


def _mock_action(lead_row: dict) -> NextAction:
    score = lead_row.get("score") or 0
    if score >= 18:
        return NextAction(
            label="Rappeler aujourd'hui — lead chaud sans suivi récent",
            priority="haute",
            reason="Score élevé, action urgente recommandée.",
            deadline=None,
        )
    if score >= 11:
        return NextAction(
            label="Envoyer un SMS de suivi avec une question ouverte",
            priority="moyenne",
            reason="Lead tiède, relance pour maintenir l'engagement.",
            deadline=None,
        )
    return NextAction(
        label="Mettre en séquence nurturing 30 jours",
        priority="basse",
        reason="Lead froid, pas d'action urgente.",
        deadline=None,
    )


# ─── Persistance ──────────────────────────────────────────────────────────────

def _save_next_action(lead_id: str, action: NextAction) -> None:
    try:
        from memory.database import get_connection
        deadline_iso = action.deadline.isoformat() if action.deadline else None
        with get_connection() as conn:
            conn.execute(
                """UPDATE leads SET
                       next_action_label = ?,
                       next_action_priority = ?,
                       next_action_reason = ?,
                       next_action_deadline = ?,
                       next_action_computed_at = NOW()
                   WHERE id = ?""",
                (action.label, action.priority, action.reason, deadline_iso, lead_id),
            )
    except Exception as e:
        logger.warning("[NextAction] _save_next_action lead_id=%s: %s", lead_id, e)


def _parse_deadline(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        # Convertir en tz-naïf pour stockage PostgreSQL sans timezone
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None
