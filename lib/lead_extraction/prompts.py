"""
Prompts d'extraction de données structurées depuis du texte libre.
Deux grilles de scoring distinctes : acheteur/locataire et vendeur.
Score normalisé sur 24 points, axes 0-3 chacun.
"""

# ── Instructions scoring partagées (importées par call/SMS pipelines) ─────────
SCORING_INSTRUCTIONS = """
DÉTECTION DU TYPE DE LEAD (obligatoire, fait AVANT le scoring) :
- "acheteur" : cherche à acheter un bien
- "vendeur"  : veut vendre ou faire estimer son bien
- "locataire": cherche un logement à louer
- Si le lead veut VENDRE pour RACHETER : is_ambiguous = true, lead_type = "vendeur" principal

────────────────────────────────────────────────────────────────
GRILLE ACHETEUR / LOCATAIRE — 4 axes, chacun noté 0-3
────────────────────────────────────────────────────────────────
score_urgence (poids ×3 dans le total)
  3 : vraie deadline = mutation pro, bail qui se termine, compromis signé ailleurs,
      "dès que possible", "avant l'été", "avant la rentrée", "urgent"
  2 : délai réel mais flexible (ex. "dans 3 mois")
  1 : horizon vague (ex. "dans 6 mois")
  0 : pas de timeline mentionnée

score_capacite_fin (poids ×2) — financement CRÉDIBLE, pas juste un budget
  3 : prêt accordé, vente du bien actuel en cours, cash disponible
  2 : apport clair > 20 %, accord bancaire en cours
  1 : apport faible ou "je verrai pour le financement"
  0 : aucune mention de financement

score_engagement (poids ×2) — comportement actif
  3 : a déjà visité des biens, comparé des agences, demandé un bien précis,
      pose des questions techniques (DPE, copropriété, travaux)
  2 : a commencé à regarder activement, a contacté une autre agence
  1 : premier contact, curiosité passive
  0 : aucun signe d'engagement

score_motivation (poids ×1) — raison d'acheter
  3 : vie forte : divorce, naissance, mutation pro, succession
  2 : investissement opportuniste avec intention claire
  1 : projet vague, "on réfléchit"
  0 : inconnue

────────────────────────────────────────────────────────────────
GRILLE VENDEUR — 4 axes, chacun noté 0-3
────────────────────────────────────────────────────────────────
score_urgence (poids ×3)
  3 : succession à régler, divorce, mutation, déjà acheté ailleurs,
      deadline notariale, "doit vendre dans les 3 mois"
  2 : veut vendre dans les 6 mois avec raison réelle
  1 : envisage de vendre "à terme"
  0 : pas de timing mentionné

score_maturite (poids ×3) — projet de vente avancé = mandat potentiel
  3 : a déjà fait estimer, a un prix en tête, a contacté d'autres agences,
      a publié sur LBC/SeLoger, veut signer rapidement
  2 : a pris la décision de vendre (ex. "on doit vendre"), prêt à rencontrer l'agence
  1 : commence à réfléchir, pas encore décidé
  0 : curiosité pure ("juste pour info", "juste pour savoir combien ça vaut")

score_qualite_bien (poids ×2) — bien attractif et propriétaire ouvert à l'exclusivité
  3 : bien attractif (maison, grand appart, bonne zone), propriétaire mentionne exclusivité
  2 : bien standard, zone correcte
  1 : bien difficile (travaux importants, mauvaise zone, prix déconnecté marché)
  0 : aucune info sur le bien

score_motivation (poids ×1)
  3 : vie forte : héritage, divorce, mutation, séparation
  2 : retraite, déménagement choisi
  1 : opportuniste
  0 : floue ou inconnue

────────────────────────────────────────────────────────────────
RÈGLE CRITIQUE — redistribution des axes inconnus
────────────────────────────────────────────────────────────────
Si une info est VRAIMENT absente (non déductible du texte), note l'axe null.
Le calcul du score normalisera automatiquement sur les axes connus.
Ne mets JAMAIS 0 pour "info absente" — 0 signifie "info présente et mauvaise".
null signifie "info absente".
"""

