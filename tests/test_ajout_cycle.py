"""Ajout d'un participant à un cycle déjà commencé, avec paiement du rappel."""
import os
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'aj.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, TontineCycleDetail, CycleParticipant, CycleBeneficiary, Transaction  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


c = app.test_client()
c.post('/inscription', data={'name': 'Tontine Rappel', 'slug': 'rappel', 'first_name': 'Hélène', 'last_name': 'Mbarga',
                             'email': 'h@rap.cm', 'phone': '699000000', 'username': 'helene', 'password': 'Helene2026',
                             'password_confirm': 'Helene2026'})
for fn in ('Paul', 'Rose', 'Jean', 'Awa'):
    c.post('/members/add', data={'first_name': fn, 'last_name': 'Tchoua', 'email': f'{fn.lower()}@rap.cm', 'phone': '699111111',
                                 'username': fn.lower(), 'role': 'MEMBRE', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='rappel').one().id
    mem = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}

# Cycle tirage à 1 000 FCFA : Hélène, Paul, Rose (3 mains) ; 2 tours versés
c.post('/tontine-cycles/add', data={'contribution_type_id': '', 'custom_amount': '1000', 'mode': 'TIRAGE', 'draw_now': 'on',
                                    f'hands_{mem["Hélène"]}': 1, f'hands_{mem["Paul"]}': 1, f'hands_{mem["Rose"]}': 1})
with app.app_context():
    cid = TontineCycleDetail.query.filter_by(tontine_id=tid).one().id
for turn in (1, 2):
    c.post(f'/tontine-cycles/{cid}/register-benefit', data={'confirm_offline': 'on', 'expected_turn': str(turn), 'payment_mode': 'ESPECE'})
with app.app_context():
    served = [b.member_id for b in CycleBeneficiary.query.filter_by(cycle_id=cid).all()]
    check(len(served) == 2, '2 tours versés avant l\'arrivée du nouveau')

h = c.get(f'/tontine-cycles/{cid}').get_data(as_text=True)
check('Ajouter un participant en cours de cycle' in h and 'data-tours="2"' in h, 'formulaire d\'ajout affiché avec 2 tours à rattraper')

# Refus : rappel non confirmé
r = c.post(f'/tontine-cycles/{cid}/participants/add', data={'member_id': mem['Jean'], 'hands': 2, 'expected_total': '4000'})
with app.app_context():
    check(len(TontineCycleDetail.query.get(cid).participants) == 3, 'sans confirmation du paiement : personne n\'est ajouté')
# Refus : montant affiché obsolète (un tour a été versé entre-temps)
c.post(f'/tontine-cycles/{cid}/participants/add', data={'member_id': mem['Jean'], 'hands': 2, 'expected_total': '2000', 'confirm_paid': 'on'})
with app.app_context():
    check(len(TontineCycleDetail.query.get(cid).participants) == 3, 'montant obsolète : ajout refusé')

# Ajout de Jean avec 2 mains : rappel = 1 000 x 2 x 2 = 4 000, reversé aux 2 mains servies
r = c.post(f'/tontine-cycles/{cid}/participants/add', data={'member_id': mem['Jean'], 'hands': 2, 'expected_total': '4000',
                                                            'confirm_paid': 'on', 'destination': 'BENEFICIAIRES',
                                                            'payment_mode': 'MTN_MOBILE', 'payment_reference': 'MOMO-42'})
with app.app_context():
    cyc = db.session.get(TontineCycleDetail, cid)
    jean_parts = sorted((p.position, p.hand_number) for p in cyc.participants if p.member_id == mem['Jean'])
    check(len(cyc.participants) == 5 and float(cyc.total_amount) == 5000, f'5 mains, cagnotte des prochains tours = 5 000 ({cyc.total_amount})')
    check(jean_parts == [(4, 1), (5, 2)], f'les mains de Jean passent après les autres ({jean_parts})')
    rappel = Transaction.query.filter_by(member_id=mem['Jean'], cycle_id=cid, type='TONTINE').one()
    check(rappel.amount == Decimal('4000') and rappel.payment_reference == 'MOMO-42', 'rappel de 4 000 encaissé (référence MoMo)')
    comps = Transaction.query.filter(Transaction.cycle_id == cid, Transaction.type == 'BENEFICE_TONTINE',
                                     Transaction.description.like('Complément%')).all()
    check(len(comps) == 2 and all(t.amount == Decimal('2000') for t in comps) and sorted(t.member_id for t in comps) == sorted(served),
          'chaque main déjà servie reçoit 2 000 de complément (total = rappel)')
    bens = CycleBeneficiary.query.filter_by(cycle_id=cid).all()
    check(all(b.gross_amount == Decimal('5000') for b in bens), 'cagnottes déjà versées réajustées à 5 000 dans l\'historique')
    check(cyc.end_date == cyc.start_date + m.timedelta(days=14 * 4), 'date de fin recalculée (5 tours)')

