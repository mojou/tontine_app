# ============================================================
# RÉFÉRENTIEL FINANCIER : types d'opérations, fonds, cotisations
# ============================================================
#
# Source unique pour savoir si une transaction est une ENTRÉE ou une SORTIE
# de caisse et à quel fonds elle se rattache. Auparavant ces listes étaient
# recopiées dans plusieurs fichiers (avec des écarts).
#
# Les fonds reprennent l'organisation courante des tontines africaines
# (njangi, chilemba, tontines camerounaises, sénégalaises, ivoiriennes...) :
#   - TONTINE : cotisations rotatives, reversées intégralement au bénéficiaire du tour
#   - CAISSE  : caisse générale (présences, fonds de caisse, adhésions, amendes,
#               intérêts d'emprunt) qui finance les prêts et le fonctionnement
#   - EPARGNE : épargne individuelle ("banque"), restituée en fin d'exercice
#   - SECOURS : caisse de solidarité (décès, maladie, naissance, mariage)
#   - PROJET  : caisse projet / investissement collectif

from collections import OrderedDict
from decimal import Decimal

IN, OUT = 'ENTREE', 'SORTIE'

FUNDS = OrderedDict([
    ('CAISSE', 'Caisse générale'),
    ('TONTINE', 'Tontine (rotative)'),
    ('EPARGNE', 'Épargne des membres'),
    ('SECOURS', 'Caisse de secours'),
    ('PROJET', 'Caisse projet'),
])

# code -> (libellé, sens, fonds)
TRANSACTION_TYPES = OrderedDict([
    ('TONTINE', ('Cotisation tontine', IN, 'TONTINE')),
    ('PRESENCE', ('Droit de présence (séance)', IN, 'CAISSE')),
    ('EPARGNE', ('Épargne', IN, 'EPARGNE')),
    ('FONDS_CAISSE', ('Fonds de caisse', IN, 'CAISSE')),
    ('ADHESION', ("Frais d'adhésion", IN, 'CAISSE')),
    ('SECOURS', ('Cotisation caisse de secours', IN, 'SECOURS')),
    ('ACCUEIL', ('Accueil / collation de séance', IN, 'CAISSE')),
    ('PROJET', ('Cotisation projet', IN, 'PROJET')),
    ('AUTRE_COTISATION', ('Autre cotisation', IN, 'CAISSE')),
    ('SANCTION', ('Sanction / amende', IN, 'CAISSE')),
    ('ENCHERE', ("Mise d'enchère (retenue sur cagnotte)", IN, 'CAISSE')),
    ('REMBOURSEMENT', ("Remboursement d'emprunt", IN, 'CAISSE')),
    ('SORTIE_LOAN', ("Décaissement d'emprunt", OUT, 'CAISSE')),
    ('BENEFICE_TONTINE', ('Cagnotte versée au bénéficiaire', OUT, 'TONTINE')),
    ('AIDE', ('Aide sociale versée', OUT, 'SECOURS')),
    ('RETRAIT_EPARGNE', ("Restitution d'épargne", OUT, 'EPARGNE')),
    ('RESTITUTION_TONTINE', ("Avance de tontine rendue", OUT, 'TONTINE')),
    ('PARTAGE', ('Part des bénéfices (fin d\'exercice)', OUT, 'CAISSE')),
    ('DEPENSE', ('Dépense de fonctionnement', OUT, 'CAISSE')),
])

PAYMENT_MODES = OrderedDict([
    ('ESPECE', 'Espèces'),
    ('ORANGE_MONEY', 'Orange Money'),
    ('MTN_MOBILE', 'MTN Mobile Money'),
    ('WAVE', 'Wave'),
    ('MOOV_MONEY', 'Moov Money'),
    ('VIREMENT', 'Virement bancaire'),
])
MOBILE_MODES = {'ORANGE_MONEY', 'MTN_MOBILE', 'WAVE', 'MOOV_MONEY'}

# Modes d'attribution de la cagnotte dans un cycle
CYCLE_MODES = OrderedDict([
    ('TIRAGE', "Tirage au sort de l'ordre de passage"),
    ('ENCHERE', 'Enchères à chaque tour (le plus offrant reçoit la cagnotte, sa mise va en caisse)'),
])

# Écart entre deux tours selon la périodicité de la cotisation
FREQUENCY_DAYS = {'HEBDOMADAIRE': 7, 'PAR_SEANCE': 7, 'BIMENSUEL': 14, 'MENSUEL': 30, 'ANNUEL': 365}

INFLOW_TYPES = [code for code, (_, sens, _) in TRANSACTION_TYPES.items() if sens == IN]
OUTFLOW_TYPES = [code for code, (_, sens, _) in TRANSACTION_TYPES.items() if sens == OUT]

# Types qu'un trésorier peut saisir à la main (les autres sont générés par
# les modules dédiés : emprunts, sanctions, aides, cycles)
MANUAL_TYPES = ['TONTINE', 'PRESENCE', 'EPARGNE', 'FONDS_CAISSE', 'ADHESION', 'SECOURS', 'ACCUEIL',
                'PROJET', 'AUTRE_COTISATION', 'RETRAIT_EPARGNE', 'DEPENSE']

# Catégories utilisables pour une rubrique de cotisation
CONTRIBUTION_CATEGORIES = ['TONTINE', 'PRESENCE', 'EPARGNE', 'FONDS_CAISSE', 'ADHESION', 'SECOURS',
                           'ACCUEIL', 'PROJET', 'AUTRE_COTISATION']

