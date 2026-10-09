# ============================================================
# ABONNEMENT DES TONTINES (facturation de la plateforme)
# ============================================================
# Règles :
#   - jusqu'à FREE_MEMBERS membres actifs : gratuit ;
#   - au-delà : PRICE_PER_MEMBER FCFA par membre actif et par mois, pour TOUS les membres
#     (ex. 15 membres -> 15 x 200 = 3 000 FCFA / mois) ;
#   - le super-admin peut offrir la version payante (sans limite) ou des mois gratuits ;
#   - à l'échéance non payée : GRACE_DAYS jours de grâce, puis lecture seule
#     (les données ne sont jamais supprimées).

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

FREE_MEMBERS = 10
PRICE_PER_MEMBER = 200
GRACE_DAYS = 7
MAX_MONTHS = 12          # paiement de 1 à 12 mois d'avance

# États
OK, GRACE, READ_ONLY = 'OK', 'GRACE', 'LECTURE_SEULE'


def add_months(day, months):
    return day + relativedelta(months=months)


def monthly_price(members):
    """Prix mensuel selon le nombre de membres actifs (0 si gratuit)"""
    return 0 if members <= FREE_MEMBERS else PRICE_PER_MEMBER * members


def status(tontine, members, today=None):
    """Situation d'abonnement d'une tontine. Retourne un dict :
    plan      : GRATUIT | OFFERT | PAYANT
    state     : OK | GRACE | LECTURE_SEULE
    monthly   : prix mensuel actuel
    covered_until : date jusqu'à laquelle la tontine est couverte (payée ou offerte)
    free_until    : fin des mois offerts (si en cours)
    grace_end     : dernier jour de grâce (si impayé)"""
    today = today or date.today()
    monthly = monthly_price(members)
    info = {'members': members, 'monthly': monthly, 'plan': 'PAYANT', 'state': OK, 'covered_until': None,
            'free_until': tontine.free_until if tontine.free_until and tontine.free_until >= today else None,
            'grace_end': None, 'free_members': FREE_MEMBERS, 'price_per_member': PRICE_PER_MEMBER}
    if tontine.billing_offered:
        info['plan'] = 'OFFERT'
        return info
    if monthly == 0:
        info['plan'] = 'GRATUIT'
        return info
    covered = max([d for d in (tontine.paid_until, tontine.free_until) if d], default=None)
    info['covered_until'] = covered
    if covered and covered >= today:
        return info
    start = (covered + timedelta(days=1)) if covered else (tontine.billing_started_on or today)
    info['grace_end'] = start + timedelta(days=GRACE_DAYS - 1)
    info['state'] = GRACE if today <= info['grace_end'] else READ_ONLY
    return info


def next_period(tontine, months, today=None):
    """Période couverte par un paiement validé de `months` mois : (début, fin)"""
    today = today or date.today()
    covered = max([d for d in (tontine.paid_until, tontine.free_until) if d], default=None)
    start = covered + timedelta(days=1) if covered and covered >= today else today
    return start, add_months(start, months) - timedelta(days=1)
