import os
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'se.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import (Tontine, Member, Transaction, ContributionType, TontineCycleDetail, Seance,  # noqa: E402
                    ExerciseClosure)

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return r.get_data(as_text=True)


c = app.test_client()
c.post('/inscription', data={'name': 'Njangi Bonaberi', 'slug': 'bonaberi', 'first_name': 'Hélène', 'last_name': 'Ekwalla',
                             'email': 'h@bona.cm', 'phone': '699000009', 'username': 'helene',
                             'password': 'Helene2026', 'password_confirm': 'Helene2026'})
for i, (fn, ln) in enumerate([('Paul', 'Eboa'), ('Rose', 'Ngo'), ('Jean', 'Mbappe')]):
    c.post('/members/add', data={'first_name': fn, 'last_name': ln, 'email': f'{fn.lower()}@bona.cm', 'phone': f'69922233{i}',
                                 'username': fn.lower(), 'role': 'MEMBRE', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='bonaberi').one().id
    mem = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
check(len(mem) == 4, f'4 membres créés sans type de groupe ({list(mem)})')
check(c.get('/members/add').status_code == 200 and 'Type de groupe' not in body(c.get('/members/add')), "formulaire membre sans « type de groupe »")

# Niveaux : 1 000 et 20 000 (10 000 existe par défaut) via les boutons rapides des Paramètres
for amount in ('1000', '20000'):
    r = c.post('/cotisations/rubriques/add', data={'category': 'TONTINE', 'amount': amount, 'frequency': 'BIMENSUEL',
                                                   'next': '/parametres#niveaux'})
    check(r.status_code == 302 and '/parametres' in r.headers['Location'], f'ajout du niveau {amount} depuis Paramètres')
r = c.post('/cotisations/rubriques/add', data={'category': 'TONTINE', 'amount': '1000', 'frequency': 'BIMENSUEL', 'next': '/parametres'})
with app.app_context():
    lv = {int(x.amount): x for x in ContributionType.query.filter_by(tontine_id=tid, category='TONTINE').all()}
    check(sorted(lv) == [1000, 10000, 20000], f'niveaux 1 000 / 10 000 / 20 000, doublon refusé ({sorted(lv)})')
    check(lv[1000].name == 'Tontine 1 000', f'nom automatique ({lv[1000].name})')
    lv_ids = {k: v.id for k, v in lv.items()}
check('Tontine 20 000' in body(c.get('/parametres')), 'niveaux listés dans Paramètres')
h = body(app.test_client().get('/register?t=bonaberi'))
check('20 000 FCFA' in h and '5 100' not in h, "l'inscription propose les niveaux de la tontine")

# Deux cycles parallèles : 1 000 (Paul 2 mains, Rose, Jean) et 20 000 (Hélène, Paul)
d = {'contribution_type_id': lv_ids[1000], 'mode': 'TIRAGE', 'draw_now': 'on',
     f'hands_{mem["Paul"]}': 2, f'hands_{mem["Rose"]}': 1, f'hands_{mem["Jean"]}': 1, f'hands_{mem["Hélène"]}': 0}
c.post('/tontine-cycles/add', data=d)
c.post('/tontine-cycles/add', data={'contribution_type_id': lv_ids[20000], 'mode': 'ENCHERE',
                                    f'hands_{mem["Hélène"]}': 1, f'hands_{mem["Paul"]}': 1})
with app.app_context():
    cyc = {int(x.amount_per_member): x.id for x in TontineCycleDetail.query.filter_by(tontine_id=tid).all()}
check(sorted(cyc) == [1000, 20000], 'deux cycles en parallèle')

# ---------------------------------------------------------------- séance
with app.app_context():
    rub = {x.category: x.id for x in ContributionType.query.filter_by(tontine_id=tid).all() if x.category != 'TONTINE'}
check(c.get('/seances').status_code == 200, 'page séances')
r = c.post('/seances/add', data={'date': '2026-10-12', 'title': 'Réunion du 12 octobre',
                                 'columns': [f'c{cyc[1000]}', f'c{cyc[20000]}', f'r{rub["PRESENCE"]}', f'r{rub["EPARGNE"]}']})
check(r.status_code == 302, 'feuille de séance ouverte')
with app.app_context():
    sid = Seance.query.filter_by(tontine_id=tid).one().id
h = body(c.get(f'/seances/{sid}'))
check(f'name="amt_{mem["Paul"]}_c{cyc[1000]}"' in h and 'value="2000"' in h, 'Paul : 2 mains x 1 000 = 2 000 attendus')
check(f'name="amt_{mem["Rose"]}_c{cyc[20000]}"' not in h, 'Rose ne participe pas au cycle 20 000 (case grisée)')
form = {'payment_mode': 'MTN_MOBILE',
        f'pay_{mem["Paul"]}_c{cyc[1000]}': 'on', f'amt_{mem["Paul"]}_c{cyc[1000]}': '2000',
        f'pay_{mem["Rose"]}_c{cyc[1000]}': 'on', f'amt_{mem["Rose"]}_c{cyc[1000]}': '1000',
        f'pay_{mem["Paul"]}_r{rub["PRESENCE"]}': 'on', f'amt_{mem["Paul"]}_r{rub["PRESENCE"]}': '1050',
        f'pay_{mem["Paul"]}_r{rub["EPARGNE"]}': 'on', f'amt_{mem["Paul"]}_r{rub["EPARGNE"]}': '30000',
        f'pay_{mem["Rose"]}_r{rub["EPARGNE"]}': 'on', f'amt_{mem["Rose"]}_r{rub["EPARGNE"]}': '10000',
        f'ref_{mem["Paul"]}': 'MOMO-778899',
        # Rose cochée sur un cycle où elle n'est pas : ignoré
        f'pay_{mem["Rose"]}_c{cyc[20000]}': 'on', f'amt_{mem["Rose"]}_c{cyc[20000]}': '20000'}
r = c.post(f'/seances/{sid}', data=form)
with app.app_context():
    txs = Transaction.query.filter_by(seance_id=sid).all()
    check(len(txs) == 5, f'5 paiements créés ({len(txs)})')
    check(sum(float(t.amount) for t in txs) == 44050, 'total 44 050 FCFA')
    t_paul = [t for t in txs if t.member_id == mem['Paul'] and t.cycle_id == cyc[1000]][0]
    check(t_paul.type == 'TONTINE' and t_paul.payment_reference == 'MOMO-778899' and t_paul.payment_mode == 'MTN_MOBILE',
          'cotisation tontine rattachée au cycle avec référence MoMo')
    check(not [t for t in txs if t.member_id == mem['Rose'] and t.cycle_id == cyc[20000]], 'paiement hors participation ignoré')
c.post(f'/seances/{sid}', data=form)
with app.app_context():
    check(Transaction.query.filter_by(seance_id=sid).count() == 5, 'renvoi du formulaire : pas de double paiement')
h = body(c.get(f'/seances/{sid}'))
check('fa-check-circle' in h and '44 050' in h, 'cases payées affichées en vert + total')
h = body(c.get(f'/tontine-cycles/{cyc[1000]}'))
check('3 000' in h, 'cotisations rattachées au cycle affichées (3 000)')

# ---------------------------------------------------------------- enchère + emprunt => bénéfices
with app.app_context():
    from models import CycleParticipant
    p_paul = CycleParticipant.query.filter_by(cycle_id=cyc[20000], member_id=mem['Paul']).one().id
c.post(f'/tontine-cycles/{cyc[20000]}/register-benefit', data={'confirm_offline': 'on', 'participant_id': p_paul, 'bid_amount': '4000', 'payment_mode': 'ESPECE'})
with app.app_context():
    check(Transaction.query.filter_by(tontine_id=tid, type='ENCHERE').count() == 1, 'mise de 4 000 en caisse')

# ---------------------------------------------------------------- fin d'exercice
year = m.date.today().year
h = body(c.get(f'/exercice?year={year}'))
check(c.get(f'/exercice?year={year}').status_code == 200 and 'Paul' in h and 'Rose' in h, 'aperçu du partage')
with app.app_context():
    prev = None
with app.test_request_context():
    from flask import g
    g.tenant_id = tid
    prev = m._exercise_preview(year, False)
    shares = {s['member'].first_name: (float(s['savings']), float(s['profit'])) for s in prev['savers']}
check(shares == {'Paul': (30000.0, 3000.0), 'Rose': (10000.0, 1000.0)}, f'bénéfices 4 000 répartis 75/25 : {shares}')
member_c = app.test_client()
member_c.post('/login', data={'tontine': 'bonaberi', 'username': 'paul', 'password': 'Passw0rd1'})
check(member_c.get('/exercice').status_code == 302, 'un membre ne voit pas la clôture')
r = c.post('/exercice', data={'action': 'execute', 'year': year, 'pool_amount': '999999', 'payment_mode': 'ESPECE'})
with app.app_context():
    check(ExerciseClosure.query.filter_by(tontine_id=tid).count() == 0, 'partage supérieur à la caisse refusé')
r = c.post('/exercice', data={'action': 'execute', 'year': year, 'pool_amount': '4000', 'payment_mode': 'ESPECE', 'notes': 'AG'})
with app.app_context():
    cl = ExerciseClosure.query.filter_by(tontine_id=tid, year=year).one()
    check(float(cl.savings_returned) == 40000 and float(cl.profit_distributed) == 4000, 'exercice clôturé : 40 000 + 4 000')
    paul = db.session.get(Member, mem['Paul'])
    check(paul.savings_balance == 0, 'épargne de Paul restituée (solde 0)')
    check(Transaction.query.filter_by(member_id=mem['Paul'], type='PARTAGE').one().amount == Decimal('3000'), 'Paul reçoit 3 000 de bénéfices')
c.post('/exercice', data={'action': 'execute', 'year': year, 'pool_amount': '4000', 'payment_mode': 'ESPECE'})
with app.app_context():
    check(ExerciseClosure.query.filter_by(tontine_id=tid).count() == 1, 'double clôture impossible')
check('clôturé' in body(c.get(f'/exercice?year={year}')), 'exercice affiché comme clôturé')

for url in ['/cotisations', '/transactions', '/transactions/add', '/dashboard', '/tontine-cycles', f'/tontine-cycles/{cyc[1000]}',
            '/seances', f'/seances/{sid}', '/exercice', '/parametres']:
    check(c.get(url).status_code == 200, f'GET {url}')
r = c.post('/transactions/add', data={'member_id': mem['Jean'], 'type': 'PRESENCE', 'amount': 1050, 'payment_mode': 'WAVE',
                                      'payment_reference': 'WAVE-1', 'description': ''})
with app.app_context():
    t = Transaction.query.filter_by(member_id=mem['Jean'], payment_reference='WAVE-1').first()
    check(t is not None and t.payment_mode == 'WAVE', 'saisie manuelle : paiement Wave + référence')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