# Ajout d'Awa : rappel gardé en caisse + cotisation du tour en cours
c.post(f'/tontine-cycles/{cid}/participants/add', data={'member_id': mem['Awa'], 'hands': 1, 'expected_total': '3000',
                                                        'include_current': 'on', 'confirm_paid': 'on', 'destination': 'CAISSE'})
with app.app_context():
    awa = Transaction.query.filter_by(member_id=mem['Awa'], cycle_id=cid).order_by(Transaction.id).all()
    check([float(t.amount) for t in awa] == [2000.0, 1000.0], f'Awa : rappel 2 000 + tour en cours 1 000 ({[float(t.amount) for t in awa]})')
    nb_comp = Transaction.query.filter(Transaction.cycle_id == cid, Transaction.description.like('Complément%')).count()
    check(nb_comp == 2, 'rappel gardé en caisse : aucun complément supplémentaire')

# Le cycle va jusqu'au bout avec les nouvelles mains
for turn in (3, 4, 5, 6):
    c.post(f'/tontine-cycles/{cid}/register-benefit', data={'confirm_offline': 'on', 'expected_turn': str(turn), 'payment_mode': 'ESPECE'})
with app.app_context():
    cyc = db.session.get(TontineCycleDetail, cid)
    jean_served = CycleBeneficiary.query.filter_by(cycle_id=cid, member_id=mem['Jean']).count()
    check(cyc.status == 'TERMINE' and jean_served == 2, f'cycle terminé, Jean reçoit ses 2 cagnottes ({cyc.status}, {jean_served})')
    check(float(CycleBeneficiary.query.filter_by(cycle_id=cid, position=6).one().gross_amount) == 6000, 'dernier tour : cagnotte de 6 000 (6 mains)')

# Garde-fous
r = c.post(f'/tontine-cycles/{cid}/participants/add', data={'member_id': mem['Awa'], 'hands': 1, 'confirm_paid': 'on'})
with app.app_context():
    check(len(db.session.get(TontineCycleDetail, cid).participants) == 6, 'cycle terminé : plus d\'ajout possible')
with app.app_context():
    jsb_member = Member.query.filter(Member.tontine_id != tid).first().id
c.post('/tontine-cycles/add', data={'contribution_type_id': '', 'custom_amount': '500', 'mode': 'ENCHERE',
                                    f'hands_{mem["Paul"]}': 1, f'hands_{mem["Rose"]}': 1})
with app.app_context():
    cid2 = TontineCycleDetail.query.filter_by(tontine_id=tid, status='EN_COURS').one().id
c.post(f'/tontine-cycles/{cid2}/participants/add', data={'member_id': jsb_member, 'hands': 1, 'confirm_paid': 'on'})
c.post(f'/tontine-cycles/{cid2}/participants/add', data={'member_id': mem['Paul'], 'hands': 10, 'confirm_paid': 'on'})
with app.app_context():
    check(len(db.session.get(TontineCycleDetail, cid2).participants) == 2, "membre d'une autre tontine ou trop de mains : refusé")
c.post(f'/tontine-cycles/{cid2}/participants/add', data={'member_id': mem['Jean'], 'hands': 1, 'expected_total': '0'})
with app.app_context():
    p = CycleParticipant.query.filter_by(cycle_id=cid2, member_id=mem['Jean']).one()
    check(p.position is None, "aucun tour versé : ajout gratuit, sans position (cycle aux enchères)")
paul = app.test_client()
paul.post('/login', data={'tontine': 'rappel', 'username': 'paul', 'password': 'Passw0rd1'})
check(paul.post(f'/tontine-cycles/{cid2}/participants/add', data={'member_id': mem['Awa'], 'hands': 1}).status_code == 302
      and 'Ajouter un participant' not in paul.get(f'/tontine-cycles/{cid2}').get_data(as_text=True), 'un simple membre ne peut pas ajouter')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
