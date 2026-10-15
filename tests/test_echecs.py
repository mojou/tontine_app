"""Échecs d'un cycle : plus de « Régulariser ». Tableau « Échecs à régler » (part + pénalité) et bouton « Régler »
(tout ou rien), dans le cycle et dans la séance. Trop-payé versé dans l'épargne à la fin du cycle."""
import html
import os
import re
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'ec.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import (Tontine, Member, ContributionType, TontineCycleDetail, CycleBeneficiary, Transaction,  # noqa: E402
                    Sanction, Seance)
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Echecs', 'slug': 'echecs', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@echecs.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})
for i, first in enumerate(['Marie', 'Awa', 'Kofi']):
    pres.post('/members/add', data={'first_name': first, 'last_name': 'Test', 'email': f'{first.lower()}@echecs.cm',
                                    'phone': f'69911122{i}', 'username': first.lower(), 'role': 'MEMBRE',
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context(), tenant_bypass():
    tid = Tontine.query.filter_by(slug='echecs').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
    level = ContributionType.query.filter_by(tontine_id=tid, category='TONTINE', amount=10000).first().id
pres.post('/tontine-cycles/add', data={'contribution_type_id': level, 'mode': 'TIRAGE', 'draw_now': 'on',
                                       **{f'hands_{ids[n]}': 1 for n in ('Marie', 'Awa', 'Kofi')}})
with app.app_context(), tenant_bypass():
    cid = TontineCycleDetail.query.filter_by(tontine_id=tid).one().id


def ctx():
    c = app.app_context()
    c.push()
    m.g.tenant_id = tid
    return c


def verser(turn, paid):
    data = {'expected_turn': turn, 'payment_mode': 'ESPECE', 'payers_form': '1'}
    data.update({f'paid_{ids[n]}': 'on' for n in paid})
    return pres.post(f'/tontine-cycles/{cid}/register-benefit', data=data, follow_redirects=True)


verser(1, ['Marie', 'Awa', 'Kofi'])
c = ctx()
b2 = db.session.get(TontineCycleDetail, cid).get_next_participant().member_id
unpaid = next(n for n in ('Marie', 'Awa', 'Kofi') if ids[n] != b2)
c.pop()
verser(2, [n for n in ('Marie', 'Awa', 'Kofi') if n != unpaid])

# ---------------------------------------------------------------- tableau des échecs sur la page du cycle
h = pres.get(f'/tontine-cycles/{cid}').get_data(as_text=True)
t = text(pres.get(f'/tontine-cycles/{cid}'))
check('Échecs à régler' in t and f'{unpaid} Test 10 000 (1 tour) 1 000 11 000 F' in t,
      f'cycle : {unpaid} apparaît dans « Échecs à régler » : part 10 000 + pénalité 1 000 = 11 000')
check('Régulariser' not in h and 'regulariser' not in h, 'plus de bouton « Régulariser » sur la page du cycle')
check('Confirmer le paiement' in h and 'name="amount"' not in h.split('Échecs à régler')[1].split('État des cotisations')[0],
      'le montant à régler est fixe (pas de paiement partiel dans un cycle)')

# ---------------------------------------------------------------- « Régler » depuis une séance
pres.post('/seances/add', data={'date': m.date.today().isoformat(), 'columns': [f'c{cid}']})
with app.app_context(), tenant_bypass():
    sid = Seance.query.filter_by(tontine_id=tid).one().id
t = text(pres.get(f'/seances/{sid}'))
check('Échecs à régler · Cycle #1' in t and '11 000 F' in t, "la séance affiche aussi l'échec à régler")
r = pres.post(f'/tontine-cycles/{cid}/regler/{ids[unpaid]}', data={'expected_total': '9999', 'seance_id': sid,
                                                                    'payment_mode': 'ESPECE'}, follow_redirects=True)
check('Le montant a changé' in text(r), 'montant différent du total dû : refusé')
r = pres.post(f'/tontine-cycles/{cid}/regler/{ids[unpaid]}', data={'expected_total': '11000', 'seance_id': sid,
                                                                    'payment_mode': 'ESPECE'})
check(r.status_code == 302 and r.headers['Location'].endswith(f'/seances/{sid}#echecs'), 'après « Régler » on revient à la séance')
c = ctx()
check(Transaction.query.filter_by(cycle_id=cid, member_id=ids[unpaid], type='TONTINE', seance_id=sid).first().amount == 10000,
      'la part de 10 000 est enregistrée dans le cycle et la séance')
check(Sanction.query.filter_by(member_id=ids[unpaid], status='PENDING').count() == 0
      and Transaction.query.filter_by(member_id=ids[unpaid], type='SANCTION').first().amount == 1000,
      "l'amende de 1 000 est payée en même temps")
ben2 = CycleBeneficiary.query.filter_by(cycle_id=cid, position=2).one()
check(ben2.net_amount == 30000 and not ben2.pending_amount, 'le bénéficiaire du tour 2 reçoit les 10 000 qui manquaient')
check(m.cycle_failures(db.session.get(TontineCycleDetail, cid)) == [], "plus d'échec à régler")
c.pop()
r = pres.post(f'/tontine-cycles/{cid}/regler/{ids[unpaid]}', data={'payment_mode': 'ESPECE'}, follow_redirects=True)
check("n'a rien à régler" in text(r), 'régler deux fois : refusé (rien à régler)')

# ---------------------------------------------------------------- trop-payé : versé dans l'épargne à la fin du cycle
with app.app_context(), tenant_bypass():
    db.session.add(Transaction(tontine_id=tid, member_id=ids['Marie'], type='TONTINE', amount=Decimal('15000'),
                               date=m.date.today(), cycle_id=cid, description='payé en trop'))
    db.session.commit()
r = verser(3, [])
c = ctx()
cy = db.session.get(TontineCycleDetail, cid)
st = m.cycle_contribution_status(cy)
ep = Transaction.query.filter_by(member_id=ids['Marie'], type='EPARGNE').first()
check(cy.status == 'TERMINE' and st['advance_total'] == 0 and ep is not None and ep.amount == 5000,
      "cycle terminé : les 5 000 payés en trop par Marie vont automatiquement dans son épargne")
c.pop()
check('versés dans l\'épargne' in text(r), 'un message le signale')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
