"""
Script de configuration du compte démo Dumortier.
Crée l'utilisateur, 15 leads + 1 lead live, conversations SMS, RDVs.
Idempotent — exécutable plusieurs fois sans duplication.

Usage:
    python scripts/seed_demo_dumortier.py
"""
from __future__ import annotations

import sys
from pathlib import Path
import json
from datetime import datetime, timedelta
from uuid import uuid4

import bcrypt

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.database import init_database, get_connection
from memory.models import Canal, Lead, LeadStatus, NurturingSequence, ProjetType
from memory.lead_repository import create_lead, add_conversation_message

init_database()

# ─── Constantes démo ──────────────────────────────────────────────────────────

DEMO_USER_ID  = "demo-dumortier-gh-st-etienne"
DEMO_EMAIL    = "demo.dumortier@proppilot.fr"
DEMO_PASSWORD = "PropPilot2026!"
DEMO_AGENCY   = "Guy Hoquet Saint-Étienne Nord"
DEMO_FIRSTNAME = "Laurent"

# ─── Leads Saint-Étienne ──────────────────────────────────────────────────────

LEADS = [
    # ── Chauds : score 8-10 ───────────────────────────────────────────────────
    {
        "prenom": "Fabrice", "nom": "Dumoulin",
        "tel": "+33677001101", "email": "fabrice.dumoulin@gmail.com",
        "projet": "achat", "budget": "290 000€",
        "loc": "Saint-Priest-en-Jarez", "score": 9, "urgence": 4, "bud": 3, "mot": 2,
        "timeline": "Avant septembre 2026",
        "financement": "Accord de principe CIC, apport 30 000€",
        "motivation": "Jardin pour les enfants, arrêter de payer un loyer",
        "statut": LeadStatus.RDV_BOOKÉ, "source": Canal.SELOGER,
        "resume": "Famille de 4, locataire 6 ans. Financement solide, délai clair. RDV vendredi 14h.",
        "jours": 3, "has_conv": True, "has_rdv": True,
    },
    {
        "prenom": "Nathalie", "nom": "Veyret",
        "tel": "+33677001102", "email": "nathalie.veyret@orange.fr",
        "projet": "vente", "budget": "145 000€",
        "loc": "Saint-Étienne centre", "score": 8, "urgence": 3, "bud": 3, "mot": 2,
        "timeline": "3-4 mois",
        "financement": "Propriétaire sans crédit",
        "motivation": "Divorce, besoin de vendre pour répartir le patrimoine",
        "statut": LeadStatus.RDV_BOOKÉ, "source": Canal.SMS,
        "resume": "Vendeur urgent post-divorce. T3/65m² libre, DPE C. RDV estimation mercredi 14h30.",
        "jours": 2, "has_conv": True, "has_rdv": True,
    },
    {
        "prenom": "Christophe", "nom": "Aubert",
        "tel": "+33677001103", "email": "c.aubert@hotmail.fr",
        "projet": "achat", "budget": "320 000€",
        "loc": "Villars", "score": 9, "urgence": 4, "bud": 3, "mot": 2,
        "timeline": "Avant juillet 2026",
        "financement": "Accord BNP, apport 15%",
        "motivation": "Mutation Clermont-Ferrand → Saint-Étienne, maison avec garage",
        "statut": LeadStatus.RDV_BOOKÉ, "source": Canal.LEBONCOIN,
        "resume": "Mutation pro, délai urgent, financement validé. Propriétaire vendeur Clermont. RDV lundi 9h.",
        "jours": 1, "has_conv": True, "has_rdv": True,
    },
    # ── Tièdes : score 5-7 ────────────────────────────────────────────────────
    {
        "prenom": "Sandrine", "nom": "Bonnet",
        "tel": "+33677001104", "email": "sandrine.bonnet@sfr.fr",
        "projet": "achat", "budget": "195 000€",
        "loc": "La Talaudière", "score": 7, "urgence": 3, "bud": 2, "mot": 2,
        "timeline": "6-8 mois",
        "financement": "Simulation Crédit Mutuel en cours, apport 10%",
        "motivation": "Première acquisition, sortir de la location",
        "statut": LeadStatus.QUALIFIE, "source": Canal.SELOGER,
        "resume": "Primo-accédante motivée, financement à finaliser. Secteur La Talaudière.",
        "jours": 5, "has_conv": True,
        "nurturing": NurturingSequence.ACHETEUR_QUALIFIE,
    },
    {
        "prenom": "Alain", "nom": "Marchand",
        "tel": "+33677001105", "email": "a.marchand@gmail.com",
        "projet": "estimation", "budget": "—",
        "loc": "Sorbiers", "score": 6, "urgence": 2, "bud": 2, "mot": 2,
        "timeline": "Décision dans 6 mois",
        "financement": "Propriétaire sans crédit",
        "motivation": "Héritage récent, étudie la vente pour investir ailleurs",
        "statut": LeadStatus.NURTURING, "source": Canal.WEB,
        "resume": "Héritage maison Sorbiers, pas encore décidé. Relancer dans 3 semaines.",
        "jours": 8,
        "nurturing": NurturingSequence.VENDEUR_CHAUD,
    },
    {
        "prenom": "Marie-Laure", "nom": "Peyrard",
        "tel": "+33677001106", "email": "ml.peyrard@laposte.net",
        "projet": "vente", "budget": "390 000€",
        "loc": "Saint-Genest-Lerpt", "score": 6, "urgence": 2, "bud": 2, "mot": 2,
        "timeline": "5-6 mois",
        "financement": "Propriétaire, vente conditionnelle à achat T3 Lyon",
        "motivation": "Nid vide — les enfants sont partis, veut s'installer à Lyon",
        "statut": LeadStatus.NURTURING, "source": Canal.SELOGER,
        "resume": "Vente chaîne SGLerpt → achat Lyon. Maison 130m²/5P/DPE B.",
        "jours": 6, "has_conv": True,
        "nurturing": NurturingSequence.VENDEUR_CHAUD,
    },
    {
        "prenom": "Thierry", "nom": "Collomb",
        "tel": "+33677001107", "email": "t.collomb@free.fr",
        "projet": "achat", "budget": "120 000€",
        "loc": "Saint-Étienne centre", "score": 5, "urgence": 2, "bud": 1, "mot": 2,
        "timeline": "Pas de délai précis",
        "financement": "Apport 5 000€, simulation bancaire non réalisée",
        "motivation": "Fatigué de la location, cherche F2 calme",
        "statut": LeadStatus.NURTURING, "source": Canal.LEBONCOIN,
        "resume": "Acheteur sans financement validé, délai flou. Nurturing à 30j.",
        "jours": 12,
        "nurturing": NurturingSequence.ACHETEUR_QUALIFIE,
    },
    {
        "prenom": "Catherine", "nom": "Dumas",
        "tel": "+33677001108", "email": "c.dumas@gmail.com",
        "projet": "location", "budget": "700€/mois",
        "loc": "La Talaudière", "score": 5, "urgence": 2, "bud": 1, "mot": 2,
        "timeline": "2-3 mois",
        "financement": "Locataire, CDI fonction publique",
        "motivation": "Rapprochement du lycée de sa fille",
        "statut": LeadStatus.NURTURING, "source": Canal.WEB,
        "resume": "Fonctionnaire, loyer 700€/mois, cherche T3 La Talaudière.",
        "jours": 4,
        "nurturing": NurturingSequence.ACHETEUR_QUALIFIE,
    },
    # ── Froids : score 1-4 ────────────────────────────────────────────────────
    {
        "prenom": "Robert", "nom": "Tissot",
        "tel": "+33677001109", "email": "robert.tissot@yahoo.fr",
        "projet": "achat", "budget": "80 000€",
        "loc": "Sorbiers", "score": 4, "urgence": 1, "bud": 2, "mot": 1,
        "timeline": "Dans 2 ans",
        "financement": "Épargne en cours",
        "motivation": "Terrain à bâtir, projet lointain",
        "statut": LeadStatus.NURTURING, "source": Canal.SELOGER,
        "resume": "Projet terrain lointain, horizon 2 ans. Nurturing long terme.",
        "jours": 14,
        "nurturing": NurturingSequence.LEAD_FROID,
    },
    {
        "prenom": "Valérie", "nom": "Jomard",
        "tel": "+33677001110", "email": "v.jomard@gmail.com",
        "projet": "estimation", "budget": "—",
        "loc": "Saint-Étienne centre", "score": 3, "urgence": 1, "bud": 1, "mot": 1,
        "timeline": "Pas de projet concret",
        "financement": "Propriétaire",
        "motivation": "Simple curiosité sur la valeur du bien",
        "statut": LeadStatus.NURTURING, "source": Canal.LEBONCOIN,
        "resume": "Curiosité marché, aucune intention de vente à court terme.",
        "jours": 18,
        "nurturing": NurturingSequence.LEAD_FROID,
    },
    {
        "prenom": "Pascal", "nom": "Revol",
        "tel": "+33677001111", "email": "pascal.revol@sfr.fr",
        "projet": "achat", "budget": "150 000€",
        "loc": "Villars", "score": 3, "urgence": 1, "bud": 1, "mot": 1,
        "timeline": "Vague idée",
        "financement": "Aucun financement étudié",
        "motivation": "Vague intérêt pour l'immobilier",
        "statut": LeadStatus.NURTURING, "source": Canal.SELOGER,
        "resume": "Lead froid sans projet défini. Nurturing 30j.",
        "jours": 21,
        "nurturing": NurturingSequence.LEAD_FROID,
    },
    {
        "prenom": "Isabelle", "nom": "Faure",
        "tel": "+33677001112", "email": "",
        "projet": "achat", "budget": "170 000€",
        "loc": "Saint-Priest-en-Jarez", "score": 2, "urgence": 1, "bud": 1, "mot": 0,
        "timeline": "Indéterminé",
        "financement": "Inconnu",
        "motivation": "Inconnu",
        "statut": LeadStatus.ENTRANT, "source": Canal.WEB,
        "resume": "Lead entrant sans qualification.",
        "jours": 1,
    },
    {
        "prenom": "Gérard", "nom": "Moulin",
        "tel": "+33677001113", "email": "g.moulin@gmail.com",
        "projet": "estimation", "budget": "—",
        "loc": "Saint-Étienne centre", "score": 2, "urgence": 1, "bud": 0, "mot": 1,
        "timeline": "Indéterminé",
        "financement": "Propriétaire",
        "motivation": "A lu un article sur le marché stéphanois",
        "statut": LeadStatus.ENTRANT, "source": Canal.LEBONCOIN,
        "resume": "Lead froid, curiosité presse.",
        "jours": 2,
    },
    {
        "prenom": "Sylvie", "nom": "Arnaud",
        "tel": "+33677001114", "email": "sylvie.arnaud@orange.fr",
        "projet": "vente", "budget": "210 000€",
        "loc": "Saint-Genest-Lerpt", "score": 1, "urgence": 0, "bud": 1, "mot": 0,
        "timeline": "Pas décidé",
        "financement": "Propriétaire",
        "motivation": "Peut-être dans quelques années",
        "statut": LeadStatus.ENTRANT, "source": Canal.SELOGER,
        "resume": "Lead très froid, sans motivation claire.",
        "jours": 3,
    },
    {
        "prenom": "Michel", "nom": "Berthet",
        "tel": "+33677001115", "email": "",
        "projet": "achat", "budget": "100 000€",
        "loc": "La Talaudière", "score": 1, "urgence": 0, "bud": 1, "mot": 0,
        "timeline": "Inconnu",
        "financement": "Inconnu",
        "motivation": "Inconnu",
        "statut": LeadStatus.ENTRANT, "source": Canal.LEBONCOIN,
        "resume": "Lead entrant sans information.",
        "jours": 0,
    },
]

