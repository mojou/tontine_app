import os
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'cy.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import (Tontine, Member, User, TontineCycleDetail, CycleParticipant, CycleBeneficiary,  # noqa: E402
                    Transaction, ContributionType, Sanction)

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return r.get_data(as_text=True)


# ---------------------------------------------------------------- reprise du cycle JSB existant
with app.app_context():
    jsb = Tontine.query.filter_by(slug='jsb').one()
    jsb_id = jsb.id
    old = TontineCycleDetail.query.filter_by(tontine_id=jsb_id).first()
    old_id = old.id if old else None
    if old:
        parts = old.participants
        served = [p for p in parts if p.served]
        check(len(parts) >= len(served) == old.beneficiaries_count, f'cycle JSB repris : {len(parts)} participations, {len(served)} servies')
        check(all(b.participant_id for b in old.benefits.all()), 'bénéficiaires reliés à leur participation')
    u = User.query.filter_by(tontine_id=jsb_id, username='president').one()
    u.set_password('JsbPass123')
    db.session.commit()

c = app.test_client()
assert c.post('/login', data={'tontine': 'jsb', 'username': 'president', 'password': 'JsbPass123'}).status_code == 302
for url in ['/tontine-cycles', '/tontine-cycles/add', '/tirages', '/dashboard']:
    r = c.get(url)
    check(r.status_code == 200, f'GET {url}')
if old_id:
    check(c.get(f'/tontine-cycles/{old_id}').status_code == 200, 'détail du cycle repris')
    check(c.get(f'/tontine-cycles/{old_id}/tirage').status_code == 200, 'tirage du cycle repris')

# ---------------------------------------------------------------- niveaux de cotisation dans les paramètres
for amount in (1000, 20000):
    c.post('/cotisations/rubriques/add', data={'name': f'Tontine {amount}', 'category': 'TONTINE', 'amount': str(amount),
                                               'frequency': 'BIMENSUEL', 'next': '/parametres'})
with app.app_context():
    levels = {int(l.amount): l.id for l in ContributionType.query.filter_by(tontine_id=jsb_id, category='TONTINE').all()}
    check({1000, 10000, 20000} <= set(levels), f'3 niveaux : {sorted(levels)}')
    members = Member.query.filter_by(tontine_id=jsb_id, is_active=True, status='ACTIF').order_by(Member.id).all()
    mids = [x.id for x in members]
h = body(c.get('/parametres'))
check('Niveaux de cotisation' in h and '20 000' in h, 'niveaux visibles dans Paramètres')

# Fin du cycle JSB en cours pour libérer ? (non : niveaux différents => cycles parallèles)
# ---------------------------------------------------------------- cycle tirage 1 000 FCFA avec mains multiples
data = {'contribution_type_id': levels[1000], 'mode': 'TIRAGE', 'start_date': '2026-10-10', 'frequency_days': '14', 'draw_now': 'on'}
data.update({f'hands_{mid}': 0 for mid in mids})
data[f'hands_{mids[0]}'] = 2
data[f'hands_{mids[1]}'] = 1
data[f'hands_{mids[2]}'] = 1
r = c.post('/tontine-cycles/add', data=data)
check(r.status_code == 302 and 'reveal=' in r.headers['Location'], 'cycle 1 000 créé et tiré au sort')
with app.app_context():
    cy = TontineCycleDetail.query.filter_by(tontine_id=jsb_id, contribution_type_id=levels[1000]).one()
    cid = cy.id
    check(cy.total_members == 4 and cy.members_count == 3, f'4 mains pour 3 membres ({cy.total_members}/{cy.members_count})')
    check(float(cy.total_amount) == 4000, 'cagnotte = 1 000 x 4 mains')
    check(sorted(p.position for p in cy.participants) == [1, 2, 3, 4], 'positions 1..4 tirées')
    first = cy.get_next_participant()
    first_member = first.member_id
check(c.post('/tontine-cycles/add', data=data).status_code == 200, 'second cycle actif sur le même niveau refusé')
data2 = dict(data, mode='ENCHERE', contribution_type_id=levels[20000])
data2.pop('draw_now')
r = c.post('/tontine-cycles/add', data=data2)
with app.app_context():
    auc = TontineCycleDetail.query.filter_by(tontine_id=jsb_id, contribution_type_id=levels[20000]).one()
    aid = auc.id
    check(auc.is_auction and all(p.position is None for p in auc.participants), 'cycle aux enchères en parallèle (sans ordre)')
check(c.post(f'/tontine-cycles/{aid}/tirage').status_code == 302, 'pas de tirage sur un cycle aux enchères')
d = data.copy()
d[f'hands_{mids[0]}'] = 11
d['contribution_type_id'] = ''
d['custom_amount'] = '500'
check(c.post('/tontine-cycles/add', data=d).status_code == 200, 'plus de 10 mains refusé')

