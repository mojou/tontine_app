"""Nouvelle règle des emprunts : intérêts tous les 3 mois sur le capital restant (l'emprunt reste en cours),
capital remboursable en partie, 12 mois au plus, rouge si les intérêts ne sont pas payés à temps."""
import html
import os
import re
import sys
from datetime import date, timedelta
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'et.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, Loan, Transaction  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402
from dateutil.relativedelta import relativedelta  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Pret', 'slug': 'pret', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@pret.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})
pres.post('/members/add', data={'first_name': 'Marc', 'last_name': 'Test', 'email': 'marc@pret.cm', 'phone': '699111220',
                                'username': 'marc', 'role': 'MEMBRE', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context(), tenant_bypass():
    t = Tontine.query.filter_by(slug='pret').one()
    tid = t.id
    t.loan_interest_rate = Decimal('10')
    t.guarantee_threshold = Decimal('10000000')     # pas d'avaliste exigé dans ce test
    marc = Member.query.filter_by(tontine_id=tid, first_name='Marc').one().id
    for kind, amount in (('FONDS_CAISSE', 5000), ('EPARGNE', 40000)):
        db.session.add(Transaction(tontine_id=tid, member_id=marc, type=kind, amount=Decimal(amount), date=date.today(),
                                   description='test'))
    db.session.commit()


def loan():
    with app.app_context(), tenant_bypass():
        return Loan.query.filter_by(tontine_id=tid, member_id=marc).order_by(Loan.id.desc()).first()


def set_due(days_from_today):
    with app.app_context(), tenant_bypass():
        lo = Loan.query.filter_by(tontine_id=tid, member_id=marc).one()
        lo.next_due_date = date.today() + timedelta(days=days_from_today)
        db.session.commit()


def pay_interest():
    lo = loan()
    return pres.post(f'/loans/{lo.id}/interets', data={'payment_mode': 'ESPECE', 'expected_due': lo.next_due_date.isoformat()},
                     follow_redirects=True)


def repay(amount):
    lo = loan()
    return pres.post(f'/loans/{lo.id}/repay', data={'amount': amount, 'payment_mode': 'ESPECE',
                                                    'expected_paid': str(float(lo.amount_paid or 0))}, follow_redirects=True)


# ---------------------------------------------------------------- demande et accord
h = text(pres.get('/loans'))
check('tous les 3 mois' in h and '12 mois' in h, 'formulaire de demande : la règle (intérêts tous les 3 mois, 12 mois au plus) est expliquée')
pres.post('/loan/request', data={'member_id': marc, 'amount': 100000, 'duration_months': 12})
lo = loan()
check(lo.is_quarterly and lo.total_amount == 100000 and lo.interest == 10000,
      'nouvel emprunt de 100 000 : capital 100 000, intérêts 10 000 par trimestre (10 %)')
pres.post(f'/loans/{lo.id}/approve')
lo = loan()
check(lo.status == 'ACTIF' and lo.next_due_date == date.today() + relativedelta(months=3)
      and lo.end_date == date.today() + relativedelta(months=12), 'accordé : intérêts dans 3 mois, capital au plus tard dans 12 mois')
h = text(pres.get('/loans'))
check('Payer les intérêts (10 000 F)' in h and 'Rembourser du capital' in h, 'boutons « Payer les intérêts » et « Rembourser du capital »')

# ---------------------------------------------------------------- tout solder exige les intérêts du trimestre commencé
r = repay(100000)
check('payez les intérêts du trimestre commencé (10 000 FCFA)' in text(r) and loan().amount_paid == 0,
      'solder tout de suite : il faut d\'abord payer les intérêts du trimestre commencé')

# ---------------------------------------------------------------- intérêts payés : l'emprunt reste en cours, échéance + 3 mois
before = loan().next_due_date
r = pay_interest()
lo = loan()
check('Intérêts de 10 000 FCFA payés' in text(r) and lo.next_due_date == before + relativedelta(months=3) and lo.status == 'ACTIF',
      'intérêts payés : l\'emprunt reste en cours, prochaine échéance 3 mois plus tard')
r = pres.post(f'/loans/{lo.id}/interets', data={'payment_mode': 'ESPECE', 'expected_due': before.isoformat()}, follow_redirects=True)
check('déjà été payés' in text(r), 'double clic : les intérêts ne sont pas payés deux fois')

# ---------------------------------------------------------------- remboursement partiel du capital
r = repay(40000)
lo = loan()
check(lo.remaining_amount == 60000 and lo.status == 'ACTIF' and 'les prochains intérêts baissent à 6 000' in text(r),
      'remboursement partiel de 40 000 : reste 60 000, les intérêts suivants baissent à 6 000')

# ---------------------------------------------------------------- intérêts non payés à temps : rouge
set_due(-1)
h = text(pres.get('/loans'))
check(loan().status == 'OVERDUE' and 'En retard' in h and 'dus depuis' in h, 'échéance dépassée sans intérêts payés : emprunt en rouge (En retard)')
r = pay_interest()
check(loan().status == 'ACTIF' and 'Intérêts de 6 000 FCFA payés' in text(r), 'intérêts payés (6 000) : l\'emprunt redevient « en cours »')
check('dus depuis' not in text(pres.get('/loans')), 'plus de rouge dans la liste')

# ---------------------------------------------------------------- solder : intérêts du trimestre commencé puis capital
r = repay(60000)
check('payez les intérêts du trimestre commencé' in text(r), 'le nouveau trimestre a commencé : ses intérêts avant de solder')
pay_interest()
r = repay(60000)
check(loan().status == 'REMBOURSE' and 'entièrement remboursé' in text(r), 'intérêts payés puis capital : emprunt terminé')

# ---------------------------------------------------------------- les intérêts reçus alimentent le partage de l'épargne
with app.app_context():
    m.g.tenant_id = tid
    total, detail = m.loan_interest_received(date(date.today().year, 1, 1), date(date.today().year, 12, 31))
    check(total == 22000 and detail[0]['repaid'] == 100000,
          f'intérêts reçus dans l\'année : 10 000 + 6 000 + 6 000 = 22 000 ({total}) ; capital remboursé 100 000 non compté comme intérêt')

# ---------------------------------------------------------------- dernier trimestre : il ne reste que le capital
pres.post('/loan/request', data={'member_id': marc, 'amount': 30000, 'duration_months': 12})
lo2 = loan()
pres.post(f'/loans/{lo2.id}/approve')
with app.app_context(), tenant_bypass():
    x = db.session.get(Loan, lo2.id)
    x.next_due_date = x.end_date
    db.session.commit()
r = pay_interest()
lo2 = loan()
check(lo2.next_due_date is None and "c'étaient les derniers" in text(r), 'derniers intérêts payés : il ne reste que le capital, à rendre avant la fin des 12 mois')
with app.app_context(), tenant_bypass():
    x = db.session.get(Loan, lo2.id)
    x.end_date = date.today() - timedelta(days=1)
    db.session.commit()
pres.get('/loans')
check(loan().status == 'OVERDUE', '12 mois dépassés avec du capital non rendu : emprunt en rouge')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
