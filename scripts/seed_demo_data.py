"""
Script de population des données de démo.
Crée leads réalistes, conversations, usages pour 3 clients-agences.
"""
from __future__ import annotations

import sys
from pathlib import Path
import json
from datetime import datetime, timedelta
from uuid import uuid4
import random

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.database import init_database, get_connection
from memory.models import Canal, Lead, LeadStatus, NurturingSequence, ProjetType
from memory.lead_repository import create_lead, add_conversation_message, update_lead

init_database()

# ─── Données réalistes ────────────────────────────────────────────────────────

LEADS_DATA = [
    # Leads chauds (score ≥ 7)
    {"prenom": "Mathieu", "nom": "Bernard", "tel": "+33612345601", "email": "m.bernard@gmail.com",
     "projet": "achat", "budget": "480 000€", "loc": "Lyon 6e", "score": 9, "urgence": 4, "bud": 3, "mot": 2,
     "timeline": "Avant juin 2026", "financement": "Accord de principe Crédit Agricole, apport 25%",
     "motivation": "Mutation professionnelle Paris → Lyon", "statut": LeadStatus.QUALIFIE,
     "source": Canal.SELOGER, "resume": "Acheteur très motivé, mutation pro, financement solide."},

    {"prenom": "Claire", "nom": "Rousseau", "tel": "+33612345602", "email": "c.rousseau@outlook.fr",
     "projet": "vente", "budget": "320 000€", "loc": "Bordeaux Chartrons", "score": 8, "urgence": 3, "bud": 3, "mot": 2,
     "timeline": "3 mois", "financement": "Propriétaire — vente financement achat suivant",
     "motivation": "Séparation, besoin de liquidités", "statut": LeadStatus.RDV_BOOKÉ,
     "source": Canal.SMS, "resume": "Vendeur urgent suite séparation. Score élevé."},

    {"prenom": "Antoine", "nom": "Lefebvre", "tel": "+33612345603", "email": "antoine.l@hotmail.com",
     "projet": "achat", "budget": "220 000€", "loc": "Nantes Est", "score": 7, "urgence": 3, "bud": 2, "mot": 2,
     "timeline": "2-4 mois", "financement": "Apport 15%, simulation bancaire en cours",
     "motivation": "Première acquisition, investissement locatif", "statut": LeadStatus.QUALIFIE,
     "source": Canal.WEB, "resume": "Primo-accédant, projet investissement locatif."},

    {"prenom": "Sophie", "nom": "Martin", "tel": "+33612345604", "email": "sophie.martin@gmail.com",
     "projet": "vente", "budget": "850 000€", "loc": "Paris 15e", "score": 9, "urgence": 4, "bud": 3, "mot": 2,
     "timeline": "Urgent — déménagement prévu en avril", "financement": "Propriétaire sans crédit",
     "motivation": "Retraite à la campagne, vente appartement Paris", "statut": LeadStatus.MANDAT,
     "source": Canal.LEBONCOIN, "resume": "Vendeur Paris, retraite, très motivé."},

    {"prenom": "Julien", "nom": "Dupont", "tel": "+33612345605", "email": "julien.d@gmail.com",
     "projet": "achat", "budget": "350 000€", "loc": "Marseille 8e", "score": 8, "urgence": 3, "bud": 3, "mot": 2,
     "timeline": "4-5 mois", "financement": "Accord bancaire BNP, apport 22%",
     "motivation": "Agrandissement famille, 3ème enfant", "statut": LeadStatus.RDV_BOOKÉ,
     "source": Canal.WHATSAPP, "resume": "Acheteur avec financement, famille en croissance."},

    # Leads tièdes (score 4-6)
    {"prenom": "Marie", "nom": "Petit", "tel": "+33612345606", "email": "marie.petit@yahoo.fr",
     "projet": "achat", "budget": "180 000€", "loc": "Toulouse Capitole", "score": 6, "urgence": 2, "bud": 2, "mot": 2,
     "timeline": "6-12 mois", "financement": "Apport 10%, pas encore de simulation",
     "motivation": "Lassée de la location", "statut": LeadStatus.NURTURING,
     "source": Canal.SMS, "resume": "Acheteur tiède, délai long, financement à consolider.",
     "nurturing": NurturingSequence.ACHETEUR_QUALIFIE},

    {"prenom": "Thomas", "nom": "Moreau", "tel": "+33612345607", "email": "t.moreau@free.fr",
     "projet": "estimation", "budget": "—", "loc": "Strasbourg Centre", "score": 5, "urgence": 2, "bud": 2, "mot": 1,
     "timeline": "Pas décidé encore", "financement": "Propriétaire",
     "motivation": "Curiosité marché, héritage récent", "statut": LeadStatus.NURTURING,
     "source": Canal.WEB, "resume": "Héritage récent, pas encore décidé sur la vente.",
     "nurturing": NurturingSequence.VENDEUR_CHAUD},

    {"prenom": "Isabelle", "nom": "Simon", "tel": "+33612345608", "email": "isabelle.s@gmail.com",
     "projet": "location", "budget": "900€/mois", "loc": "Rennes Centre", "score": 5, "urgence": 2, "bud": 2, "mot": 1,
     "timeline": "Dans 3-4 mois", "financement": "Locataire actuel",
     "motivation": "Rapprochement travail", "statut": LeadStatus.NURTURING,
     "source": Canal.SMS, "resume": "Locataire cherche T3 pour rapprochement travail.",
     "nurturing": NurturingSequence.ACHETEUR_QUALIFIE},

    {"prenom": "Pierre", "nom": "Garnier", "tel": "+33612345609", "email": "pierre.garnier@sfr.fr",
     "projet": "achat", "budget": "290 000€", "loc": "Nice Cimiez", "score": 6, "urgence": 2, "bud": 2, "mot": 2,
     "timeline": "Avant fin d'année", "financement": "Apport 18%, simulation Société Générale",
     "motivation": "Divorce en cours, besoin de stabilité", "statut": LeadStatus.NURTURING,
     "source": Canal.EMAIL, "resume": "Divorce en cours, acheteur avec apport partiel.",
     "nurturing": NurturingSequence.ACHETEUR_QUALIFIE},

    {"prenom": "Claire", "nom": "Dubois", "tel": "+33612345610", "email": "claire.dubois@laposte.net",
     "projet": "vente", "budget": "410 000€", "loc": "Montpellier Antigone", "score": 6, "urgence": 2, "bud": 2, "mot": 2,
     "timeline": "5-6 mois", "financement": "Propriétaire, veut vendre avant d'acheter",
     "motivation": "Mutation pour Lyon", "statut": LeadStatus.NURTURING,
     "source": Canal.SELOGER, "resume": "Vendeur-acheteur, chaîne conditionnelle.",
     "nurturing": NurturingSequence.VENDEUR_CHAUD},

    # Leads froids (score < 4)
    {"prenom": "Nicolas", "nom": "Lambert", "tel": "+33612345611", "email": "n.lambert@gmail.com",
     "projet": "achat", "budget": "150 000€", "loc": "Rouen", "score": 3, "urgence": 1, "bud": 1, "mot": 1,
     "timeline": "Dans 2 ans", "financement": "Pas encore réfléchi",
     "motivation": "Vague idée", "statut": LeadStatus.NURTURING,
     "source": Canal.SMS, "resume": "Lead froid, horizon 2 ans.",
     "nurturing": NurturingSequence.LEAD_FROID},

    {"prenom": "Lucie", "nom": "Fontaine", "tel": "+33612345612", "email": "",
     "projet": "estimation", "budget": "—", "loc": "Grenoble", "score": 2, "urgence": 1, "bud": 0, "mot": 1,
     "timeline": "Pas de délai", "financement": "Inconnu",
     "motivation": "Simple curiosité", "statut": LeadStatus.NURTURING,
     "source": Canal.WEB, "resume": "Simple curiosité, pas de projet concret.",
     "nurturing": NurturingSequence.LEAD_FROID},

    {"prenom": "François", "nom": "Mercier", "tel": "+33612345613", "email": "f.mercier@gmail.com",
     "projet": "inconnu", "budget": "—", "loc": "Lille", "score": 1, "urgence": 0, "bud": 1, "mot": 0,
     "timeline": "Inconnu", "financement": "Inconnu",
     "motivation": "Inconnu", "statut": LeadStatus.ENTRANT,
     "source": Canal.LEBONCOIN, "resume": "Lead sans qualification."},

    # Mandats et ventes
    {"prenom": "Emma", "nom": "Chevalier", "tel": "+33612345614", "email": "emma.c@gmail.com",
     "projet": "vente", "budget": "595 000€", "loc": "Paris 11e", "score": 9, "urgence": 4, "bud": 3, "mot": 2,
     "timeline": "Signé", "financement": "Propriétaire",
     "motivation": "Déménagement Bretagne", "statut": LeadStatus.VENDU,
     "source": Canal.SMS, "resume": "Mandat signé, en cours de vente."},

    {"prenom": "Alexandre", "nom": "Roux", "tel": "+33612345615", "email": "alexandre.r@gmail.com",
     "projet": "achat", "budget": "440 000€", "loc": "Lyon 3e", "score": 8, "urgence": 3, "bud": 3, "mot": 2,
     "timeline": "Compromis signé", "financement": "Accord BNP",
     "motivation": "Retour Lyon après expatriation", "statut": LeadStatus.MANDAT,
     "source": Canal.WEB, "resume": "Mandat achat, compromis en cours."},

    # Leads supplémentaires variés
    {"prenom": "Chloé", "nom": "Blanc", "tel": "+33612345616", "email": "chloe.b@gmail.com",
     "projet": "achat", "budget": "265 000€", "loc": "Nantes Erdre", "score": 7, "urgence": 3, "bud": 2, "mot": 2,
     "timeline": "3 mois", "financement": "Apport 20%, accord LCL",
     "motivation": "Première acquisition", "statut": LeadStatus.QUALIFIE,
     "source": Canal.WHATSAPP, "resume": "Primo-accédant avec financement solide."},

    {"prenom": "Hugo", "nom": "Morel", "tel": "+33612345617", "email": "hugo.m@hotmail.com",
     "projet": "location", "budget": "1 200€/mois", "loc": "Bordeaux Centre", "score": 4, "urgence": 2, "bud": 1, "mot": 1,
     "timeline": "2 mois", "financement": "Locataire",
     "motivation": "Besoin T3", "statut": LeadStatus.NURTURING,
     "source": Canal.EMAIL, "resume": "Locataire cherche T3, délai 2 mois.",
     "nurturing": NurturingSequence.ACHETEUR_QUALIFIE},

    {"prenom": "Océane", "nom": "Girard", "tel": "+33612345618", "email": "oceane.g@gmail.com",
     "projet": "vente", "budget": "185 000€", "loc": "Dijon Centre", "score": 7, "urgence": 3, "bud": 2, "mot": 2,
     "timeline": "4 mois", "financement": "Propriétaire sans crédit",
     "motivation": "Héritage, bien familial à vendre", "statut": LeadStatus.QUALIFIE,
     "source": Canal.SMS, "resume": "Héritage, bien à vendre rapidement."},

    {"prenom": "Romain", "nom": "Perrin", "tel": "+33612345619", "email": "romain.p@sfr.fr",
     "projet": "achat", "budget": "520 000€", "loc": "Paris 14e", "score": 8, "urgence": 4, "bud": 2, "mot": 2,
     "timeline": "Avant juillet", "financement": "Accord BNP, apport 30%",
     "motivation": "Agrandissement, 2ème enfant", "statut": LeadStatus.RDV_BOOKÉ,
     "source": Canal.SELOGER, "resume": "Acheteur Paris, délai urgent, bon financement."},

    {"prenom": "Pauline", "nom": "Clement", "tel": "+33612345620", "email": "pauline.c@gmail.com",
     "projet": "estimation", "budget": "—", "loc": "Tours Centre", "score": 5, "urgence": 2, "bud": 2, "mot": 1,
     "timeline": "Réflexion", "financement": "Propriétaire",
     "motivation": "Divorce imminent", "statut": LeadStatus.NURTURING,
     "source": Canal.WEB, "resume": "Propriétaire en réflexion, divorce probable.",
     "nurturing": NurturingSequence.VENDEUR_CHAUD},

    {"prenom": "Adrien", "nom": "Bertrand", "tel": "+33612345621", "email": "a.bertrand@gmail.com",
     "projet": "achat", "budget": "320 000€", "loc": "Montpellier Mosson", "score": 6, "urgence": 2, "bud": 2, "mot": 2,
     "timeline": "6 mois", "financement": "Apport 15%",
     "motivation": "Investissement locatif", "statut": LeadStatus.NURTURING,
     "source": Canal.LEBONCOIN, "resume": "Investisseur locatif, délai modéré.",
     "nurturing": NurturingSequence.ACHETEUR_QUALIFIE},

    {"prenom": "Laura", "nom": "Denis", "tel": "+33612345622", "email": "laura.d@outlook.fr",
     "projet": "vente", "budget": "275 000€", "loc": "Lille Vieux", "score": 8, "urgence": 3, "bud": 3, "mot": 2,
     "timeline": "3 mois", "financement": "Propriétaire, compte épargne",
     "motivation": "Retraite anticipée, simplification patrimoine", "statut": LeadStatus.QUALIFIE,
     "source": Canal.SMS, "resume": "Propriétaire vendeur, retraite prochaine."},

    {"prenom": "Victor", "nom": "Leroy", "tel": "+33612345623", "email": "",
     "projet": "achat", "budget": "130 000€", "loc": "Clermont-Ferrand", "score": 2, "urgence": 1, "bud": 0, "mot": 1,
     "timeline": "Pas encore", "financement": "Aucun",
     "motivation": "Idée vague", "statut": LeadStatus.ENTRANT,
     "source": Canal.WEB, "resume": "Lead froid sans financement."},

    {"prenom": "Inès", "nom": "Robin", "tel": "+33612345624", "email": "ines.r@gmail.com",
     "projet": "location", "budget": "750€/mois", "loc": "Toulouse Minimes", "score": 4, "urgence": 2, "bud": 1, "mot": 1,
     "timeline": "1 mois", "financement": "Locataire, CDI",
     "motivation": "Rapprochement université", "statut": LeadStatus.NURTURING,
     "source": Canal.SMS, "resume": "Locataire cherche T2, urgence modérée.",
     "nurturing": NurturingSequence.ACHETEUR_QUALIFIE},

    {"prenom": "Baptiste", "nom": "Simon", "tel": "+33612345625", "email": "baptiste.s@gmail.com",
     "projet": "achat", "budget": "680 000€", "loc": "Neuilly-sur-Seine", "score": 9, "urgence": 4, "bud": 3, "mot": 2,
     "timeline": "Urgent, avant mars", "financement": "Financement 100% fonds propres",
     "motivation": "Investissement patrimonial, profil executive", "statut": LeadStatus.MANDAT,
     "source": Canal.EMAIL, "resume": "Lead premium, financement propre, mandat signé."},
]

