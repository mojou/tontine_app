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
#   - EPARGNE : épargne individuelle ("banque"), restituée en fin d'année
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
    ('PRESENCE', ('Droit de présence (réunion)', IN, 'CAISSE')),
    ('EPARGNE', ('Épargne', IN, 'EPARGNE')),
    ('FONDS_CAISSE', ('Fonds de caisse', IN, 'CAISSE')),
    ('ADHESION', ("Frais d'adhésion", IN, 'CAISSE')),
    ('SECOURS', ('Cotisation caisse de secours', IN, 'SECOURS')),
    ('ACCUEIL', ('Accueil / collation de séance', IN, 'CAISSE')),
    ('PROJET', ('Cotisation projet', IN, 'PROJET')),
    ('AUTRE_COTISATION', ('Autre cotisation', IN, 'CAISSE')),
    ('SANCTION', ('Sanction / amende', IN, 'CAISSE')),
    ('ENCHERE', ("Enchère (prise sur la cagnotte)", IN, 'CAISSE')),
    ('REMBOURSEMENT', ("Remboursement d'emprunt", IN, 'CAISSE')),
    ('SORTIE_LOAN', ("Prêt remis au membre", OUT, 'CAISSE')),
    ('BENEFICE_TONTINE', ('Cagnotte versée au bénéficiaire', OUT, 'TONTINE')),
    ('AIDE', ('Aide sociale versée', OUT, 'SECOURS')),
    ('RETRAIT_EPARGNE', ("Épargne rendue au membre", OUT, 'EPARGNE')),
    ('RESTITUTION_TONTINE', ("Avance de tontine rendue", OUT, 'TONTINE')),
    ('PARTAGE', ('Part des bénéfices (fin d\'année)', OUT, 'CAISSE')),
    ('DEPENSE', ('Dépense de la tontine', OUT, 'CAISSE')),
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
    ('ENCHERE', 'Enchères à chaque tour (celui qui propose le plus reçoit la cagnotte ; ce qu’il propose va en caisse)'),
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
    ('LIBRE', 'Quand on veut'),
])


# Explication en langage simple de chaque type (formulaire de saisie, fiche membre)
TYPE_HINTS = {
    'TONTINE': "Part de la tontine : elle est donnée en entier à celui qui bouffe ce tour.",
    'PRESENCE': "Somme payée à chaque réunion ; elle va dans la caisse générale.",
    'EPARGNE': "Argent que le membre met de côté pour lui-même (« banque ») : il reste à lui "
               "et on le lui rend en fin d'année. Ce n'est PAS le fonds de caisse.",
    'FONDS_CAISSE': "Somme obligatoire versée à la caisse générale (elle sert aux prêts et aux dépenses de la tontine).",
    'ADHESION': "Frais payés une seule fois à l'entrée dans la tontine.",
    'SECOURS': "Cotisation à la caisse de solidarité qui finance les aides (décès, maladie, naissance...).",
    'ACCUEIL': "Participation à la collation / l'accueil de la séance.",
    'PROJET': "Cotisation pour un projet commun.",
    'AUTRE_COTISATION': "Autre versement à la caisse générale.",
    'SANCTION': "Paiement d'une amende.",
    'ENCHERE': "Somme proposée à l'enchère, prise sur la cagnotte ; elle va en caisse.",
    'REMBOURSEMENT': "Remboursement d'un emprunt.",
    'SORTIE_LOAN': "Argent prêté au membre (sort de la caisse).",
    'BENEFICE_TONTINE': "Cagnotte donnée au membre (sort de la caisse).",
    'AIDE': "Aide donnée au membre par la caisse de secours (sort de la caisse).",
    'RETRAIT_EPARGNE': "Épargne rendue au membre (sort de la caisse).",
    'RESTITUTION_TONTINE': "Cotisation payée en trop, rendue au membre ou mise dans son épargne (sort de la caisse).",
    'PARTAGE': "Part des bénéfices de fin d'année donnée au membre (sort de la caisse).",
    'DEPENSE': "Dépense de la tontine (sort de la caisse).",
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
             description="Somme payée une fois pour entrer, qu'on ne rend pas (carte, cahier, frais du bureau)."),
        dict(name='Épargne', category='EPARGNE', amount=Decimal('0'), frequency='LIBRE', is_mandatory=False,
             description="Somme libre mise à la « banque » de la tontine ; on vous la rend en fin d'année avec votre part des intérêts."),
        dict(name='Caisse de secours', category='SECOURS', amount=Decimal('1000'), frequency='MENSUEL', is_mandatory=True,
             description='Solidarité : décès, maladie, naissance, mariage.'),
        dict(name='Accueil / collation', category='ACCUEIL', amount=Decimal('500'), frequency='PAR_SEANCE', is_mandatory=False,
             description="Participation à la réception de la séance (boissons, repas de l'hôte)."),
        dict(name='Caisse projet', category='PROJET', amount=Decimal('0'), frequency='LIBRE', is_mandatory=False,
             description='Investissement collectif (terrain, matériel, activité génératrice de revenus).'),
    ]
