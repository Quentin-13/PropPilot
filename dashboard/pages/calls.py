"""
Page Appels capturés — Liste paginée + détail avec audio, transcription et extraction.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import json
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st

from config.settings import get_settings
from dashboard.auth_ui import require_auth, render_sidebar_logout
from dashboard.utils.datetime_helpers import fmt_paris_datetime

settings = get_settings()

st.set_page_config(
    page_title="Appels capturés — PropPilot",
    layout="wide",
    page_icon="📞",
)

require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)

# ─── Header ───────────────────────────────────────────────────────────────────

st.title("📞 Appels capturés")
st.markdown("Tous les appels entrants et sortants capturés et analysés par PropPilot.")

# ─── Filtres ──────────────────────────────────────────────────────────────────

col_period, col_date, col_direction = st.columns([1.2, 2, 1])

with col_period:
    period = st.selectbox(
        "Période",
        ["Aujourd'hui", "7 derniers jours", "30 derniers jours", "Personnalisé"],
        key="calls_period",
    )

now = datetime.now()
since: Optional[datetime] = None
until: Optional[datetime] = None

if period == "Aujourd'hui":
    since = now.replace(hour=0, minute=0, second=0, microsecond=0)
elif period == "7 derniers jours":
    since = now - timedelta(days=7)
elif period == "30 derniers jours":
    since = now - timedelta(days=30)
else:
    with col_date:
        date_range = st.date_input(
            "Plage de dates",
            value=(now.date() - timedelta(days=30), now.date()),
            max_value=now.date(),
            key="calls_date_range",
        )
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        since = datetime.combine(date_range[0], datetime.min.time())
        until = datetime.combine(date_range[1], datetime.max.time())
    else:
        since = now - timedelta(days=30)

with col_direction:
    filter_direction = st.selectbox(
        "Direction",
        ["Tous", "Entrant", "Sortant"],
        key="calls_direction",
    )

# ─── Pagination ───────────────────────────────────────────────────────────────

PAGE_SIZE = 20
if "calls_page" not in st.session_state:
    st.session_state.calls_page = 0

# ─── Chargement données ───────────────────────────────────────────────────────

try:
    from memory.call_repository import get_calls_by_client, count_calls_by_client

    total = count_calls_by_client(client_id, since=since)
    calls_raw = get_calls_by_client(
        client_id=client_id,
        since=since,
        limit=PAGE_SIZE,
        offset=st.session_state.calls_page * PAGE_SIZE,
    )
except Exception as exc:
    st.error(
        f"Impossible de charger les appels : {exc}\n\n"
        "Vérifiez que la migration Sprint A a bien été appliquée : `alembic upgrade head`"
    )
    st.stop()

# Filtre direction côté Python
if filter_direction == "Entrant":
    calls_raw = [c for c in calls_raw if (c.get("direction") or "").lower() == "inbound"]
elif filter_direction == "Sortant":
    calls_raw = [c for c in calls_raw if (c.get("direction") or "").lower() == "outbound"]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt
    return fmt_paris_datetime(dt, "%d/%m/%Y %H:%M")


def _direction_label(direction: Optional[str]) -> str:
    d = (direction or "").lower()
    if d in ("inbound", "incoming"):
        return "⬇️ Entrant"
    if d in ("outbound", "outgoing"):
        return "⬆️ Sortant"
    return direction or "—"


def _status_label(call: dict) -> str:
    status = call.get("status") or call.get("statut") or "—"
    labels = {
        "initiated": "🔵 Initié",
        "ringing": "🟡 Sonnerie",
        "answered": "🟢 Décroché",
        "recorded": "🟢 Enregistré",
        "transcribed": "🟢 Transcrit",
        "extracted": "✅ Extrait",
        "completed": "✅ Terminé",
        "no_answer": "⚫ Sans réponse",
        "failed": "🔴 Échec",
        "voicemail": "📭 Messagerie",
        "abandoned_legal_notice": "⚫ Abandon",
        "transcription_failed": "🔴 Transcription échouée",
    }
    return labels.get(status, status)


def _score_label(score: Optional[str]) -> str:
    if not score:
        return "—"
    labels = {
        "chaud": "🔴 Chaud",
        "tiède": "🟠 Tiède",
        "froid": "🔵 Froid",
    }
    if score in labels:
        return labels[score]
    return score


def _lead_name(call: dict) -> str:
    prenom = call.get("prenom") or ""
    nom = call.get("nom") or ""
    name = f"{prenom} {nom}".strip()
    return name or call.get("from_number") or "—"


def _get_audio_url(recording_url: Optional[str]) -> Optional[str]:
    """Génère une URL signée B2 ou retourne l'URL directe."""
    if not recording_url or recording_url.startswith("https://mock-b2/"):
        return None
    if not settings.b2_available:
        return recording_url
    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=settings.b2_endpoint,
            aws_access_key_id=settings.b2_account_id,
            aws_secret_access_key=settings.b2_application_key,
            config=Config(signature_version="s3v4"),
        )
        bucket = settings.b2_bucket_name
        prefix = f"{settings.b2_endpoint}/{bucket}/"
        key = recording_url[len(prefix):] if recording_url.startswith(prefix) else recording_url.split("/")[-1]
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=3600,
        )
    except Exception:
        return recording_url


