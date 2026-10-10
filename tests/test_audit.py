"""Non-régression des défauts corrigés lors de l'audit."""
import os
import re
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'au.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, User, Loan, Transaction, Sanction, TontineCycleDetail, CycleBeneficiary  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return r.get_data(as_text=True)


# ---------------------------------------------------------------- configuration
check(app.config['SECRET_KEY'] not in ('dev-secret-key-change-in-production-12345', 'dev-secret-key-12345')
      and len(app.config['SECRET_KEY']) >= 32, 'clé secrète aléatoire (plus de valeur connue)')
check(os.path.exists(os.path.join(P, 'instance', 'secret_key')), 'clé secrète conservée dans instance/secret_key')
run_src = open(os.path.join(P, 'run.py'), encoding='utf-8').read()
check("debug=True" not in run_src and "'127.0.0.1'" in run_src, 'run.py : pas de débogage ni d\'écoute réseau par défaut')
import backup  # noqa: E402
check(backup.DATABASE_PATH.replace('\\', '/').endswith('au.db'), 'backup.py sauvegarde la base réellement utilisée')
out = str(app.jinja_env.from_string('{{ t|nl2br|safe }}').render(t='a\n<b>x</b>'))
check(out == 'a<br>\n&lt;b&gt;x&lt;/b&gt;', f'nl2br : vrais sauts de ligne, HTML neutralisé ({out!r})')

# ---------------------------------------------------------------- données
c = app.test_client()
c.post('/inscription', data={'name': 'Audit', 'slug': 'audit', 'first_name': 'Hélène', 'last_name': 'Abo', 'email': 'h@au.cm',
                             'phone': '699000000', 'username': 'helene', 'password': 'Helene2026', 'password_confirm': 'Helene2026'})
