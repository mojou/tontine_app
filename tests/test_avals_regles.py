"""Règles pour avaliser : à jour en réunion, épargne >= somme demandée / 3, pas de dette d'emprunt."""
import html
import os
import sys
from datetime import date
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'ar.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, Loan, LoanGuarantor, Sanction, ContributionType  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return html.unescape(r.get_data(as_text=True))


def login(username):
    c = app.test_client()
    c.post('/login', data={'tontine': 'garants', 'username': username, 'password': 'Passw0rd1'})
    return c


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Garants', 'slug': 'garants', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@garants.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Helene2026', 'password_confirm': 'Helene2026'})
names = ['Marc', 'Awa', 'Kofi', 'Ines', 'Yao']
for i, first in enumerate(names):
    pres.post('/members/add', data={'first_name': first, 'last_name': 'Test', 'email': f'{first.lower()}@garants.cm',
                                    'phone': f'69911122{i}', 'username': first.lower(), 'role': 'MEMBRE',
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='garants').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
    rub = {r.category: r.id for r in ContributionType.query.filter_by(tontine_id=tid).all()}


def pay(name, category, amount):
    pres.post('/transactions/add', data={'member_id': ids[name], 'type': category, 'contribution_type_id': rub[category],
                                         'amount': amount, 'payment_mode': 'ESPECE', 'description': f'{category} {name}'})


# Tout le monde paie son fonds de caisse ; épargnes différentes
for name in names:
    pay(name, 'FONDS_CAISSE', 5000)
pay('Awa', 'EPARGNE', 10000)      # peut avaliser jusqu'à 30 000
pay('Kofi', 'EPARGNE', 5000)      # 15 000 seulement
pay('Ines', 'EPARGNE', 50000)     # beaucoup d'épargne mais une amende impayée
pay('Yao', 'EPARGNE', 50000)      # beaucoup d'épargne mais un emprunt en cours
pay('Marc', 'EPARGNE', 10000)
with app.app_context():
    db.session.add(Sanction(tontine_id=tid, member_id=ids['Ines'], type_sanction='RETARD_REUNION', amount=Decimal('500'),
                            sanction_date=date.today(), status='PENDING', description='Retard'))
    db.session.add(Loan(tontine_id=tid, member_id=ids['Yao'], amount=Decimal('10000'), interest=Decimal('0'),
                        total_amount=Decimal('10000'), amount_paid=Decimal('0'), request_date=date.today(), status='ACTIF'))
    db.session.commit()

marc = login('marc')


def request_loan(amount, guarantors):
    marc.post('/loan/request', data={'member_id': ids['Marc'], 'amount': amount, 'duration_months': 2,
                                     'guarantor_ids': [ids[g] for g in guarantors]})
    with app.app_context():
        return Loan.query.filter_by(member_id=ids['Marc'], status='PENDING').first()


# ---------------------------------------------------------------- épargne = somme demandée / 3
check(request_loan(30000, ['Kofi']) is None, "Kofi (5 000 d'épargne) ne peut pas avaliser 30 000 (il faut 10 000)")
r = marc.post('/loan/request', data={'member_id': ids['Marc'], 'amount': 30000, 'duration_months': 2,
                                     'guarantor_ids': [ids['Kofi']]}, follow_redirects=True)
check("n'a pas assez d'épargne : 10 000 FCFA exigés" in body(r) and '5 000 FCFA disponibles' in body(r),
      'le message explique la règle du tiers et les montants')

# ---------------------------------------------------------------- à jour en réunion
check(request_loan(15000, ['Ines']) is None, 'Ines (amende impayée) ne peut pas avaliser')
r = marc.post('/loan/request', data={'member_id': ids['Marc'], 'amount': 15000, 'duration_months': 2,
                                     'guarantor_ids': [ids['Ines']]}, follow_redirects=True)
check("n'est pas à jour : 500 FCFA d'amendes impayées" in body(r), "raison affichée : amende impayée")

# ---------------------------------------------------------------- pas de dette d'emprunt
check(request_loan(15000, ['Yao']) is None, 'Yao (emprunt en cours) ne peut pas avaliser')
r = marc.post('/loan/request', data={'member_id': ids['Marc'], 'amount': 15000, 'duration_months': 2,
                                     'guarantor_ids': [ids['Yao']]}, follow_redirects=True)
check('a lui-même un emprunt en cours' in body(r), 'raison affichée : emprunt en cours')

# ---------------------------------------------------------------- liste de choix
h = body(marc.get('/loans'))
check("Awa Test : peut avaliser jusqu'à 30 000 FCFA" in h, "la liste indique la capacité d'Awa (3 x 10 000)")
check('Ines Test : ne peut pas avaliser' in h and 'Yao Test : ne peut pas avaliser' in h, 'les membres non éligibles sont grisés')
check('au moins égale au tiers de la somme demandée' in h, 'la règle est rappelée dans le formulaire')

# ---------------------------------------------------------------- cas valide
loan = request_loan(30000, ['Awa'])
check(loan is not None, 'Awa (10 000 d\'épargne, à jour, sans dette) avalise 30 000')
with app.app_context():
    g_awa = LoanGuarantor.query.filter_by(member_id=ids['Awa']).one().id
    m.g.tenant_id = tid
    problems, available = m.aval_standing(db.session.get(Member, ids['Awa']))
    check(available == 0, f"l'épargne d'Awa est engagée pour cet aval ({available} disponible)")

# même épargne : pas deux avals en même temps
with app.app_context():
    m.g.tenant_id = tid
    check(m.aval_problems(db.session.get(Member, ids['Awa']), 30000) != [],
          "l'épargne déjà engagée ne garantit pas un second emprunt")
    check(m.aval_problems(db.session.get(Member, ids['Awa']), 30000, ignore_guarantee_id=g_awa) == [],
          'sans compter son propre aval, Awa reste éligible')

# ---------------------------------------------------------------- re-vérification à l'acceptation
with app.app_context():
    db.session.add(Sanction(tontine_id=tid, member_id=ids['Awa'], type_sanction='RETARD_REUNION', amount=Decimal('1000'),
                            sanction_date=date.today(), status='PENDING', description='Absence'))
    db.session.commit()
awa = login('awa')
r = awa.post(f'/avals/{g_awa}/respond', data={'action': 'accept'}, follow_redirects=True)
with app.app_context():
    check(db.session.get(LoanGuarantor, g_awa).status == 'EN_ATTENTE', "Awa n'est plus à jour : son acceptation est refusée")
check("Vous ne pouvez pas avaliser cet emprunt" in body(r) and "1 000 FCFA d'amendes impayées" in body(r), 'raison expliquée à Awa')
with app.app_context():
    Sanction.query.filter_by(member_id=ids['Awa'], status='PENDING').one().status = 'PAID'
    db.session.commit()
awa.post(f'/avals/{g_awa}/respond', data={'action': 'accept'})
with app.app_context():
    check(db.session.get(LoanGuarantor, g_awa).status == 'ACCEPTE', 'amende payée : Awa peut accepter')

# ---------------------------------------------------------------- ajout d'avaliste depuis la page Avals
h = body(marc.get('/avals'))
check('Kofi Test : épargne insuffisante pour cet emprunt' in h, "page Avals : Kofi grisé (épargne insuffisante pour 30 000)")

# ---------------------------------------------------------------- cotisation de tontine en retard
from models import TontineCycleDetail, Transaction  # noqa: E402
with app.app_context():
    lv = ContributionType.query.filter_by(tontine_id=tid, category='TONTINE').first().id
pres.post('/tontine-cycles/add', data={'contribution_type_id': lv, 'mode': 'TIRAGE', 'draw_now': 'on',
                                       **{f'hands_{ids[n]}': 1 for n in ('Kofi', 'Ines', 'Yao')}})
with app.app_context():
    cyc = TontineCycleDetail.query.filter_by(tontine_id=tid).one().id
pres.post(f'/tontine-cycles/{cyc}/register-benefit', data={'expected_turn': 1, 'payment_mode': 'ESPECE', 'confirm_offline': 'on'})
with app.app_context():
    m.g.tenant_id = tid
    kofi = db.session.get(Member, ids['Kofi'])
    check(m.aval_problems(kofi, 3000) == [], 'Kofi à jour sur le cycle (tour 1 encaissé) : peut avaliser 3 000')
    db.session.delete(Transaction.query.filter_by(cycle_id=cyc, member_id=ids['Kofi'], type='TONTINE').first())
    db.session.commit()
    reasons = m.aval_problems(db.session.get(Member, ids['Kofi']), 3000)
    check(any('cotisations en retard' in r for r in reasons), f'cotisation du tour 1 manquante : Kofi refusé ({reasons})')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
