"""Écarts d'un cycle : retard / tour en cours / avance, et régularisation (cycle en cours ou terminé)."""
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
from models import Tontine, Member, ContributionType, TontineCycleDetail, Seance, Transaction  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


c = app.test_client()
c.post('/inscription', data={'name': 'Tontine Ecarts', 'slug': 'ecarts', 'first_name': 'Hélène', 'last_name': 'Ngo',
                             'email': 'h@ecarts.cm', 'phone': '699000001', 'username': 'helene',
                             'password': 'Helene2026', 'password_confirm': 'Helene2026'})
for i, fn in enumerate(['Paul', 'Rose']):
    c.post('/members/add', data={'first_name': fn, 'last_name': 'Test', 'email': f'{fn.lower()}@ecarts.cm',
                                 'phone': f'69911122{i}', 'username': fn.lower(), 'role': 'MEMBRE',
                                 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='ecarts').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
    lv = ContributionType.query.filter_by(tontine_id=tid, category='TONTINE').first().id
c.post('/tontine-cycles/add', data={'contribution_type_id': lv, 'mode': 'TIRAGE', 'draw_now': 'on',
                                    **{f'hands_{i}': 1 for i in ids.values()}})
with app.app_context():
    cyc = TontineCycleDetail.query.filter_by(tontine_id=tid).one().id
url = f'/tontine-cycles/{cyc}'


def age():
    """Vieillit les écritures d'une minute : la protection anti double-clic (15 s) ne bloque pas le test"""
    from datetime import timedelta
    with app.app_context():
        for t in Transaction.query.filter_by(tontine_id=tid).all():
            t.created_at = (t.created_at or m.datetime.utcnow()) - timedelta(minutes=1)
        db.session.commit()


def status():
    with app.test_request_context():
        m.g.tenant_id = tid
        st = m.cycle_contribution_status(db.session.get(TontineCycleDetail, cyc))
        return st, {r['member'].first_name: r for r in st['rows']}


# ---------------------------------------------------------------- début de tour : ce n'est pas un retard
h = text(c.get(url))
check('tour 1 : 30 000 FCFA à encaisser' in h and 'en retard' not in h.split('État des cotisations')[1][:200],
      'début du tour 1 : « 30 000 FCFA à encaisser », pas de retard affiché')
st, rows = status()
check(st['late_total'] == 0 and st['current_total'] == Decimal('30000'), 'calcul : 0 en retard, 30 000 pour le tour en cours')

# ---------------------------------------------------------------- tour 1 versé (cotisations déclarées), puis un oubli
c.post(f'{url}/register-benefit', data={'expected_turn': 1, 'payment_mode': 'ESPECE', 'confirm_offline': 'on'})
with app.app_context():   # simule une ancienne donnée : la cotisation de Rose n'avait pas été saisie
    db.session.delete(Transaction.query.filter_by(cycle_id=cyc, member_id=ids['Rose'], type='TONTINE').one())
    db.session.commit()
st, rows = status()
check(rows['Rose']['late'] == Decimal('10000') and rows['Rose']['current_due'] == Decimal('10000'),
      'Rose : 10 000 en retard (tour 1 versé) + 10 000 pour le tour 2')
check(rows['Paul']['late'] == 0 and rows['Paul']['current_due'] == Decimal('10000'), 'Paul : à jour, 10 000 pour le tour 2')
h = text(c.get(url))
check('10 000 FCFA en retard' in h and 'Régulariser' in h, 'la page distingue le retard et propose « Régulariser »')

# ---------------------------------------------------------------- régulariser un retard
r = c.post(f'{url}/regulariser', data={'member_id': ids['Rose'], 'action': 'encaisser', 'amount': '30000',
                                       'payment_mode': 'ESPECE'}, follow_redirects=True)
check('Montant invalide' in text(r), 'encaisser plus que ce qu\'il doit (30 000 > 20 000) : refusé')
r = c.post(f'{url}/regulariser', data={'member_id': ids['Rose'], 'action': 'encaisser', 'amount': '10000',
                                       'payment_mode': 'MTN_MOBILE'}, follow_redirects=True)
st, rows = status()
check(rows['Rose']['late'] == 0 and '10 000 FCFA de cotisations encaissés pour Rose Test' in text(r),
      'Rose rattrape son retard : plus de retard')
with app.app_context():
    tx = Transaction.query.filter_by(cycle_id=cyc, member_id=ids['Rose'], type='TONTINE').order_by(Transaction.id.desc()).first()
    check(tx.amount == Decimal('10000') and tx.payment_mode == 'MTN_MOBILE' and 'Rattrapage' in tx.description,
          'le rattrapage est une cotisation du cycle (mode MTN conservé)')

# ---------------------------------------------------------------- saisie dans Transactions : rattachée au cycle
age()
r = c.post('/transactions/add', data={'member_id': ids['Paul'], 'type': 'TONTINE', 'contribution_type_id': lv,
                                      'amount': 10000, 'payment_mode': 'ESPECE', 'description': 'tour 2'}, follow_redirects=True)
with app.app_context():
    tx = Transaction.query.filter_by(member_id=ids['Paul'], description='tour 2').one()
    check(tx.cycle_id == cyc, 'cotisation saisie dans Transactions : rattachée automatiquement au cycle')
check('Cotisation rattachée au Cycle #1' in text(r), "message : « Cotisation rattachée au cycle »")

# ---------------------------------------------------------------- avance (double saisie) : épargne ou remboursement
age()
c.post('/transactions/add', data={'member_id': ids['Hélène'], 'type': 'TONTINE', 'contribution_type_id': lv,
                                  'amount': 30000, 'payment_mode': 'ESPECE', 'description': 'double'})
st, rows = status()
check(rows['Hélène']['advance'] == Decimal('20000'), f"Hélène a payé 30 000 pour 10 000 dus : 20 000 d'avance ({rows['Hélène']['advance']})")
check('20 000 FCFA d\'avance' in text(c.get(url)), "l'avance est affichée")
with app.test_request_context():
    m.g.tenant_id = tid
    savings_before = db.session.get(Member, ids['Hélène']).savings_balance
r = c.post(f'{url}/regulariser', data={'member_id': ids['Hélène'], 'action': 'epargne', 'amount': '15000',
                                       'payment_mode': 'ESPECE'}, follow_redirects=True)
c.post(f'{url}/regulariser', data={'member_id': ids['Hélène'], 'action': 'rendre', 'amount': '5000', 'payment_mode': 'ESPECE'})
st, rows = status()
with app.test_request_context():
    m.g.tenant_id = tid
    helene = db.session.get(Member, ids['Hélène'])
    check(rows['Hélène']['advance'] == 0 and helene.savings_balance - savings_before == Decimal('15000'),
          "15 000 versés dans l'épargne + 5 000 rendus : plus d'avance, épargne +15 000")
    check(Transaction.query.filter_by(member_id=ids['Hélène'], type='RESTITUTION_TONTINE').count() == 2,
          'les deux opérations sont enregistrées comme « Avance de tontine rendue »')
r = c.post(f'{url}/regulariser', data={'member_id': ids['Hélène'], 'action': 'rendre', 'amount': '1000', 'payment_mode': 'ESPECE'},
           follow_redirects=True)
check('Montant invalide' in text(r), 'rendre une avance qui n\'existe plus : refusé')

# ---------------------------------------------------------------- cycle terminé : on peut encore régulariser
age()
c.post('/transactions/add', data={'member_id': ids['Rose'], 'type': 'TONTINE', 'contribution_type_id': lv,
                                  'amount': 10000, 'payment_mode': 'ESPECE', 'description': 'rose t2'})
c.post(f'{url}/register-benefit', data={'expected_turn': 2, 'payment_mode': 'ESPECE'})
c.post(f'{url}/register-benefit', data={'expected_turn': 3, 'payment_mode': 'ESPECE', 'confirm_offline': 'on'})
with app.app_context():
    check(db.session.get(TontineCycleDetail, cyc).status == 'TERMINE', 'cycle terminé après 3 tours')
    db.session.delete(Transaction.query.filter_by(cycle_id=cyc, member_id=ids['Paul'], description='tour 2').one())
    db.session.commit()
st, rows = status()
check(rows['Paul']['late'] == Decimal('10000'), 'cycle terminé : le retard de Paul (10 000) est visible')
c.post(f'{url}/regulariser', data={'member_id': ids['Paul'], 'action': 'encaisser', 'amount': '10000', 'payment_mode': 'ESPECE'})
st, rows = status()
check(st['late_total'] == 0 and st['advance_total'] == 0, 'cycle terminé régularisé : tout le monde est à jour')
check('À jour' in text(c.get(url)), 'la page du cycle terminé affiche « À jour »')

# ---------------------------------------------------------------- cycle terminé : prochaines étapes
h = text(c.get(url))
check('Cycle terminé : prochaines étapes' in h, "la page du cycle terminé affiche « prochaines étapes »")
with app.test_request_context():
    m.g.tenant_id = tid
    cy = db.session.get(TontineCycleDetail, cyc)
    steps = m.cycle_next_steps(cy, m.cycle_contribution_status(cy))
check([s['done'] for s in steps] == [True, True, True, False],
      f"étapes cochées automatiquement : cotisations soldées, caisse à 0, amendes réglées ; cycle suivant à lancer {[s['done'] for s in steps]}")
check('3/4' in h and 'Nouveau cycle' in h, 'compteur 3/4 et bouton « Nouveau cycle »')
c.post('/tontine-cycles/add', data={'contribution_type_id': lv, 'mode': 'TIRAGE', 'draw_now': 'on',
                                    **{f'hands_{i}': 1 for i in ids.values()}})
h = text(c.get(url))
check('4/4' in h and 'Cycle #2' in h and 'Ouvrir le nouveau cycle' in h, 'cycle suivant créé : 4/4 et lien vers le nouveau cycle')
check('Cycle terminé : prochaines étapes' not in text(c.get(f'/tontine-cycles/{cyc + 1}')),
      "un cycle en cours n'affiche pas l'encadré de fin")

# ---------------------------------------------------------------- droits et tableau de bord
paul = app.test_client()
paul.post('/login', data={'tontine': 'ecarts', 'username': 'paul', 'password': 'Passw0rd1'})
r = paul.post(f'{url}/regulariser', data={'member_id': ids['Paul'], 'action': 'encaisser', 'amount': '1', 'payment_mode': 'ESPECE'})
with app.app_context():
    check(Transaction.query.filter_by(member_id=ids['Paul'], amount=Decimal('1')).count() == 0, 'un membre ne peut pas régulariser')
check('Régulariser' not in text(paul.get(url)), 'un membre ne voit pas le bouton « Régulariser »')
h = text(c.get('/dashboard'))
check('Fonds tontine négatif' not in h, 'cycle régularisé : plus d\'alerte « fonds tontine négatif »')
with app.app_context():
    db.session.add(Transaction(tontine_id=tid, member_id=ids['Paul'], type='BENEFICE_TONTINE', amount=Decimal('500000'),
                               date=m.date.today(), description='test fonds négatif'))
    db.session.commit()
check('Fonds tontine négatif' in text(c.get('/dashboard')), "alerte si le fonds tontine devient négatif")

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