for fn in ('Paul', 'Rose'):
    c.post('/members/add', data={'first_name': fn, 'last_name': 'Bami', 'email': f'{fn.lower()}@au.cm', 'phone': '699111111',
                                 'username': fn.lower(), 'role': 'MEMBRE', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
c.post('/parametres', data={'name': 'Audit', 'presence_amount': '1050', 'fonds_caisse_amount': '5000', 'loan_interest_rate': '5',
                            'max_aid_per_member': '3', 'guarantors_min': '0', 'guarantee_threshold': '0'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='audit').one().id
    mem = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}

# ---------------------------------------------------------------- doublons de saisie
data = {'member_id': mem['Paul'], 'type': 'EPARGNE', 'amount': 50000, 'payment_mode': 'ESPECE', 'description': ''}
c.post('/transactions/add', data=data)
c.post('/transactions/add', data=data)
with app.app_context():
    check(Transaction.query.filter_by(member_id=mem['Paul'], type='EPARGNE').count() == 1, 'double clic sur une saisie : une seule écriture')
check(c.get('/transactions/1/view').status_code in (200, 302, 404), 'détail de transaction sans erreur')
with app.app_context():
    tx_id = Transaction.query.filter_by(member_id=mem['Paul'], type='EPARGNE').one().id
check(c.get(f'/transactions/{tx_id}/view').status_code == 200, 'page de détail d\'une transaction (template créé)')
check(c.get('/transactions?date_debut=zz').status_code == 200, 'date de filtre invalide ignorée')

# ---------------------------------------------------------------- emprunt : page de remboursement, double remboursement
c.post('/transactions/add', data={'member_id': mem['Paul'], 'type': 'FONDS_CAISSE', 'amount': 5000, 'payment_mode': 'ESPECE', 'description': ''})
c.post('/loan/request', data={'member_id': mem['Paul'], 'amount': 10000, 'duration_months': 2})
with app.app_context():
    loan_id = Loan.query.filter_by(member_id=mem['Paul']).one().id
c.post(f'/loans/{loan_id}/approve')
h = body(c.get(f'/loans/{loan_id}/repay'))
check('csrf_token' in h and 'expected_paid' in h and 'Reste à payer' in h, 'page de remboursement dédiée fonctionnelle')
repay = {'amount': '3000', 'expected_paid': '0.0', 'payment_mode': 'WAVE', 'payment_reference': 'W-1'}
c.post(f'/loans/{loan_id}/repay', data=repay)
c.post(f'/loans/{loan_id}/repay', data=repay)
with app.app_context():
    loan = db.session.get(Loan, loan_id)
    check(loan.amount_paid == Decimal('3000'), f'double remboursement bloqué ({loan.amount_paid})')
    rt = Transaction.query.filter_by(member_id=mem['Paul'], type='REMBOURSEMENT').one()
    check(rt.payment_mode == 'WAVE' and rt.payment_reference == 'W-1', 'mode et référence du remboursement enregistrés')
    sortie_id = Transaction.query.filter_by(type='SORTIE_LOAN', member_id=mem['Paul']).one().id
c.post(f'/loans/{loan_id}/repay', data={'amount': '1000', 'payment_mode': 'PIRATE'})
with app.app_context():
    check(Transaction.query.filter_by(payment_mode='PIRATE').count() == 0, 'mode de paiement inconnu remplacé par Espèces')

# ---------------------------------------------------------------- écritures automatiques protégées
r = c.post(f'/transactions/{sortie_id}/delete', follow_redirects=True)
with app.app_context():
    check(db.session.get(Transaction, sortie_id) is not None and 'Emprunts' in body(r), 'suppression d\'un décaissement refusée')
check(c.get(f'/transactions/{sortie_id}/edit').status_code == 302, 'modification d\'un décaissement refusée')
h = body(c.get('/transactions'))
check('fa-lock' in h and 'editTransactionModal' not in h, 'cadenas sur les écritures automatiques, ancien formulaire cassé retiré')

# ---------------------------------------------------------------- cagnotte : double versement
d = {'contribution_type_id': '', 'custom_amount': '1000', 'mode': 'TIRAGE', 'draw_now': 'on',
     f'hands_{mem["Paul"]}': 1, f'hands_{mem["Rose"]}': 1, f'hands_{mem["Hélène"]}': 1}
c.post('/tontine-cycles/add', data=d)
with app.app_context():
    cid = TontineCycleDetail.query.filter_by(tontine_id=tid).one().id
h = body(c.get(f'/tontine-cycles/{cid}'))
check('name="expected_turn" value="1"' in h, 'le formulaire de versement porte le numéro du tour')
c.post(f'/tontine-cycles/{cid}/register-benefit', data={'confirm_offline': 'on', 'expected_turn': '1', 'payment_mode': 'ESPECE'})
c.post(f'/tontine-cycles/{cid}/register-benefit', data={'confirm_offline': 'on', 'expected_turn': '1', 'payment_mode': 'ESPECE'})
with app.app_context():
    check(CycleBeneficiary.query.filter_by(cycle_id=cid).count() == 1, 'double clic sur « Verser la cagnotte » : un seul versement')

# ---------------------------------------------------------------- rapports : sanctions payées
with app.app_context():
    db.session.add(Sanction(tontine_id=tid, member_id=mem['Rose'], type_sanction='AUTRE', amount=Decimal('700'),
                            description='Test', sanction_date=m.date.today(), status='PENDING'))
    db.session.commit()
    sid = Sanction.query.filter_by(member_id=mem['Rose']).one().id
c.post(f'/sanctions/{sid}/pay', data={'payment_mode': 'ESPECE'})
h = body(c.get('/reports'))
check('700' in h, 'rapport : total des sanctions payées pris en compte')

# ---------------------------------------------------------------- emails : unicité et synchronisation
r = c.post(f'/members/{mem["Rose"]}/edit', data={'first_name': 'Rose', 'last_name': 'Bami', 'email': 'paul@au.cm', 'phone': '699111111',
                                                  'status': 'ACTIF'})
check(r.status_code == 200 and 'déjà utilisé' in body(r), 'email déjà pris : message clair (plus d\'erreur 500)')
c.post(f'/members/{mem["Rose"]}/edit', data={'first_name': 'Rose', 'last_name': 'Bami', 'email': 'rose.new@au.cm', 'phone': '699111111',
                                             'status': 'ACTIF'})
with app.app_context():
    u = User.query.filter_by(tontine_id=tid, member_id=mem['Rose']).one()
    check(u.email == 'rose.new@au.cm', 'email du compte synchronisé avec la fiche membre')
paul = app.test_client()
paul.post('/login', data={'tontine': 'audit', 'username': 'paul', 'password': 'Passw0rd1'})
r = paul.post('/profile', data={'first_name': 'Paul', 'last_name': 'Bami', 'phone': '699111111', 'email': 'rose.new@au.cm'})
check(r.status_code == 200 and 'déjà utilisé' in body(r), 'profil : email d\'un autre membre refusé')

# ---------------------------------------------------------------- force brute
brute = app.test_client()
codes = [brute.post('/login', data={'tontine': 'audit', 'username': 'rose', 'password': 'mauvais'}).status_code for _ in range(6)]
r = brute.post('/login', data={'tontine': 'audit', 'username': 'rose', 'password': 'Passw0rd1'})
check(codes[-1] == 429 and r.status_code == 429, f'5 échecs : compte bloqué 15 min, même avec le bon mot de passe ({codes[-2:]}, {r.status_code})')
from models import LoginAttempt  # noqa: E402
with app.app_context():
    check(LoginAttempt.query.filter_by(scope='login').count() >= 5, 'échecs enregistrés en base (le blocage survit à un redémarrage)')
other = app.test_client().post('/login', data={'tontine': 'audit', 'username': 'paul', 'password': 'Passw0rd1'})
check(other.status_code == 302, "les autres comptes ne sont pas bloqués")

# ---------------------------------------------------------------- nombres démesurés
r = c.post('/loan/request', data={'member_id': '9' * 30, 'amount': '1000'})
check(r.status_code == 303, 'identifiant démesuré : message propre au lieu d\'une erreur 500')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