# ─── Lead live démo ───────────────────────────────────────────────────────────

LEAD_LIVE = {
    "prenom": "Jérôme", "nom": "Martin",
    "tel": "+33614150263", "email": "jerome.martin.st42@gmail.com",
    "projet": "achat", "budget": "350 000€",
    "loc": "Saint-Étienne avenue de Verdun", "score": 0, "urgence": 0, "bud": 0, "mot": 0,
    "timeline": "Non renseigné",
    "financement": "Non renseigné",
    "motivation": "Non renseigné",
    "statut": LeadStatus.ENTRANT, "source": Canal.SELOGER,
    "resume": "Lead SeLoger — maison 4 pièces avenue de Verdun, 350 000€. Non encore contacté.",
    "notes_agent": "LEAD LIVE DÉMO — déclencher manuellement pendant la présentation",
    "jours": 0,
}

# ─── Conversations SMS (7 questions qualification avec Léa) ───────────────────

CONVERSATIONS = {
    "+33677001101": [  # Fabrice Dumoulin
        ("user",      "Bonjour, j'ai vu votre annonce sur SeLoger pour une maison à Saint-Priest-en-Jarez"),
        ("assistant", "Bonjour Fabrice ! Je suis Léa, votre conseillère chez Guy Hoquet Saint-Étienne Nord. Vous avez un projet immobilier en cours ?"),
        ("user",      "Oui, j'aimerais acheter une maison — on est une famille de 4 et on manque de place"),
        ("assistant", "Je comprends parfaitement ! Vous cherchez principalement dans quel secteur de la région stéphanoise ?"),
        ("user",      "Saint-Priest-en-Jarez ou Villars, on veut rester proche des écoles"),
        ("assistant", "Excellent choix, deux secteurs très appréciés des familles. Quel est votre budget pour cette acquisition ?"),
        ("user",      "On peut aller jusqu'à 290 000€, avec une certaine flexibilité selon le bien"),
        ("assistant", "Très bien. Vous avez un délai souhaité pour conclure cet achat ?"),
        ("user",      "Idéalement avant la rentrée de septembre, soit d'ici 4 à 5 mois"),
        ("assistant", "C'est tout à fait réalisable sur ce secteur. Quelle est votre situation actuelle — locataire ou déjà propriétaire ?"),
        ("user",      "Locataire depuis 6 ans dans un T3, ça devient vraiment petit avec les enfants"),
        ("assistant", "Je vois. Avez-vous déjà obtenu un accord de financement ou fait une simulation bancaire ?"),
        ("user",      "Oui, accord de principe du CIC avec 30 000€ d'apport, la capacité est confirmée"),
        ("assistant", "Excellent — dossier très solide. Qu'est-ce qui vous motive le plus dans cet achat, un jardin, un garage, de l'espace ?"),
        ("user",      "Un jardin pour les enfants surtout, et arrêter de payer un loyer à perte"),
        ("assistant", "Fabrice, votre projet est très clair et votre financement bien avancé. Je vous propose un rendez-vous cette semaine pour vous présenter nos biens disponibles à SPJ et Villars. Jeudi 10h ou vendredi 14h ?"),
        ("user",      "Vendredi 14h c'est parfait"),
        ("assistant", "Parfait ! RDV confirmé vendredi à 14h en agence. Je vous prépare une sélection de 3 maisons correspondant à vos critères. À vendredi, Fabrice !"),
    ],
    "+33677001102": [  # Nathalie Veyret
        ("user",      "Bonjour j'aimerais vendre mon appartement à Saint-Étienne"),
        ("assistant", "Bonjour Nathalie ! Je suis Léa de Guy Hoquet Saint-Étienne Nord. Quel type de bien souhaitez-vous mettre en vente ?"),
        ("user",      "Un T3 de 65m² dans le centre, quartier Bergson, en bon état"),
        ("assistant", "Bien situé ! Avez-vous déjà une idée du prix de vente souhaité ?"),
        ("user",      "Autour de 145 000€ — j'aimerais vendre rapidement, situation personnelle compliquée"),
        ("assistant", "Je comprends. Quel délai vous donnez-vous pour cette vente ?"),
        ("user",      "3 à 4 mois maximum, j'ai une succession à régler suite à un divorce"),
        ("assistant", "Je note l'urgence. Êtes-vous la seule propriétaire ou avez-vous un co-emprunteur ?"),
        ("user",      "Seule propriétaire, aucun crédit dessus"),
        ("assistant", "Parfait, ça simplifie tout. Le bien est actuellement libre ou occupé ?"),
        ("user",      "Libre depuis le mois dernier"),
        ("assistant", "Excellent — un bien libre se vend plus vite. Pour vous, c'est quoi la priorité : le meilleur prix ou la rapidité de vente ?"),
        ("user",      "La rapidité, mais sans brader — je veux récupérer une somme juste"),
        ("assistant", "Je comprends cet équilibre, c'est tout à fait raisonnable. Nathalie, votre T3 libre centre-ville à 145K€ correspond bien au marché actuel. Je vous propose une estimation officielle cette semaine. Mercredi après-midi vous convient ?"),
        ("user",      "Oui mercredi 14h30 c'est parfait"),
        ("assistant", "Mercredi 14h30 c'est noté ! Je passe chez vous pour l'estimation. À mercredi, Nathalie !"),
    ],
    "+33677001103": [  # Christophe Aubert
        ("user",      "Bonjour, annonce LeBonCoin maison Villars, encore disponible ?"),
        ("assistant", "Bonjour Christophe ! Je suis Léa de Guy Hoquet Saint-Étienne Nord. Vous êtes à la recherche d'une maison sur Villars ?"),
        ("user",      "Oui je cherche pour ma famille, j'ai une mutation pro de Clermont à Saint-Étienne"),
        ("assistant", "Bienvenue dans la région ! Quel type de maison cherchez-vous et quel est votre budget ?"),
        ("user",      "Maison avec garage, 4 pièces minimum, budget 320 000€"),
        ("assistant", "Excellent budget pour ce secteur. Vous avez un délai pour vous installer ?"),
        ("user",      "Mutation en juillet, donc signer avant fin juin idéalement"),
        ("assistant", "Le délai est serré mais réaliste. Vous êtes propriétaire à Clermont ou locataire ?"),
        ("user",      "Propriétaire — on a vendu notre maison le mois dernier, on est en transition"),
        ("assistant", "Parfait, sans vente à synchroniser c'est beaucoup plus simple. Votre financement est déjà en place ?"),
        ("user",      "Oui, accord BNP avec 15% d'apport, tout est validé"),
        ("assistant", "Dossier au top ! Qu'est-ce qui est prioritaire entre le garage, le jardin et la proximité des écoles ?"),
        ("user",      "Garage double en priorité, jardin ensuite, et le calme du quartier"),
        ("assistant", "Christophe, j'ai 2 biens à Villars correspondant exactement à vos critères avec garage double. Je vous propose de les visiter lundi. 9h ou 11h ?"),
        ("user",      "Lundi 9h c'est très bien"),
        ("assistant", "RDV lundi 9h confirmé — on visite les 2 maisons avec garage à Villars. Je vous envoie les fiches avant le weekend. À lundi !"),
    ],
    "+33677001104": [  # Sandrine Bonnet
        ("user",      "Bonjour, je cherche un appartement sur La Talaudière"),
        ("assistant", "Bonjour Sandrine ! Je suis Léa de Guy Hoquet Saint-Étienne Nord. C'est pour un achat ou une location ?"),
        ("user",      "Achat — je suis encore locataire mais je veux devenir propriétaire"),
        ("assistant", "C'est une excellente décision ! Vous avez un budget en tête ?"),
        ("user",      "Autour de 195 000€, peut-être un peu plus si le bien le vaut"),
        ("assistant", "Très bien pour La Talaudière. Vous cherchez quel type de bien — appartement, maison ?"),
        ("user",      "Appartement T3 ou petite maison, je suis seule mais j'aime l'espace"),
        ("assistant", "Je comprends. Vous avez un délai souhaité pour cette acquisition ?"),
        ("user",      "Pas d'urgence, 6 à 8 mois, je prends le temps de bien choisir"),
        ("assistant", "Sage approche. Votre financement est déjà étudié ?"),
        ("user",      "Simulation en cours au Crédit Mutuel, j'ai 10% d'apport"),
        ("assistant", "Bon point de départ. Qu'est-ce qui vous attire particulièrement sur La Talaudière ?"),
        ("user",      "Le calme, les commerces de proximité, et c'est pas loin de mon travail à Andrézieux"),
        ("assistant", "Sandrine, je vais vous préparer une sélection de T3 sur La Talaudière dans votre budget. Tenez-moi informée de la simulation Crédit Mutuel et je vous rappelle dès qu'on a des biens correspondants. À très bientôt !"),
        ("user",      "Parfait, je reviens vers vous dès que j'ai la réponse de la banque"),
        ("assistant", "Super ! En attendant je vous envoie 2 fiches de biens disponibles pour affiner vos critères. Belle journée Sandrine !"),
    ],
    "+33677001106": [  # Marie-Laure Peyrard
        ("user",      "Bonjour, je souhaite mettre en vente ma maison à Saint-Genest-Lerpt"),
        ("assistant", "Bonjour Marie-Laure ! Je suis Léa de Guy Hoquet Saint-Étienne Nord. Pouvez-vous me donner quelques informations sur le bien ?"),
        ("user",      "Maison de 130m², 5 pièces, terrain 600m², très bon état, DPE B"),
        ("assistant", "Bel ensemble ! Vous avez une idée du prix de vente souhaité ?"),
        ("user",      "Autour de 390 000€ — les comparables dans le secteur partent entre 370 et 410"),
        ("assistant", "Vous êtes bien informée du marché. Vous avez un délai pour cette vente ?"),
        ("user",      "5 à 6 mois — je dois vendre pour acheter un T3 à Lyon, les enfants sont partis"),
        ("assistant", "Je comprends cette transition. La vente est conditionnelle à votre achat à Lyon ?"),
        ("user",      "Oui, j'ai besoin des fonds de la vente pour financer l'achat"),
        ("assistant", "C'est une chaîne à bien orchestrer. Votre maison est actuellement occupée par vous seule ?"),
        ("user",      "Oui, depuis 8 mois maintenant"),
        ("assistant", "Très bien. Entre le prix, la rapidité et la discrétion, qu'est-ce qui compte le plus pour vous ?"),
        ("user",      "L'équilibre entre les trois — je veux pas brader mais pas traîner non plus"),
        ("assistant", "Marie-Laure, votre maison DPE B à Saint-Genest-Lerpt va très bien se vendre. Je vous propose de venir faire l'estimation officielle et prendre les photos cette semaine. Mardi ou jeudi matin ?"),
        ("user",      "Jeudi matin si possible"),
        ("assistant", "Jeudi matin noté ! Je viendrai avec notre photographe à 10h. On fait l'estimation complète et les visuels en une seule visite. À jeudi, Marie-Laure !"),
    ],
}