# ---------------------------------------------------------------- versement avec amende retenue
with app.app_context():
    db.session.add(Sanction(tontine_id=jsb_id, member_id=first_member, type_sanction='RETARD_REUNION', amount=Decimal('500'),
                            description='Retard', sanction_date=m.date.today(), status='PENDING'))
    db.session.commit()
r = c.post(f'/tontine-cycles/{cid}/register-benefit', data={'confirm_offline': 'on', 'payment_mode': 'ORANGE_MONEY', 'payment_reference': 'OM123',
                                                            'deduct_sanctions': 'on'})
with app.app_context():
    b = CycleBeneficiary.query.filter_by(cycle_id=cid).one()
    check(float(b.gross_amount) == 4000 and float(b.net_amount) == 3500 and float(b.sanctions_deducted) == 500,
          f'tour 1 : 4000 - 500 amende = {b.net_amount}')
    check(Sanction.query.filter_by(member_id=first_member, status='PENDING').count() == 0, "l'amende retenue est soldée")
    txs = Transaction.query.filter_by(cycle_id=cid).all()
    kinds = sorted((t.type, float(t.amount)) for t in txs)
    check(kinds == [('BENEFICE_TONTINE', 4000.0), ('SANCTION', 500.0), ('TONTINE', 1000.0), ('TONTINE', 1000.0), ('TONTINE', 2000.0)],
          f'écritures : cagnotte, amende et cotisations régularisées (4 000) {kinds}')
    check(b.transaction_id == 'OM123', 'référence Orange Money conservée')

# ---------------------------------------------------------------- enchère
with app.app_context():
    winner = CycleParticipant.query.filter_by(cycle_id=aid).order_by(CycleParticipant.id.desc()).first()
    wid, pot = winner.id, float(TontineCycleDetail.query.get(aid).total_amount)
check(c.post(f'/tontine-cycles/{aid}/register-benefit', data={'participant_id': wid, 'bid_amount': str(int(pot))}).status_code == 302, 'mise >= cagnotte refusée')
with app.app_context():
    check(CycleBeneficiary.query.filter_by(cycle_id=aid).count() == 0, '... rien enregistré')
c.post(f'/tontine-cycles/{aid}/register-benefit', data={'confirm_offline': 'on', 'participant_id': wid, 'bid_amount': '7000', 'payment_mode': 'ESPECE'})
with app.app_context():
    b = CycleBeneficiary.query.filter_by(cycle_id=aid).one()
    check(float(b.net_amount) == pot - 7000 and float(b.bid_amount) == 7000 and b.position == 1, f'enchère : net {b.net_amount}, mise 7000, tour 1')
    check(Transaction.query.filter_by(cycle_id=aid, type='ENCHERE').count() == 1, 'mise enregistrée en caisse (ENCHERE)')
    check(CycleParticipant.query.get(wid).served, 'main servie')
check('Enchère du tour 2' in body(c.get(f'/tontine-cycles/{aid}')), 'tour suivant aux enchères')

# ---------------------------------------------------------------- fin de cycle
for _ in range(3):
    c.post(f'/tontine-cycles/{cid}/register-benefit', data={'confirm_offline': 'on', 'payment_mode': 'ESPECE'})
with app.app_context():
    cy = TontineCycleDetail.query.get(cid)
    check(cy.status == 'TERMINE' and cy.beneficiaries_count == 4, 'cycle terminé après 4 tours (2 pour le membre à 2 mains)')
    check(CycleBeneficiary.query.filter_by(cycle_id=cid, member_id=first_member).count() >= 1, 'membre à plusieurs mains servi')
    mains0 = CycleBeneficiary.query.filter_by(cycle_id=cid, member_id=mids[0]).count()
    check(mains0 == 2, f'le membre à 2 mains reçoit 2 cagnottes ({mains0})')

# ---------------------------------------------------------------- membre : vue
with app.app_context():
    mu = User.query.filter_by(tontine_id=jsb_id, role='MEMBRE', is_active=True).first()
if mu:
    mc = app.test_client()
    with mc.session_transaction() as sess:
        sess['_user_id'] = str(mu.id); sess['_fresh'] = True
    check(mc.get('/tontine-cycles').status_code == 200, 'un membre voit les cycles')
    check(mc.post(f'/tontine-cycles/{aid}/register-benefit', data={'participant_id': wid}).status_code == 302, 'un membre ne peut pas verser')
    check(mc.get('/dashboard').status_code == 200, 'tableau de bord membre')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