CONVERSATIONS_DEMO = {
    "+33612345601": [
        ("user", "Bonjour, j'ai vu une annonce sur SeLoger pour un appartement à Lyon 6e"),
        ("assistant", "[MOCK] Bonjour Mathieu ! Je suis Sophie, conseillère immobilier chez notre agence. Merci de nous avoir contactés ! Quel est votre projet immobilier : achat, vente, location ou estimation ?"),
        ("user", "Je cherche à acheter un appartement, 3 pièces minimum"),
        ("assistant", "[MOCK] Très bien ! Dans quel secteur de Lyon recherchez-vous précisément, et quel est votre budget ?"),
        ("user", "Lyon 6e ou 8e, budget 480 000€ maxi"),
        ("assistant", "[MOCK] Parfait. Vous avez un délai pour conclure cette acquisition ?"),
        ("user", "Avant juin, j'ai une mutation professionnelle"),
        ("assistant", "[MOCK] Je comprends, c'est une contrainte claire. Avez-vous déjà votre financement en place ?"),
        ("user", "Oui, accord de principe du Crédit Agricole avec 25% d'apport"),
        ("assistant", "[MOCK] Excellent ! Votre dossier est très solide. Je vous propose un rendez-vous cette semaine pour voir ensemble les biens correspondants. Mardi 10h ou jeudi 14h ?"),
    ],
    "+33612345602": [
        ("user", "Je voudrais vendre mon appartement à Bordeaux Chartrons"),
        ("assistant", "[MOCK] Bonjour Claire ! Je suis Sophie de l'agence. Pouvez-vous me donner quelques détails sur le bien ? Surface, nombre de pièces ?"),
        ("user", "80m², 3 pièces, belle vue sur les quais, DPE B"),
        ("assistant", "[MOCK] Très beau bien ! Quel est votre prix de vente souhaité et dans quel délai ?"),
        ("user", "320 000€, j'aimerais vendre dans 3 mois max. Situation personnelle compliquée."),
        ("assistant", "[MOCK] Je comprends. Votre bien à Bordeaux Chartrons de 80m² DPE B avec vue quais, à 320K€ est très attractif. Votre délai de 3 mois est tout à fait réaliste. Je vous propose de passer faire une estimation formelle ?"),
    ],
}