# ─── Compteur + pagination ────────────────────────────────────────────────────

total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
current_page = st.session_state.calls_page

col_count, col_nav_l, col_nav_info, col_nav_r = st.columns([3, 0.5, 1, 0.5])
with col_count:
    st.markdown(
        f"**{total} appel{'s' if total != 1 else ''}** sur la période"
        + (f" · page {current_page + 1}/{total_pages}" if total_pages > 1 else "")
    )
with col_nav_l:
    if st.button("◀ Préc.", disabled=(current_page == 0), key="calls_prev"):
        st.session_state.calls_page -= 1
        st.session_state.pop("calls_selected_idx", None)
        st.rerun()
with col_nav_r:
    if st.button("Suiv. ▶", disabled=(current_page >= total_pages - 1), key="calls_next"):
        st.session_state.calls_page += 1
        st.session_state.pop("calls_selected_idx", None)
        st.rerun()

# ─── Tableau ──────────────────────────────────────────────────────────────────

if not calls_raw:
    st.info(
        "Aucun appel trouvé pour cette période. "
        "Configurez votre numéro de téléphone dans **Paramètres** pour commencer à capturer des appels."
    )
    st.stop()

import pandas as pd

rows_display = []
for call in calls_raw:
    rows_display.append({
        "Date / Heure": _fmt_dt(call.get("started_at") or call.get("created_at")),
        "Direction": _direction_label(call.get("direction")),
        "Durée": _fmt_duration(call.get("duration_seconds")),
        "Lead": _lead_name(call),
        "Statut": _status_label(call),
        "Qualification": _score_label(call.get("score_qualification")),
        "_id": call.get("id", ""),
    })

df = pd.DataFrame(rows_display)
display_cols = ["Date / Heure", "Direction", "Durée", "Lead", "Statut", "Qualification"]

selection = st.dataframe(
    df[display_cols],
    use_container_width=True,
    hide_index=True,
    selection_mode="single-row",
    on_select="rerun",
    key="calls_table",
)

# ─── Panneau détail ───────────────────────────────────────────────────────────

selected_rows = selection.selection.rows if selection.selection else []
if not selected_rows:
    st.caption("Cliquez sur une ligne pour afficher le détail de l'appel.")
    st.stop()

idx = selected_rows[0]
call = calls_raw[idx]

st.markdown("---")
call_dt = _fmt_dt(call.get("started_at") or call.get("created_at"))
lead_name = _lead_name(call)
st.markdown(f"### 📋 Détail — {call_dt} · {lead_name}")

# Infos générales
info_col1, info_col2, info_col3, info_col4 = st.columns(4)
with info_col1:
    st.markdown(f"**Direction**\n\n{_direction_label(call.get('direction'))}")
with info_col2:
    st.markdown(f"**De**\n\n`{call.get('from_number') or '—'}`")
with info_col3:
    st.markdown(f"**Vers**\n\n`{call.get('to_number') or '—'}`")
with info_col4:
    st.markdown(f"**Durée**\n\n{_fmt_duration(call.get('duration_seconds'))}")

info2_col1, info2_col2, info2_col3 = st.columns(3)
with info2_col1:
    st.markdown(f"**Statut**\n\n{_status_label(call)}")
with info2_col2:
    mode = call.get("mode") or "—"
    mode_labels = {
        "dedicated_number": "Numéro dédié",
        "forwarded": "Renvoi d'appel",
        "outbound": "Appel sortant",
    }
    st.markdown(f"**Mode**\n\n{mode_labels.get(mode, mode)}")
with info2_col3:
    numéro_twilio = call.get("twilio_number") or "—"
    st.markdown(f"**Numéro**\n\n`{numéro_twilio}`")

# Bouton fiche lead
lead_id = call.get("lead_id")
if lead_id:
    if st.button("👤 Voir la fiche lead", key="btn_voir_lead"):
        st.session_state["selected_lead_id"] = lead_id
        st.switch_page("pages/01_mes_leads.py")

st.markdown("---")

# Audio
st.markdown("#### 🎵 Enregistrement")
recording_url = call.get("recording_url") or ""
if not recording_url or recording_url.startswith("https://mock-b2/"):
    st.info("Enregistrement audio non disponible (mock ou en cours de traitement).")
else:
    audio_url = _get_audio_url(recording_url)
    if audio_url:
        try:
            st.audio(audio_url, format="audio/mpeg")
        except Exception as e:
            st.warning(f"Impossible de lire l'audio : {e}")
            st.markdown(f"[Télécharger l'enregistrement]({audio_url})")
    else:
        st.info("Audio indisponible.")