# ── Exemples few-shot ──────────────────────────────────────────────────────────
_FEW_SHOT_EXAMPLES = """
════════════════════════════════════════════════════
EXEMPLES — lire attentivement avant de scorer
════════════════════════════════════════════════════

[EXEMPLE 1 — ACHETEUR CHAUD]
Texte : "Bonjour, je m'appelle Marc. Je cherche un T3 à Lyon 6e, budget 380-420k€.
J'ai mon accord de prêt depuis la semaine dernière. J'ai déjà visité 4 biens
avec une autre agence mais rien ne me convenait. Je dois être installé avant
septembre, mutation pro à Lyon."

Scoring attendu :
- lead_type : acheteur
- score_urgence : 3 (mutation pro + deadline septembre)
- score_capacite_fin : 3 (accord de prêt obtenu)
- score_engagement : 3 (4 visites, autre agence)
- score_motivation : 3 (mutation professionnelle)
- score_total : 24/24 → CHAUD

────────────────────────────────────────────────────
[EXEMPLE 2 — ACHETEUR FROID (piège : tout rempli mais pas urgent)]
Texte : "Bonsoir, je cherche une maison en région parisienne, budget 600k€.
Nous avons un apport de 30%. On a visité quelques maisons il y a 6 mois.
On se donne 2 ans pour trouver, pas de pression."

Scoring attendu :
- lead_type : acheteur
- score_urgence : 0 (2 ans, "pas de pression" = pas de timeline réelle)
- score_capacite_fin : 2 (apport 30%)
- score_engagement : 1 (visites il y a 6 mois = passé, passivité actuelle)
- score_motivation : 1 (projet vague, pas de raison de vie)
- score_total : 3×0 + 2×2 + 2×1 + 1×1 = 7 → normalisé ≈ 7/24 → FROID

────────────────────────────────────────────────────
[EXEMPLE 3 — VENDEUR CHAUD]
Texte : "Bonjour, suite au décès de mon père j'hérite de sa maison à Toulouse
Saint-Cyprien, 4 pièces 95m². Avec mes frères on doit la vendre dans les 3 mois
pour régler la succession. J'ai déjà eu une estimation d'une autre agence à 320k.
Je voudrais comparer et si vous êtes bien, signer rapidement."

Scoring attendu :
- lead_type : vendeur
- score_urgence : 3 (succession + deadline 3 mois)
- score_maturite : 3 (estimation faite, prêt à signer)
- score_qualite_bien : 2 (maison 95m² Saint-Cyprien = bien standard/bon)
- score_motivation : 3 (héritage/succession)
- score_total : 3×3 + 3×3 + 2×2 + 1×3 = 9+9+4+3 = 25 → normalisé 24/24 → CHAUD

────────────────────────────────────────────────────
[EXEMPLE 4 — VENDEUR FROID (piège : veut juste une estimation)]
Texte : "Bonjour, j'aimerais avoir une idée de la valeur de mon appartement
T2 à Nantes. Pas forcément envie de vendre maintenant, juste pour info.
Ça fait 10 ans que je l'ai acheté, je me demande si ça a pris de la valeur."

Scoring attendu :
- lead_type : vendeur
- score_urgence : 0 (pas de timeline)
- score_maturite : 0 ("juste pour info", pas de décision de vendre)
- score_qualite_bien : 1 (T2 Nantes = bien standard, infos limitées)
- score_motivation : 0 (curiosité, aucune motivation de vente réelle)
- score_total : 0+0+2+0 = 2 → normalisé ≈ 2/24 → FROID

────────────────────────────────────────────────────
[EXEMPLE 5 — LOCATAIRE CHAUD]
Texte : "Bonjour, je cherche un appartement à louer à Bordeaux Chartrons,
T2 ou T3, max 900€ charges comprises. Mon bail actuel se termine le 31 août,
j'ai besoin de trouver avant fin juillet. Je suis CDI depuis 3 ans, revenus 2800€/mois.
J'ai déjà visité 5 logements cette semaine."

Scoring attendu :
- lead_type : locataire
- score_urgence : 3 (bail qui se termine, deadline fin juillet)
- score_capacite_fin : 3 (CDI 3 ans, revenus stables 2800€ = profil solide)
- score_engagement : 3 (5 visites cette semaine)
- score_motivation : 3 (contrainte de bail = vie forte)
- score_total : 24/24 → CHAUD

────────────────────────────────────────────────────
[EXEMPLE 6 — CAS AMBIGU vendeur+acheteur]
Texte : "Bonjour, on veut vendre notre maison à Grenoble pour racheter
plus grand à Lyon. On est propriétaires depuis 8 ans, maison 4 pièces 110m².
On a une offre d'achat sur un bien à Lyon qu'on a acceptée sous condition
de vente de notre maison. Prix de vente souhaité 340k€."

Scoring attendu :
- lead_type : vendeur (priorité car blocage sur la vente)
- is_ambiguous : true
- linked_lead_hint : "Acheteur T4+ Lyon, budget ~340k€ après vente Grenoble"
- Vendeur : score_urgence=3, score_maturite=3, score_qualite_bien=2, score_motivation=2
- score_total vendeur ≈ CHAUD (offre acceptée = urgence maximale)
════════════════════════════════════════════════════
"""

# ── Prompt complet pour extract_lead_info (textes génériques) ─────────────────
EXTRACTION_PROMPT = """Analyse le texte suivant (conversation SMS, transcription d'appel, échange libre)
et extrais les informations de qualification immobilière.

TEXTE À ANALYSER :
{text}

RÈGLES D'EXTRACTION :
- Si une info n'est pas mentionnée dans le texte, retourne null pour ce champ
- Ne déduis pas ce qui n'est pas explicitement dit ou fortement sous-entendu
- Commence TOUJOURS par identifier le lead_type avant de scorer
""" + SCORING_INSTRUCTIONS + _FEW_SHOT_EXAMPLES + """

Retourne UNIQUEMENT un JSON valide (aucun texte avant ou après) :
{{
  "lead_type": "<acheteur|vendeur|locataire>",
  "score_urgence": <0-3 ou null>,
  "score_capacite_fin": <0-3 ou null — acheteur/locataire uniquement>,
  "score_engagement": <0-3 ou null — acheteur/locataire uniquement>,
  "score_maturite": <0-3 ou null — vendeur uniquement>,
  "score_qualite_bien": <0-3 ou null — vendeur uniquement>,
  "score_motivation": <0-3 ou null>,
  "is_ambiguous": <true|false>,
  "linked_lead_hint": "<description fiche liée si is_ambiguous, sinon null>",
  "projet": "<achat|vente|location|estimation|null>",
  "localisation": "<ville ou zone détectée, ou null>",
  "budget": "<montant en string, ou null>",
  "timeline": "<délai en string, ou null>",
  "financement": "<situation financement, ou null>",
  "motivation": "<motivation profonde en clair, ou null>",
  "prochaine_action": "<rdv|nurturing_14j|nurturing_30j>",
  "resume": "<résumé du profil en 1-2 phrases>"
}}"""