def seed_usage_data(client_id: str, tier: str, leads: int, voice: float, images: int,
                     tokens: int, followups: int, listings: int, estimations: int):
    """Insère ou met à jour les données d'usage pour un client."""
    month = datetime.now().strftime("%Y-%m")
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO usage_tracking
               (client_id, month, leads_count, voice_minutes, images_count,
                tokens_used, followups_count, listings_count, estimations_count, tier)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(client_id, month) DO UPDATE SET
                 leads_count = ?, voice_minutes = ?, images_count = ?,
                 tokens_used = ?, followups_count = ?, listings_count = ?,
                 estimations_count = ?, tier = ?, updated_at = CURRENT_TIMESTAMP""",
            (
                client_id, month, leads, voice, images, tokens, followups, listings, estimations, tier,
                leads, voice, images, tokens, followups, listings, estimations, tier,
            ),
        )


def seed_listings(client_id: str):
    """Crée des annonces de démo."""
    listings = [
        {
            "id": str(uuid4()),
            "lead_id": "",
            "client_id": client_id,
            "type_bien": "Appartement",
            "adresse": "15 rue de la Paix, Lyon 6e (69006)",
            "surface": 78.5,
            "nb_pieces": 3,
            "prix": 480000,
            "dpe": "C",
            "titre": "Lyon 6e — Lumineux T3 parquet chêne, balcon plein sud",
            "description_longue": "Situé au cœur du 6ème arrondissement de Lyon, ce superbe appartement de 78,5 m² (loi Carrez) vous séduira par ses volumes généreux et sa luminosité exceptionnelle. Au 4ème étage d'un immeuble haussmannien bien entretenu, il bénéficie d'une exposition plein sud avec vue dégagée sur les toits. Le séjour de 32 m² avec parquet chêne massif donne accès au balcon filant. La cuisine équipée haut de gamme est indépendante. Deux chambres de 12 et 14 m², une salle de bains avec baignoire, toilettes séparées. Cave, parking en sous-sol. DPE classe C / GES classe C. Charges de copropriété 280€/mois. Quartier Foch — commerces, transports, écoles à pied. Visite virtuelle disponible sur demande.",
            "description_courte": "Lyon 6e Foch — T3 78m² loi Carrez, balcon sud, parking, cave, parquet chêne. DPE C. 4ème étage immeuble haussmannien. 480 000€ FAI.",
            "points_forts": '["Luminosité exceptionnelle plein sud", "Parking en sous-sol inclus", "Parquet chêne massif", "Quartier Foch — toutes commodités"]',
            "mentions_legales": "Surface : 78,5 m² (loi Carrez). DPE : classe C (147 kWh/m²/an) — GES : classe C. Prix : 480 000€ FAI (dont honoraires 3,8% TTC).",
            "mots_cles_seo": '["appartement Lyon 6", "T3 Foch Lyon", "balcon Lyon 6ème", "parking sous-sol Lyon", "haussmannien Lyon"]',
            "images_urls": '[]',
        },
        {
            "id": str(uuid4()),
            "lead_id": "",
            "client_id": client_id,
            "type_bien": "Maison",
            "adresse": "8 allée des Roses, Bordeaux Chartrons (33300)",
            "surface": 142.0,
            "nb_pieces": 5,
            "prix": 750000,
            "dpe": "B",
            "titre": "Bordeaux Chartrons — Maison de maître 5P avec jardin et terrasse",
            "description_longue": "Au cœur du quartier des Chartrons, adresse prisée de Bordeaux, cette rare maison de maître de 142 m² sur terrain de 320 m² vous offrira une qualité de vie exceptionnelle. Construite en 1890 et entièrement rénovée en 2021, elle allie cachet de l'ancien et confort contemporain. Au rez-de-chaussée : entrée de caractère, salon-séjour de 45 m² avec cheminée, cuisine ouverte équipée Bulthaup, terrasse de 35 m² et jardin paysager. À l'étage : 4 chambres dont une suite parentale avec dressing, 2 salles de bains. Sous-sol complet avec cave à vin. DPE classe B. Maison sous vidéosurveillance, alarme. Idéal famille ou investisseur premium. À 5 minutes des quais de Garonne.",
            "description_courte": "Chartrons Bordeaux — Maison maître 142m², 5P, jardin 320m², terrasse, cave à vin. Rénovée 2021. DPE B. 750 000€.",
            "points_forts": '["Jardin paysager 320m² en pleine ville", "Rénovation complète 2021", "Cave à vin en sous-sol", "Quartier Chartrons — valeur sûre"]',
            "mentions_legales": "Surface : 142 m² (non copropriété). DPE : classe B (98 kWh/m²/an) — GES : classe A. Prix : 750 000€ FAI (dont honoraires 3,5% TTC).",
            "mots_cles_seo": '["maison Bordeaux Chartrons", "maison de maitre Bordeaux", "jardin Bordeaux centre", "rénovée Chartrons"]',
            "images_urls": '[]',
        },
        {
            "id": str(uuid4()),
            "lead_id": "",
            "client_id": client_id,
            "type_bien": "Appartement",
            "adresse": "22 avenue Jean Jaurès, Toulouse (31000)",
            "surface": 55.3,
            "nb_pieces": 2,
            "prix": 215000,
            "dpe": "D",
            "titre": "Toulouse Capitole — T2 refait à neuf, idéal investissement ou résidence",
            "description_longue": "À 10 minutes à pied de la Place du Capitole, ce T2 de 55,3 m² entièrement rénové en 2023 vous offre une opportunité rare. En pleine propriété au 2ème étage d'un immeuble de 1965 avec gardien, il se compose d'une entrée, d'un séjour lumineux de 22 m² donnant sur rue calme, d'une cuisine équipée semi-ouverte, d'une chambre de 13 m², d'une salle de bains rénovée, et de toilettes séparées. Double vitrage récent. Idéal premier achat ou investissement locatif (loyer estimé 750€/mois, rendement brut 4,2%). DPE classe D. Taxe foncière 980€/an. Proche métro Capitole.",
            "description_courte": "Toulouse Capitole — T2 55m², refait neuf 2023, gardien, métro à 200m. Idéal invest. locatif (750€/mois). DPE D. 215 000€.",
            "points_forts": '["Rénové 2023 — aucun travaux", "Rendement locatif 4,2%", "Métro Capitole à 200m", "Premier achat ou investissement"]',
            "mentions_legales": "Surface : 55,3 m² (loi Carrez). DPE : classe D (197 kWh/m²/an) — GES : classe D. Prix : 215 000€ FAI (dont honoraires 4% TTC).",
            "mots_cles_seo": '["appartement Toulouse Capitole", "T2 Toulouse centre", "investissement locatif Toulouse", "métro Capitole"]',
            "images_urls": '[]',
        },
    ]

    with get_connection() as conn:
        for listing in listings:
            conn.execute(
                """INSERT INTO listings
                   (id, lead_id, client_id, type_bien, adresse, surface, nb_pieces, prix, dpe,
                    titre, description_longue, description_courte, points_forts, mentions_legales,
                    mots_cles_seo, images_urls)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (id) DO NOTHING""",
                tuple(listing.values()),
            )


def seed_estimations(client_id: str):
    """Crée des estimations de démo."""
    estimations = [
        {
            "id": str(uuid4()),
            "lead_id": "",
            "client_id": client_id,
            "adresse": "45 rue Vendôme, Lyon 6e",
            "surface": 95.0,
            "type_bien": "Appartement T4",
            "prix_estime_bas": 540000,
            "prix_estime_central": 585000,
            "prix_estime_haut": 620000,
            "prix_m2_net": 6158,
            "loyer_mensuel_estime": 1850,
            "rentabilite_brute": 3.8,
            "delai_vente_estime_semaines": 8,
            "justification": "Bien en excellent état, DPE B, étage élevé avec ascenseur. Comparable DVF récent : 3 ventes en 2025 entre 5 900€ et 6 400€/m² dans le secteur Foch. Ajustement +5% pour DPE et +3% pour étage.",
            "mention_legale": "Estimation non opposable, donnée à titre indicatif conformément à la loi Hoguet.",
        },
        {
            "id": str(uuid4()),
            "lead_id": "",
            "client_id": client_id,
            "adresse": "12 rue des Capucins, Nantes",
            "surface": 63.5,
            "type_bien": "Appartement T3",
            "prix_estime_bas": 238000,
            "prix_estime_central": 258000,
            "prix_estime_haut": 275000,
            "prix_m2_net": 4063,
            "loyer_mensuel_estime": 890,
            "rentabilite_brute": 4.1,
            "delai_vente_estime_semaines": 10,
            "justification": "T3 en état correct, DPE C, secteur dynamique Nantes Centre. Prix marché : 3 800€-4 300€/m² selon état. Ajustement -3% DPE C vs B, +2% emplacement centre.",
            "mention_legale": "Estimation non opposable, donnée à titre indicatif conformément à la loi Hoguet.",
        },
    ]

    with get_connection() as conn:
        for est in estimations:
            conn.execute(
                """INSERT INTO estimations
                   (id, lead_id, client_id, adresse, surface, type_bien,
                    prix_estime_bas, prix_estime_central, prix_estime_haut, prix_m2_net,
                    loyer_mensuel_estime, rentabilite_brute, delai_vente_estime_semaines,
                    justification, mention_legale)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (id) DO NOTHING""",
                tuple(est.values()),
            )


def main():
    print("🌱 Population des données de démo...")

    # Clients agences
    CLIENTS = [
        {"id": "client_demo", "tier": "Starter"},
        {"id": "client_pro_demo", "tier": "Pro"},
        {"id": "client_elite_demo", "tier": "Elite"},
    ]

    # Leads pour le client principal (Starter)
    print(f"\n📋 Création de {len(LEADS_DATA)} leads...")
    for i, data in enumerate(LEADS_DATA):
        lead_id = str(uuid4())

        # Calcul dates réalistes
        days_ago = random.randint(0, 25)
        created = datetime.now() - timedelta(days=days_ago)
        rdv_date = created + timedelta(days=random.randint(2, 7)) if data["statut"] in (LeadStatus.RDV_BOOKÉ, LeadStatus.MANDAT, LeadStatus.VENDU) else None
        mandat_date = rdv_date + timedelta(days=random.randint(3, 10)) if data["statut"] in (LeadStatus.MANDAT, LeadStatus.VENDU) else None

        # Prochain followup pour nurturing
        prochain = datetime.now() + timedelta(days=random.randint(1, 7)) if data["statut"] == LeadStatus.NURTURING else None

        lead = Lead(
            id=lead_id,
            client_id="client_demo",
            prenom=data["prenom"],
            nom=data["nom"],
            telephone=data["tel"],
            email=data["email"],
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
            nurturing_step=random.randint(0, 2) if data.get("nurturing") else 0,
            prochain_followup=prochain,
            rdv_date=rdv_date,
            mandat_date=mandat_date,
            resume=data.get("resume", ""),
            created_at=created,
            updated_at=created,
        )
        create_lead(lead)

        # Conversations démo pour certains leads
        if data["tel"] in CONVERSATIONS_DEMO:
            for role, msg in CONVERSATIONS_DEMO[data["tel"]]:
                add_conversation_message(
                    lead_id=lead_id,
                    client_id="client_demo",
                    role=role,
                    contenu=msg,
                    canal=Canal.SMS,
                )

        print(f"  ✅ Lead {i+1}/{len(LEADS_DATA)} : {data['prenom']} {data['nom']} (score {data['score']}, {data['statut'].value})")

    # Quelques leads pour les autres clients
    print("\n📋 Création leads clients Pro et Elite...")
    for client in CLIENTS[1:]:
        for j in range(3):
            data = LEADS_DATA[j]
            lead = Lead(
                client_id=client["id"],
                prenom=data["prenom"],
                nom=data["nom"],
                telephone=f"+336999{j:05d}",
                email=data["email"],
                source=data["source"],
                projet=ProjetType(data["projet"]),
                localisation=data["loc"],
                budget=data["budget"],
                score=data["score"],
                statut=data["statut"],
                resume=data.get("resume", ""),
            )
            create_lead(lead)

    # Usage data
    print("\n📊 Création données d'usage...")
    seed_usage_data("client_demo",       "Starter", leads=187, voice=98.5, images=31, tokens=2_840_000, followups=612, listings=18, estimations=12)
    seed_usage_data("client_pro_demo",   "Pro",     leads=523, voice=312.0, images=89, tokens=8_200_000, followups=1842, listings=67, estimations=38)
    seed_usage_data("client_elite_demo", "Elite",   leads=1243, voice=887.0, images=312, tokens=28_000_000, followups=5621, listings=298, estimations=156)

    # Annonces et estimations
    print("\n📝 Création annonces et estimations...")
    seed_listings("client_demo")
    seed_estimations("client_demo")

    print("\n✅ Données de démo créées avec succès !")
    print("\n📌 Résumé :")
    print(f"   • {len(LEADS_DATA)} leads créés pour client_demo (Starter)")
    print("   • 3 annonces générées")
    print("   • 2 estimations avec rapport")
    print("   • Usage simulé pour 3 tiers (Starter, Pro, Elite)")
    print("\n🚀 Lancez le dashboard : streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