# Transcription
st.markdown("#### 📝 Transcription")
transcript = call.get("transcript_text") or ""
if not transcript:
    status = call.get("status") or ""
    if status in ("initiated", "ringing", "answered", "recorded"):
        st.info("Transcription en cours de traitement…")
    elif status == "transcription_failed":
        st.error("La transcription a échoué (3 tentatives épuisées).")
    else:
        st.info("Aucune transcription disponible pour cet appel.")
else:
    st.text_area(
        "Transcription complète",
        value=transcript,
        height=200,
        disabled=True,
        key=f"transcript_{call.get('id', idx)}",
    )

# Extraction Claude
has_extraction = bool(call.get("score_qualification") or call.get("resume_appel"))

if has_extraction:
    st.markdown("#### 🧠 Données extraites par l'IA")

    ext_col1, ext_col2, ext_col3 = st.columns(3)

    with ext_col1:
        st.markdown("**Projet**")
        st.markdown(f"Type : {call.get('type_projet') or '—'}")
        st.markdown(f"Zone : {call.get('zone_geographique') or '—'}")
        st.markdown(f"Bien : {call.get('type_bien') or '—'}")

        bmin = call.get("budget_min")
        bmax = call.get("budget_max")
        if bmin or bmax:
            budget_str = ""
            if bmin:
                budget_str += f"{bmin:,} €".replace(",", " ")
            if bmin and bmax:
                budget_str += " — "
            if bmax:
                budget_str += f"{bmax:,} €".replace(",", " ")
            st.markdown(f"Budget : {budget_str}")
        else:
            st.markdown("Budget : —")

        smin = call.get("surface_min")
        smax = call.get("surface_max")
        if smin or smax:
            s_str = f"{smin or '?'} — {smax or '?'} m²"
            st.markdown(f"Surface : {s_str}")
        else:
            st.markdown("Surface : —")

    with ext_col2:
        st.markdown("**Situation**")
        st.markdown(f"Motivation : {call.get('motivation') or '—'}")

        timing = call.get("timing") or {}
        if isinstance(timing, dict) and timing:
            for k, v in timing.items():
                if v:
                    st.markdown(f"Timing — {k} : {v}")
        elif timing:
            st.markdown(f"Timing : {timing}")
        else:
            st.markdown("Timing : —")

        financement = call.get("financement") or {}
        if isinstance(financement, dict) and financement:
            for k, v in financement.items():
                if v:
                    st.markdown(f"Financement — {k} : {v}")
        elif financement:
            st.markdown(f"Financement : {financement}")
        else:
            st.markdown("Financement : —")

        criteres = call.get("criteres") or {}
        if isinstance(criteres, dict) and criteres:
            st.markdown("**Critères**")
            for k, v in criteres.items():
                if v:
                    st.markdown(f"• {k} : {v}")

    with ext_col3:
        st.markdown("**Qualification**")
        score = call.get("score_qualification")
        st.markdown(f"Score : {_score_label(score)}")

        next_action = call.get("prochaine_action_suggeree")
        if next_action:
            st.markdown(f"Prochaine action : *{next_action}*")

        points = call.get("points_attention") or []
        if points:
            st.markdown("**⚠️ Points d'attention**")
            if isinstance(points, list):
                for pt in points:
                    st.markdown(f"• {pt}")
            else:
                st.markdown(str(points))

    # Résumé IA
    resume = call.get("resume_appel") or ""
    if resume:
        st.markdown("#### 💬 Résumé IA")
        st.markdown(
            f'<div style="background:#1e2130;border-radius:8px;padding:16px;'
            f'border-left:4px solid #3b82f6;color:#e2e8f0;font-size:0.92rem;">'
            f"{resume}"
            f"</div>",
            unsafe_allow_html=True,
        )

else:
    status = call.get("status") or ""
    if status in ("initiated", "ringing", "answered", "recorded", "transcribed"):
        st.info("Extraction IA en cours de traitement…")
    elif status == "transcription_failed":
        pass  # message déjà affiché dans la section transcription
    else:
        st.caption("Aucune extraction disponible pour cet appel.")

# Pagination en bas
st.markdown("---")
col_bl, col_binfo, col_br = st.columns([1, 2, 1])
with col_bl:
    if st.button("◀ Page précédente", disabled=(current_page == 0), key="calls_prev_bottom"):
        st.session_state.calls_page -= 1
        st.session_state.pop("calls_selected_idx", None)
        st.rerun()
with col_binfo:
    st.markdown(
        f"<div style='text-align:center;color:#8892a4;'>Page {current_page + 1} / {total_pages}</div>",
        unsafe_allow_html=True,
    )
with col_br:
    if st.button("Page suivante ▶", disabled=(current_page >= total_pages - 1), key="calls_next_bottom"):
        st.session_state.calls_page += 1
        st.session_state.pop("calls_selected_idx", None)
        st.rerun()