# ─── Création / mise à jour user démo ────────────────────────────────────────

def create_demo_user() -> str:
    password_hash = bcrypt.hashpw(
        DEMO_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users
                (id, email, password_hash, agency_name, first_name, plan, plan_active)
            VALUES (?, ?, ?, ?, ?, 'Pro', TRUE)
            ON CONFLICT(email) DO UPDATE SET
                agency_name  = EXCLUDED.agency_name,
                first_name   = EXCLUDED.first_name,
                plan         = 'Pro',
                plan_active  = TRUE
            """,
            (DEMO_USER_ID, DEMO_EMAIL, password_hash, DEMO_AGENCY, DEMO_FIRSTNAME),
        )

    print(f"   Utilisateur   : {DEMO_EMAIL}")
    print(f"   Mot de passe  : {DEMO_PASSWORD}")
    print(f"   Agence        : {DEMO_AGENCY}")
    return DEMO_USER_ID


def assign_twilio(user_id: str) -> None:
    from config.settings import assign_twilio_number
    number = assign_twilio_number(user_id)
    if number:
        print(f"   Numéro Twilio : {number}")
    else:
        print("   Numéro Twilio : non assigné (pool vide ou TWILIO_AVAILABLE_NUMBERS non configuré)")


# ─── Nettoyage données existantes ────────────────────────────────────────────

def clean_demo_data(user_id: str) -> None:
    with get_connection() as conn:
        # Récupère les IDs de leads pour supprimer les données liées
        rows = conn.execute(
            "SELECT id FROM leads WHERE client_id = ?", (user_id,)
        ).fetchall()
        lead_ids = [r["id"] for r in rows]

        for lead_id in lead_ids:
            conn.execute("DELETE FROM conversations WHERE lead_id = ?", (lead_id,))
            conn.execute("DELETE FROM lead_journey  WHERE lead_id = ?", (lead_id,))

        conn.execute("DELETE FROM leads          WHERE client_id = ?", (user_id,))
        conn.execute("DELETE FROM usage_tracking WHERE client_id = ?", (user_id,))

    print(f"   Nettoyage : {len(lead_ids)} leads existants supprimés")


# ─── Création des leads ───────────────────────────────────────────────────────

def create_leads(user_id: str) -> dict[str, str]:
    """Crée les 15 leads + le lead live. Retourne {telephone: lead_id}."""
    phone_to_id: dict[str, str] = {}
    now = datetime.now()

    all_leads = LEADS + [LEAD_LIVE]
    for data in all_leads:
        lead_id = str(uuid4())
        days_ago = data.get("jours", 0)
        created = now - timedelta(days=days_ago)

        # RDV dans les prochains jours — piloté par has_rdv (source de vérité)
        rdv_date = None
        if data.get("has_rdv") or data["statut"] == LeadStatus.RDV_BOOKÉ:
            rdv_date = now + timedelta(days=(3 - days_ago) if days_ago < 3 else 2)

        # Prochain followup pour les leads nurturing
        prochain = None
        if data["statut"] == LeadStatus.NURTURING:
            prochain = now + timedelta(days=max(1, 7 - days_ago))

        lead = Lead(
            id=lead_id,
            client_id=user_id,
            prenom=data["prenom"],
            nom=data["nom"],
            telephone=data["tel"],
            email=data.get("email", ""),
            source=data["source"],
            projet=ProjetType(data["projet"]),
            localisation=data["loc"],
            budget=data["budget"],
            timeline=data["timeline"],
            financement=data["financement"],
            motivation=data["motivation"],
            score=data["score"],
            score_urgence=data["urgence"],
            score_budget=data["bud"],
            score_motivation=data["mot"],
            statut=data["statut"],
            nurturing_sequence=data.get("nurturing"),
            nurturing_step=1 if data.get("nurturing") else 0,
            prochain_followup=prochain,
            rdv_date=rdv_date,
            resume=data.get("resume", ""),
            notes_agent=data.get("notes_agent", ""),
            created_at=created,
            updated_at=created,
        )
        create_lead(lead)
        phone_to_id[data["tel"]] = lead_id

    return phone_to_id


# ─── Conversations SMS ────────────────────────────────────────────────────────

def seed_conversations(user_id: str, phone_to_id: dict[str, str]) -> None:
    for phone, messages in CONVERSATIONS.items():
        lead_id = phone_to_id.get(phone)
        if not lead_id:
            print(f"   [WARN] Conversation ignorée — lead {phone} introuvable")
            continue
        for role, contenu in messages:
            add_conversation_message(
                lead_id=lead_id,
                client_id=user_id,
                role=role,
                contenu=contenu,
                canal=Canal.SMS,
            )


# ─── Lead journey : RDVs Google Calendar ─────────────────────────────────────

def seed_rdv_journey(user_id: str, phone_to_id: dict[str, str]) -> None:
    """Précharge lead_journey pour les 3 leads avec RDV (simule la création Calendar)."""
    rdv_phones = ["+33677001101", "+33677001102", "+33677001103"]
    rdv_labels = {
        "+33677001101": ("Fabrice Dumoulin", "Présentation sélection maisons SPJ/Villars"),
        "+33677001102": ("Nathalie Veyret",  "Estimation officielle T3 centre Saint-Étienne"),
        "+33677001103": ("Christophe Aubert","Visite 2 maisons avec garage double à Villars"),
    }
    now = datetime.now()

    with get_connection() as conn:
        for phone in rdv_phones:
            lead_id = phone_to_id.get(phone)
            if not lead_id:
                continue
            nom, objet = rdv_labels[phone]
            rdv_dt = now + timedelta(days=2)
            conn.execute(
                """
                INSERT INTO lead_journey
                    (lead_id, client_id, stage, action_done, action_result,
                     next_action, next_action_at, agent_name, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_id, user_id,
                    "rdv_booké",
                    "rdv_calendar_créé",
                    f"RDV créé dans Google Calendar — {objet}",
                    "envoi_confirmation_sms",
                    rdv_dt,
                    "Léa",
                    json.dumps({
                        "calendar_event_id": f"evt_demo_{lead_id[:8]}",
                        "rdv_objet": objet,
                        "rdv_datetime": rdv_dt.isoformat(),
                        "lead_nom": nom,
                    }),
                ),
            )