FREQUENCIES = OrderedDict([
    ('UNIQUE', 'Une seule fois'),
    ('PAR_SEANCE', 'À chaque séance'),
    ('HEBDOMADAIRE', 'Chaque semaine'),
    ('BIMENSUEL', 'Tous les 15 jours'),
    ('MENSUEL', 'Chaque mois'),
    ('ANNUEL', 'Chaque année'),
    ('LIBRE', 'Libre / volontaire'),
])


# Explication en langage simple de chaque type (formulaire de saisie, fiche membre)
TYPE_HINTS = {
    'TONTINE': "Part versée au cycle de tontine : elle est reversée en entier au bénéficiaire du tour.",
    'PRESENCE': "Droit payé à chaque séance ; il alimente la caisse générale.",
    'EPARGNE': "Argent mis de côté par le membre à titre personnel (« banque ») : il reste à lui "
               "et lui est rendu en fin d'exercice. Ce n'est PAS le fonds de caisse.",
    'FONDS_CAISSE': "Contribution obligatoire à la caisse générale (finance les prêts et le fonctionnement).",
    'ADHESION': "Frais payés une seule fois à l'entrée dans la tontine.",
    'SECOURS': "Cotisation à la caisse de solidarité qui finance les aides (décès, maladie, naissance...).",
    'ACCUEIL': "Participation à la collation / l'accueil de la séance.",
    'PROJET': "Cotisation pour un projet ou un investissement collectif.",
    'AUTRE_COTISATION': "Autre versement à la caisse générale.",
    'SANCTION': "Paiement d'une amende.",
    'ENCHERE': "Mise de l'enchère retenue sur la cagnotte ; elle va en caisse.",
    'REMBOURSEMENT': "Remboursement d'un emprunt.",
    'SORTIE_LOAN': "Argent prêté au membre (sortie de caisse).",
    'BENEFICE_TONTINE': "Cagnotte du cycle versée au membre (sortie).",
    'AIDE': "Aide sociale versée au membre par la caisse de secours (sortie).",
    'RETRAIT_EPARGNE': "Épargne rendue au membre (sortie).",
    'RESTITUTION_TONTINE': "Cotisation de tontine payée en trop, rendue au membre ou versée dans son épargne (sortie).",
    'PARTAGE': "Part des bénéfices de fin d'exercice versée au membre (sortie).",
    'DEPENSE': "Dépense de fonctionnement de la tontine (sortie).",
}


def type_hint(code):
    return TYPE_HINTS.get(code, '')


def type_label(code):
    return TRANSACTION_TYPES.get(code, (code, IN, 'CAISSE'))[0]


def is_outflow(code):
    return code in OUTFLOW_TYPES


def fund_of(code):
    return TRANSACTION_TYPES.get(code, (code, IN, 'CAISSE'))[2]


def fund_balances(type_totals):
    """Solde de chaque fonds à partir des totaux par type : {type: montant} -> {fonds: solde}"""
    balances = OrderedDict((code, Decimal('0')) for code in FUNDS)
    for code, amount in type_totals.items():
        amount = Decimal(str(amount or 0))
        fund = fund_of(code)
        balances[fund] = balances.get(fund, Decimal('0')) + (-amount if is_outflow(code) else amount)
    return balances


def default_contribution_types(tontine):
    """Rubriques proposées à la création d'une tontine (modifiables ensuite).
    Montants indicatifs inspirés des pratiques courantes en Afrique centrale et de l'Ouest."""
    presence = tontine.presence_amount if tontine.presence_amount is not None else Decimal('1050')
    fonds = tontine.fonds_caisse_amount if tontine.fonds_caisse_amount is not None else Decimal('5000')
    return [
        dict(name='Tontine 10 000', category='TONTINE', amount=Decimal('10000'), frequency='BIMENSUEL', is_mandatory=False,
             description="Niveau de cotisation : part versée à chaque tour ; la cagnotte revient au bénéficiaire du tour."),
        dict(name='Droit de présence', category='PRESENCE', amount=presence, frequency='PAR_SEANCE', is_mandatory=True,
             description='Payé à chaque séance ; alimente la caisse générale.'),
        dict(name='Fonds de caisse', category='FONDS_CAISSE', amount=fonds, frequency='UNIQUE', is_mandatory=True,
             description="Versé une fois à l'entrée ; sert de fonds de roulement et de garantie."),
        dict(name="Frais d'adhésion", category='ADHESION', amount=Decimal('2000'), frequency='UNIQUE', is_mandatory=True,
             description="Droit d'entrée non remboursable (carte, registre, frais de bureau)."),
        dict(name='Épargne', category='EPARGNE', amount=Decimal('0'), frequency='LIBRE', is_mandatory=False,
             description="Montant libre déposé à la « banque » de la tontine ; restitué en fin d'exercice avec la part des intérêts."),
        dict(name='Caisse de secours', category='SECOURS', amount=Decimal('1000'), frequency='MENSUEL', is_mandatory=True,
             description='Solidarité : décès, maladie, naissance, mariage.'),
        dict(name='Accueil / collation', category='ACCUEIL', amount=Decimal('500'), frequency='PAR_SEANCE', is_mandatory=False,
             description="Participation à la réception de la séance (boissons, repas de l'hôte)."),
        dict(name='Caisse projet', category='PROJET', amount=Decimal('0'), frequency='LIBRE', is_mandatory=False,
             description='Investissement collectif (terrain, matériel, activité génératrice de revenus).'),
    ]
