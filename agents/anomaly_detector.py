"""
AnomalyDetectorAgent — Détection anomalies dossier notaire, financement, prix marché.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from config.prompts import ANOMALY_DETECTION_PROMPT
from config.settings import get_settings
from memory.lead_repository import get_lead
from memory.models import Lead

logger = logging.getLogger(__name__)

# Seuils de détection
PRICE_DEVIATION_THRESHOLD = 0.30    # ±30% vs marché
SHORT_TIMELINE_DAYS = 45            # Délai court sans financement
MIN_APPORT_PCT = 0.10               # Apport minimum recommandé 10%


class AnomalyDetectorAgent:
    """
    Détecte les anomalies dans les dossiers immobiliers :
    - Financement insuffisant ou absent avec timeline court
    - Documents manquants (titre propriété, syndic)
    - Incohérences prix vs marché (±30%)
    - Risque dépassement délai notaire
    - Travaux non déclarés potentiels
    """

    def __init__(self, client_id: str, tier: str = "Starter"):
        self.client_id = client_id
        self.tier = tier
        self.settings = get_settings()
        self._anthropic_client = None

    def _get_anthropic(self):
        if self._anthropic_client is None and self.settings.anthropic_available:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._anthropic_client

    def analyze_lead_dossier(
        self,
        lead_id: str,
        prix_marche_estime: Optional[float] = None,
        dossier_supplementaire: Optional[dict] = None,
    ) -> dict:
        """
        Analyse complète du dossier d'un lead pour détecter les anomalies.

        Args:
            lead_id: ID du lead à analyser
            prix_marche_estime: Estimation marché pour comparaison (optionnel)
            dossier_supplementaire: Données supplémentaires (docs fournis, etc.)

        Returns:
            {
                "anomalies": list[dict],
                "score_risque": int,          # 0-10
                "recommandation_globale": str,
                "alertes_critiques": list,    # anomalies haute sévérité
                "peut_signer_mandat": bool,   # recommandation agent
            }
        """
        lead = get_lead(lead_id)
        if not lead:
            return {"anomalies": [], "score_risque": 0, "recommandation_globale": "Lead introuvable"}

        # Détection heuristique rapide
        anomalies_heuristic = self._heuristic_detection(lead, prix_marche_estime)

        # Analyse LLM si disponible
        if self.settings.anthropic_available:
            anomalies_llm = self._llm_detection(lead, prix_marche_estime, dossier_supplementaire)
            # Fusion sans doublons
            all_anomalies = self._merge_anomalies(anomalies_heuristic, anomalies_llm)
        else:
            all_anomalies = anomalies_heuristic

        score_risque = self._compute_risk_score(all_anomalies)
        alertes_critiques = [a for a in all_anomalies if a.get("severite") == "haute"]
        peut_signer = score_risque < 6 and len(alertes_critiques) == 0

        recommandation = self._build_recommandation(score_risque, alertes_critiques, lead)

        return {
            "lead_id": lead_id,
            "anomalies": all_anomalies,
            "score_risque": score_risque,
            "recommandation_globale": recommandation,
            "alertes_critiques": alertes_critiques,
            "peut_signer_mandat": peut_signer,
            "nb_anomalies": len(all_anomalies),
            "nb_critiques": len(alertes_critiques),
        }

    def analyze_dossier_dict(
        self,
        dossier: dict,
        prix_marche_estime: Optional[float] = None,
    ) -> dict:
        """
        Analyse un dossier fourni directement (sans lead en base).
        Utile pour l'analyse ad-hoc depuis le dashboard.

        Args:
            dossier: {
                "projet": str,
                "budget": float,
                "prix_demande": float,
                "timeline_jours": int,
                "financement": str,
                "documents": list,
                "travaux_declares": bool,
                "syndic_contacte": bool,
                "titre_propriete": bool,
                ...
            }
        """
        anomalies = []

        # --- Financement ---
        budget = dossier.get("budget", 0)
        timeline = dossier.get("timeline_jours", 999)
        financement = dossier.get("financement", "").lower()
        apport_pct = dossier.get("apport_pct", 0)

        if not any(kw in financement for kw in ["accord", "validé", "obtenu", "propre", "fonds"]):
            if timeline < SHORT_TIMELINE_DAYS:
                anomalies.append({
                    "type": "financement",
                    "severite": "haute",
                    "description": f"Pas d'accord de financement confirmé avec un délai de seulement {timeline} jours. Risque élevé de caducité.",
                    "action_recommandee": "Exiger un accord de principe bancaire avant signature du compromis.",
                })
            elif timeline < 90:
                anomalies.append({
                    "type": "financement",
                    "severite": "moyenne",
                    "description": "Financement non confirmé avec délai serré.",
                    "action_recommandee": "Demander une simulation bancaire récente.",
                })

        if apport_pct > 0 and apport_pct < MIN_APPORT_PCT * 100:
            anomalies.append({
                "type": "financement",
                "severite": "moyenne",
                "description": f"Apport faible ({apport_pct:.0f}% < 10% recommandé). Les banques peuvent refuser.",
                "action_recommandee": "Vérifier la capacité d'emprunt réelle avec simulation bancaire.",
            })

        # --- Prix vs marché ---
        prix_demande = dossier.get("prix_demande", 0)
        if prix_demande > 0 and prix_marche_estime and prix_marche_estime > 0:
            deviation = abs(prix_demande - prix_marche_estime) / prix_marche_estime
            if deviation > PRICE_DEVIATION_THRESHOLD:
                direction = "surévalué" if prix_demande > prix_marche_estime else "sous-évalué"
                anomalies.append({
                    "type": "prix",
                    "severite": "haute" if deviation > 0.40 else "moyenne",
                    "description": f"Prix demandé {direction} de {deviation:.0%} vs estimation marché ({prix_marche_estime:,.0f}€).",
                    "action_recommandee": f"Proposer un ajustement entre {int(prix_marche_estime * 0.95):,}€ et {int(prix_marche_estime * 1.05):,}€.",
                })

        # --- Documents ---
        if not dossier.get("titre_propriete", True):
            anomalies.append({
                "type": "titre",
                "severite": "haute",
                "description": "Titre de propriété non vérifié ou manquant.",
                "action_recommandee": "Demander au vendeur son acte de propriété ou contacter le notaire.",
            })

        if not dossier.get("syndic_contacte", True) and dossier.get("en_copropriete", False):
            anomalies.append({
                "type": "document",
                "severite": "moyenne",
                "description": "Copropriété : syndic non contacté — charges et procédures inconnues.",
                "action_recommandee": "Obtenir l'état daté du syndic et les 3 derniers PV d'AG.",
            })

        if not dossier.get("travaux_declares", True):
            anomalies.append({
                "type": "travaux",
                "severite": "moyenne",
                "description": "Travaux non déclarés potentiels détectés dans la description.",
                "action_recommandee": "Demander les permis de construire, déclarations préalables et certificats de conformité.",
            })

        # --- Délai notaire ---
        delai_notaire = dossier.get("delai_notaire_jours", 90)
        conditions_complexes = dossier.get("conditions_complexes", False)
        if delai_notaire < 75 and conditions_complexes:
            anomalies.append({
                "type": "delai",
                "severite": "moyenne",
                "description": f"Délai notaire serré ({delai_notaire} jours) avec conditions complexes. Risque de prorogation.",
                "action_recommandee": "Prévoir clause de prorogation de 15 jours dans le compromis.",
            })

        score_risque = self._compute_risk_score(anomalies)
        alertes_critiques = [a for a in anomalies if a.get("severite") == "haute"]

        return {
            "anomalies": anomalies,
            "score_risque": score_risque,
            "recommandation_globale": self._build_recommandation(score_risque, alertes_critiques),
            "alertes_critiques": alertes_critiques,
            "peut_signer_mandat": score_risque < 6 and not alertes_critiques,
            "nb_anomalies": len(anomalies),
            "nb_critiques": len(alertes_critiques),
        }

    def _heuristic_detection(
        self, lead: Lead, prix_marche_estime: Optional[float]
    ) -> list[dict]:
        """Détection rapide par règles métier sans LLM."""
        anomalies = []
        financement = lead.financement.lower() if lead.financement else ""
        timeline = lead.timeline.lower() if lead.timeline else ""
        budget_str = lead.budget

        # Financement sans accord + délai court
        has_accord = any(kw in financement for kw in ["accord", "validé", "obtenu", "propres", "fonds"])
        is_urgent = any(kw in timeline for kw in ["urgent", "mois", "semaine", "juin", "juillet", "août"])

        if not has_accord and is_urgent and lead.projet.value == "achat":
            anomalies.append({
                "type": "financement",
                "severite": "haute",
                "description": "Projet d'achat urgent sans accord de financement confirmé.",
                "action_recommandee": "Vérifier la capacité de financement avant de rechercher des biens.",
            })

        # Score élevé mais financement faible
        if lead.score >= 7 and lead.score_budget <= 1:
            anomalies.append({
                "type": "financement",
                "severite": "moyenne",
                "description": "Lead très motivé mais financement à consolider.",
                "action_recommandee": "Orienter vers un courtier ou simulateur bancaire en priorité.",
            })

        # Prix vs marché
        if prix_marche_estime and budget_str:
            try:
                budget_num = float("".join(c for c in budget_str if c.isdigit() or c == "."))
                deviation = abs(budget_num - prix_marche_estime) / prix_marche_estime
                if deviation > PRICE_DEVIATION_THRESHOLD:
                    direction = "bien supérieur" if budget_num > prix_marche_estime else "bien inférieur"
                    anomalies.append({
                        "type": "prix",
                        "severite": "moyenne",
                        "description": f"Budget annoncé {direction} au marché ({deviation:.0%} d'écart).",
                        "action_recommandee": "Recadrer les attentes sur les prix actuels du marché local.",
                    })
            except (ValueError, ZeroDivisionError):
                pass

        return anomalies

    def _llm_detection(
        self, lead: Lead, prix_marche_estime: Optional[float], dossier: Optional[dict]
    ) -> list[dict]:
        """Analyse LLM pour détecter anomalies plus subtiles."""
        client = self._get_anthropic()
        if not client:
            return []

        dossier_json = json.dumps({
            "projet": lead.projet.value,
            "localisation": lead.localisation,
            "budget": lead.budget,
            "timeline": lead.timeline,
            "financement": lead.financement,
            "motivation": lead.motivation,
            "score": lead.score,
            "notes_agent": lead.notes_agent,
            **(dossier or {}),
        }, ensure_ascii=False)

        prompt = ANOMALY_DETECTION_PROMPT.format(
            dossier_json=dossier_json,
            projet=lead.projet.value,
            budget=lead.budget or "non précisé",
            timeline=lead.timeline or "non précisé",
            financement=lead.financement or "non précisé",
            prix_demande=lead.budget or "non précisé",
            prix_marche_estime=f"{prix_marche_estime:,.0f}€" if prix_marche_estime else "non fourni",
        )

        try:
            from memory.cost_logger import log_api_action
            response = client.messages.create(
                model=self.settings.claude_model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            log_api_action(
                client_id=self.client_id,
                action_type="lead",
                provider="anthropic",
                model=self.settings.claude_model,
                tokens_input=response.usage.input_tokens,
                tokens_output=response.usage.output_tokens,
            )

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            return data.get("anomalies", [])

        except Exception as e:
            logger.warning(f"Erreur LLM anomaly detection : {e}")
            return []

    def _merge_anomalies(self, heuristic: list, llm: list) -> list:
        """Fusionne sans doublons par type."""
        result = list(heuristic)
        existing_types = {a["type"] for a in heuristic}
        for anomaly in llm:
            if anomaly.get("type") not in existing_types:
                result.append(anomaly)
        return result

    def _compute_risk_score(self, anomalies: list) -> int:
        """Calcule le score de risque 0-10 selon les anomalies."""
        score = 0
        for anomaly in anomalies:
            sev = anomaly.get("severite", "basse")
            score += {"haute": 3, "moyenne": 2, "basse": 1}.get(sev, 1)
        return min(10, score)

    def _build_recommandation(
        self, score: int, critiques: list, lead: Optional[Lead] = None
    ) -> str:
        if score == 0:
            return "Dossier conforme — aucune anomalie détectée. Vous pouvez procéder à la signature du mandat."
        elif score <= 3:
            nb = len(critiques)
            return f"Dossier globalement sain — {len(critiques)} point(s) mineur(s) à clarifier avant signature."
        elif score <= 6:
            return (
                f"Dossier à risque modéré — {len(critiques)} alerte(s) haute(s). "
                f"Résoudre les points critiques avant de signer le compromis."
            )
        else:
            return (
                f"ATTENTION — Dossier à risque élevé (score {score}/10). "
                f"Ne pas signer sans résolution des {len(critiques)} anomalie(s) critique(s). "
                f"Consulter un notaire avant toute démarche contractuelle."
            )