# ─── Usage data ───────────────────────────────────────────────────────────────

def seed_usage(user_id: str) -> None:
    month = datetime.now().strftime("%Y-%m")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO usage_tracking
                (client_id, month, leads_count, voice_minutes, images_count,
                 tokens_used, followups_count, listings_count, estimations_count, tier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pro')
            ON CONFLICT(client_id, month) DO UPDATE SET
                leads_count      = 47,
                voice_minutes    = 38.5,
                images_count     = 12,
                tokens_used      = 1_840_000,
                followups_count  = 94,
                listings_count   = 8,
                estimations_count= 5,
                tier             = 'Pro'
            """,
            (user_id, month, 47, 38.5, 12, 1_840_000, 94, 8, 5),
        )


# ─── Vérification post-seed ───────────────────────────────────────────────────

def verify(user_id: str) -> bool:
    ok = True
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id, email, plan_active FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user or not user["plan_active"]:
            print("   [FAIL] Utilisateur démo introuvable ou plan inactif")
            ok = False
        else:
            print(f"   [OK] Utilisateur : {user['email']}, plan_active={user['plan_active']}")

        nb_leads = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE client_id = ?", (user_id,)
        ).fetchone()["n"]
        if nb_leads < 16:
            print(f"   [FAIL] Seulement {nb_leads} leads (attendu 16)")
            ok = False
        else:
            print(f"   [OK] {nb_leads} leads créés")

        nb_conv = conn.execute(
            "SELECT COUNT(*) AS n FROM conversations WHERE client_id = ?", (user_id,)
        ).fetchone()["n"]
        if nb_conv < 5:
            print(f"   [FAIL] Seulement {nb_conv} messages de conversation (attendu ≥ 5)")
            ok = False
        else:
            print(f"   [OK] {nb_conv} messages de conversation")

        nb_rdv = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE client_id = ? AND rdv_date IS NOT NULL",
            (user_id,),
        ).fetchone()["n"]
        if nb_rdv < 3:
            print(f"   [FAIL] Seulement {nb_rdv} leads avec RDV (attendu 3)")
            ok = False
        else:
            print(f"   [OK] {nb_rdv} leads avec RDV")

        jerome = conn.execute(
            "SELECT id, statut FROM leads WHERE client_id = ? AND telephone = ?",
            (user_id, "+33614150263"),
        ).fetchone()
        if not jerome:
            print("   [FAIL] Lead live Jérôme Martin introuvable")
            ok = False
        else:
            print(f"   [OK] Lead live Jérôme Martin (statut={jerome['statut']})")

        chauds = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE client_id = ? AND score >= 8",
            (user_id,),
        ).fetchone()["n"]
        tièdes = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE client_id = ? AND score BETWEEN 5 AND 7",
            (user_id,),
        ).fetchone()["n"]
        froids = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE client_id = ? AND score <= 4",
            (user_id,),
        ).fetchone()["n"]
        print(f"   [OK] Répartition scores : {chauds} chauds | {tièdes} tièdes | {froids} froids")

    return ok


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  SEED DÉMO — Guy Hoquet Saint-Étienne Nord")
    print("=" * 60)

    print("\n1. Création de l'utilisateur démo...")
    user_id = create_demo_user()

    print("\n2. Attribution numéro Twilio...")
    assign_twilio(user_id)

    print("\n3. Nettoyage des données existantes...")
    clean_demo_data(user_id)

    print("\n4. Création des leads...")
    phone_to_id = create_leads(user_id)
    total = len(LEADS) + 1  # +1 pour Jérôme Martin
    print(f"   {total} leads créés (15 normaux + 1 lead live démo)")

    print("\n5. Chargement des conversations SMS...")
    seed_conversations(user_id, phone_to_id)
    print(f"   {sum(len(v) for v in CONVERSATIONS.values())} messages chargés pour 5 leads")

    print("\n6. Création des événements RDV (lead_journey)...")
    seed_rdv_journey(user_id, phone_to_id)
    print("   3 RDVs chargés (Dumoulin, Veyret, Aubert)")

    print("\n7. Chargement des données d'usage...")
    seed_usage(user_id)
    print("   Usage mensuel Pro chargé")

    print("\n8. Vérification...")
    success = verify(user_id)

    print("\n" + "=" * 60)
    if success:
        print("  SEED TERMINE AVEC SUCCES")
    else:
        print("  SEED TERMINE AVEC DES ERREURS — vérifier les logs ci-dessus")
    print("=" * 60)
    print(f"\n  Email    : {DEMO_EMAIL}")
    print(f"  Password : {DEMO_PASSWORD}")
    print(f"  User ID  : {user_id}")
    print("\n  Lead live démo (déclencher pendant la présentation) :")
    print("    Jérôme Martin — +33614150263 — maison 4P avenue de Verdun, 350 000€")
    print("\n  Dashboard : streamlit run dashboard/app.py")
    print()


if __name__ == "__main__":
    main()
