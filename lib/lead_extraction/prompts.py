"""
Prompts d'extraction de données structurées depuis du texte libre.
Adapté depuis LEAD_QUALIFIER_SCORING_PROMPT (config/prompts.py) pour accepter
des transcriptions d'appels (Whisper) et pas seulement des échanges Q/A.
"""

EXTRACTION_PROMPT = """Analyse le texte suivant (conversation SMS, transcription d'appel, ou échange quelconque)
et extrais les informations de qualification immobilière.

TEXTE À ANALYSER :
{text}

RÈGLES D'EXTRACTION :
- Si une info n'est pas mentionnée dans le texte, retourne null pour ce champ
- Ne déduis pas ce qui n'est pas explicitement dit
- Pour le score : utilise les critères ci-dessous strictement

CRITÈRES DE SCORE :
Urgence (0-4 pts) :
  délai < 3 mois = 4 pts | 3-6 mois = 2 pts | > 6 mois = 1 pt | non mentionné = 0 pt

Budget qualifié (0-3 pts) :
  accord bancaire = 3 pts | apport > 20% = 2 pts | apport < 20% = 1 pt | non mentionné = 0 pt

Motivation (0-3 pts) :
  divorce/mutation/séparation = 3 pts | héritage/retraite = 2 pts | projet vague = 1 pt | non mentionné = 0 pt

Retourne UNIQUEMENT un JSON valide :
{{
  "score_total": <entier 0-10>,
  "score_urgence": <entier 0-4>,
  "score_budget": <entier 0-3>,
  "score_motivation": <entier 0-3>,
  "projet": "<achat|vente|location|estimation|null>",
  "localisation": "<ville ou zone détectée, ou null>",
  "budget": "<montant en string, ou null>",
  "timeline": "<délai en string, ou null>",
  "financement": "<situation financement, ou null>",
  "motivation": "<motivation profonde, ou null>",
  "prochaine_action": "<rdv|nurturing_14j|nurturing_30j>",
  "resume": "<résumé du profil en 1-2 phrases>"
}}

Ne retourne rien d'autre que ce JSON."""
