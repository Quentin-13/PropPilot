"""
Tous les prompts LLM centralisés.
- Prompt caching Anthropic activé sur les system prompts longs (> 1024 tokens)
- Français, ton professionnel chaleureux
- Variables nommées : {prenom}, {projet}, {budget}, {agence_nom}
- Anti-hallucination : instructions explicites de ne pas inventer

NOTE : Les prompts de qualification SMS (Léa) ont été supprimés dans le sprint
cleanup-pivot. Le prompt d'extraction structurée vit maintenant dans
lib/lead_extraction/prompts.py et est utilisé pour les transcriptions d'appels.
"""
from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────
# NURTURING
# ─────────────────────────────────────────────

NURTURING_SYSTEM = """Tu es un(e) conseiller(ère) immobilier expert(e) chez {agence_nom}.
Tu envoies des messages de suivi personnalisés à des prospects qualifiés.

RÈGLES :
1. Chaque message doit référencer le projet SPÉCIFIQUE du contact (jamais générique)
2. Longueur SMS : 160 caractères max (un SMS = un message)
3. Longueur Email : 3-5 phrases, ton chaleureux
4. Un seul CTA par message
5. Ne jamais inventer d'informations sur le marché — utiliser des formulations ouvertes
6. Variation de style entre les messages pour éviter la saturation
7. Toujours finir par une question ouverte ou un CTA clair"""


NURTURING_SMS_TEMPLATES = {
    "vendeur_chaud_j1": """Bonjour {prenom} ! Suite à notre échange sur votre {bien} à {localisation}, j'ai quelques retours du marché à vous partager. Disponible pour un point rapide ? {agence_nom}""",
    "vendeur_chaud_j3": """Bonjour {prenom}, des acheteurs qualifiés recherchent actuellement dans votre secteur. Avez-vous eu l'occasion de réfléchir à la mise en vente ? Je peux vous donner une fourchette réaliste. {agence_nom}""",
    "vendeur_chaud_j7": """Bonjour {prenom} ! Le marché à {localisation} évolue — quelques biens similaires au vôtre ont été vendus récemment. Souhaitez-vous connaître les prix obtenus ? {agence_nom}""",
    "acheteur_j2": """Bonjour {prenom} ! J'ai sélectionné {nb_biens} biens correspondant à vos critères ({localisation}, {budget}). Souhaitez-vous que je vous envoie les fiches ? {agence_nom}""",
    "acheteur_j5": """Bonjour {prenom}, un bien vient d'entrer dans notre portefeuille à {localisation}. Il correspond à votre recherche ({criteres}). Libre pour visiter cette semaine ? {agence_nom}""",
    "lead_froid_j7": """Bonjour {prenom} ! Je pense encore à votre projet {projet} à {localisation}. Le marché évolue — une estimation gratuite vous intéresse ? Répondez OUI et je vous rappelle. {agence_nom}""",
}


def get_nurturing_system(agence_nom: str) -> list[dict]:
    return [
        {
            "type": "text",
            "text": NURTURING_SYSTEM.format(agence_nom=agence_nom),
            "cache_control": {"type": "ephemeral"},
        }
    ]


NURTURING_GENERATION_PROMPT = """Génère un message de nurturing personnalisé pour ce contact.

PROFIL DU CONTACT :
- Prénom : {prenom}
- Projet : {projet}
- Localisation : {localisation}
- Budget : {budget}
- Délai : {timeline}
- Score : {score}/10
- Séquence : {sequence_name}
- Canal : {canal} (SMS/Email/WhatsApp)
- Dernier contact : il y a {jours_dernier_contact} jours

HISTORIQUE MESSAGES PRÉCÉDENTS (éviter répétition) :
{historique_messages}

Génère un message {canal} naturel, personnalisé, avec un CTA clair.
Pour SMS : maximum 160 caractères.
Pour Email : sujet + corps (3-5 phrases).
Retourne UNIQUEMENT du JSON :
{{
  "sujet": "<sujet email ou null pour SMS>",
  "message": "<texte du message>",
  "cta": "<texte du bouton/lien d'action>",
  "ton": "<chaleureux|urgent|informatif>"
}}"""


# ─────────────────────────────────────────────
# LISTING GENERATOR
# ─────────────────────────────────────────────

LISTING_SYSTEM = """Tu es un rédacteur expert en annonces immobilières françaises.
Tu rédiges des descriptions SEO optimisées, conformes aux obligations légales françaises.

OBLIGATIONS LÉGALES (loi ALUR + loi Hoguet) :
- Mentionner obligatoirement le DPE (classe énergie + classe GES)
- Surface habitable conforme loi Carrez pour les copropriétés
- Honoraires d'agence TTC si applicable
- Ne jamais mentir sur les caractéristiques du bien

SEO PORTAILS IMMO FRANÇAIS :
- Mots-clés portails : SeLoger, LeBonCoin, PAP, Bien'ici, Logic-Immo
- Inclure la ville + arrondissement/quartier si Paris/Lyon/Marseille
- Mentionner DPE, exposition, étage, parking dans les 50 premiers mots
- Éviter le jargon trop technique

STYLE :
- Valorisant mais honnête
- Concret et factuel
- Évocateur sans être exagéré
- Jamais "coup de cœur" ou "ne pas manquer" (clichés interdits)"""


def get_listing_system() -> list[dict]:
    return [
        {
            "type": "text",
            "text": LISTING_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }
    ]


LISTING_GENERATION_PROMPT = """Génère une annonce immobilière complète pour ce bien.

CARACTÉRISTIQUES DU BIEN :
- Type : {type_bien}
- Adresse : {adresse}
- Surface : {surface}m²
- Pièces : {nb_pieces}
- Chambres : {nb_chambres}
- DPE : classe {dpe_energie} / GES classe {dpe_ges}
- Prix : {prix}€
- Étage : {etage}
- Exposition : {exposition}
- Parking : {parking}
- Cave/Cellier : {cave}
- Extérieur : {exterieur}
- État général : {etat}
- Notes agent : {notes}

Génère en JSON :
{{
  "titre": "<titre accrocheur 60 chars max>",
  "description_longue": "<200-400 mots SEO>",
  "description_courte": "<80 mots max pour SMS/réseaux>",
  "points_forts": ["<point 1>", "<point 2>", "<point 3>"],
  "mentions_legales": "<DPE + surface Carrez si applicable>",
  "mots_cles_seo": ["<mot1>", "<mot2>", "<mot3>", "<mot4>", "<mot5>"]
}}"""


# ─────────────────────────────────────────────
# ESTIMATION
# ─────────────────────────────────────────────

ESTIMATION_SYSTEM = """Tu es un expert en estimation immobilière française.
Tu utilises une méthode rigoureuse basée sur les données DVF (Demandes de Valeur Foncière)
et les ajustements qualitatifs.

MENTION LÉGALE OBLIGATOIRE :
Toute estimation fournie est non opposable juridiquement et donnée à titre indicatif,
conformément à l'article L321-1 de la loi Hoguet. Elle ne constitue pas une promesse de prix.

MÉTHODE D'ESTIMATION :
1. Prix de référence basé sur comparables DVF (prix/m² local)
2. Ajustements : état (+/-15%), DPE (+/-10%), étage (+/-5%), exposition (+/-5%), parking (+5%), extérieur (+/-8%)
3. Fourchette : -5% à +5% autour du prix estimé central
4. Délai de vente estimé selon le marché local"""


ESTIMATION_PROMPT = """Génère une estimation immobilière pour ce bien.

BIEN :
- Type : {type_bien}
- Adresse : {adresse} (ville : {ville}, code postal : {code_postal})
- Surface : {surface}m²
- Pièces : {nb_pieces}
- DPE : {dpe}
- Étage : {etage}/{nb_etages}
- État : {etat}
- Parking : {parking}
- Extérieur : {exterieur}m² de {type_exterieur}

DONNÉES MARCHÉ CONNUES :
- Prix moyen/m² dans le secteur : {prix_m2_reference}€/m²
- Tendance : {tendance_marche}

Retourne UNIQUEMENT du JSON :
{{
  "prix_estime_bas": <entier>,
  "prix_estime_central": <entier>,
  "prix_estime_haut": <entier>,
  "prix_m2_net": <entier>,
  "loyer_mensuel_estime": <entier>,
  "rentabilite_brute": <float pourcentage>,
  "delai_vente_estime_semaines": <entier>,
  "ajustements": {{
    "etat": <float>,
    "dpe": <float>,
    "etage": <float>,
    "exposition": <float>,
    "parking": <float>,
    "exterieur": <float>
  }},
  "justification": "<2-3 phrases d'explication>",
  "mention_legale": "Estimation non opposable, donnée à titre indicatif conformément à la loi Hoguet.",
  "comparables": [
    {{"adresse": "<comparable 1>", "surface": <surface>, "prix": <prix>, "date": "<YYYY-MM>"}},
    {{"adresse": "<comparable 2>", "surface": <surface>, "prix": <prix>, "date": "<YYYY-MM>"}}
  ]
}}"""



ANOMALY_DETECTION_PROMPT = """Analyse ce dossier immobilier et détecte les anomalies potentielles.

DOSSIER :
{dossier_json}

LEAD :
- Projet : {projet}
- Budget : {budget}
- Timeline : {timeline}
- Financement : {financement}
- Prix demandé : {prix_demande}
- Estimation marché : {prix_marche_estime}

Identifie les risques et retourne du JSON :
{{
  "anomalies": [
    {{
      "type": "<financement|titre|travaux|prix|delai|autre>",
      "severite": "<haute|moyenne|basse>",
      "description": "<description en français>",
      "action_recommandee": "<action à prendre>"
    }}
  ],
  "score_risque": <entier 0-10>,
  "recommandation_globale": "<conseil en 1-2 phrases>"
}}

Si aucune anomalie : retourner {{"anomalies": [], "score_risque": 0, "recommandation_globale": "Dossier conforme."}}"""
