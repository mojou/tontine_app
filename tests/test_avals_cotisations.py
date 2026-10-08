import os
import sys
from datetime import date, timedelta
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'av.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, User, Loan, LoanGuarantor, Transaction, ContributionType  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return r.get_data(as_text=True)


def client_for(username, pwd, slug='amis'):
    c = app.test_client()
    r = c.post('/login', data={'tontine': slug, 'username': username, 'password': pwd})
    assert r.status_code == 302, (username, r.status_code)
    return c


# ---------------------------------------------------------------- tontine neuve + membres
pres = app.test_client()
r = pres.post('/inscription', data={'name': 'Tontine des Amis', 'slug': 'amis', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                    'email': 'h@amis.cm', 'phone': '699000001', 'username': 'helene',
                                    'password': 'Helene2026', 'password_confirm': 'Helene2026'})
check(r.status_code == 302, 'tontine créée')
with app.app_context():
    t = Tontine.query.filter_by(slug='amis').one()
    tid = t.id
    check(ContributionType.query.filter_by(tontine_id=tid).count() == 8, '8 rubriques africaines créées par défaut')
    check(t.guarantors_min == 1, 'nouvelle tontine : 1 avaliste exigé par défaut')

for i, (first, last, user) in enumerate([('Marc', 'Tchoua', 'marc'), ('Awa', 'Diop', 'awa'), ('Kofi', 'Mensah', 'kofi')]):
    pres.post('/members/add', data={'first_name': first, 'last_name': last, 'email': f'{user}@amis.cm', 'phone': f'69911122{i}',
                                    'username': user, 'role': 'MEMBRE', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1',
                                    'group_type': '', 'position_in_group': '', 'chosen_tontine_amount': ''})
with app.app_context():
    ids = {mm.first_name: mm.id for mm in Member.query.filter_by(tontine_id=tid).all()}
check(len(ids) == 4, f'4 membres ({list(ids)})')

# ---------------------------------------------------------------- cotisations via rubriques
with app.app_context():
    rub = {r.category: r.id for r in ContributionType.query.filter_by(tontine_id=tid).all()}
check(pres.get('/transactions/add').status_code == 200, 'formulaire de transaction avec rubriques')
for name in ['Marc', 'Awa', 'Kofi']:
    pres.post('/transactions/add', data={'member_id': ids[name], 'type': 'TONTINE', 'contribution_type_id': rub['FONDS_CAISSE'],
                                         'amount': 5000, 'payment_mode': 'ESPECE', 'description': ''})
    pres.post('/transactions/add', data={'member_id': ids[name], 'type': 'PRESENCE', 'contribution_type_id': rub['EPARGNE'],
                                         'amount': 50000, 'payment_mode': 'ESPECE', 'description': ''})
with app.app_context():
    tx = Transaction.query.filter_by(tontine_id=tid, contribution_type_id=rub['EPARGNE']).first()
    check(tx is not None and tx.type == 'EPARGNE', 'la rubrique impose la nature (EPARGNE) même si le type saisi diffère')
    check(tx.get_type_display() == 'Épargne', 'libellé = nom de la rubrique')
    marc = db.session.get(Member, ids['Marc'])
    check(marc.savings_balance == Decimal('50000') and marc.assets == Decimal('55000'), f'avoirs de Marc = 55 000 ({marc.assets})')

h = body(pres.get('/cotisations'))
check('Caisse de secours' in h and 'Épargne des membres' in h and '150 000' in h, 'page Cotisations : rubriques, fonds, totaux')
check("Frais d&#39;adhésion" in h or "Frais d'adhésion" in h, "adhésion non payée signalée")
r = pres.post('/cotisations/rubriques/add', data={'name': 'Cotisation deuil', 'category': 'SECOURS', 'amount': '2500',
                                                  'frequency': 'UNIQUE', 'is_mandatory': 'on'})
with app.app_context():
    check(ContributionType.query.filter_by(name='Cotisation deuil', tontine_id=tid).count() == 1, 'ajout de rubrique')
pres.post('/cotisations/rubriques/add', data={'name': 'X', 'category': 'SORTIE_LOAN', 'amount': '1', 'frequency': 'UNIQUE'})
with app.app_context():
    check(ContributionType.query.filter_by(name='X').count() == 0, 'catégorie de sortie refusée pour une rubrique')

# ---------------------------------------------------------------- demande d'emprunt avec avalistes
marc_c = client_for('marc', 'Passw0rd1')
awa_c = client_for('awa', 'Passw0rd1')
kofi_c = client_for('kofi', 'Passw0rd1')

r = marc_c.post('/loan/request', data={'member_id': ids['Marc'], 'amount': 20000, 'duration_months': 2})
with app.app_context():
    check(Loan.query.filter_by(tontine_id=tid).count() == 0, 'emprunt sans avaliste refusé (1 exigé)')
marc_c.post('/loan/request', data={'member_id': ids['Marc'], 'amount': 20000, 'duration_months': 2, 'guarantor_ids': [ids['Marc']]})
with app.app_context():
    check(Loan.query.filter_by(tontine_id=tid).count() == 0, 'être son propre avaliste refusé')
r = marc_c.post('/loan/request', data={'member_id': ids['Marc'], 'amount': 20000, 'duration_months': 2,
                                       'guarantor_ids': [ids['Awa'], ids['Kofi']]})
with app.app_context():
    loan = Loan.query.filter_by(tontine_id=tid).one()
    loan_id = loan.id
    shares = sorted(float(g.amount) for g in loan.guarantors)
    check(len(loan.guarantors) == 2 and sum(shares) == float(loan.total_amount), f'2 avals, parts = total dû ({shares})')
    g_awa = next(g.id for g in loan.guarantors if g.member_id == ids['Awa'])
    g_kofi = next(g.id for g in loan.guarantors if g.member_id == ids['Kofi'])

check("1 demande(s) d&#39;aval" in body(awa_c.get('/dashboard')) or "1 demande(s) d'aval" in body(awa_c.get('/dashboard')), 'alerte aval sur le tableau de bord d\'Awa')
check(marc_c.post(f'/avals/{g_awa}/respond', data={'action': 'accept'}).status_code == 403, "l'emprunteur ne peut pas répondre à la place d'Awa")
r = pres.post(f'/loans/{loan_id}/approve')
with app.app_context():
    check(db.session.get(Loan, loan_id).status == 'PENDING', 'approbation bloquée tant que personne n\'a accepté')
awa_c.post(f'/avals/{g_awa}/respond', data={'action': 'accept', 'note': 'OK pour moi'})
kofi_c.post(f'/avals/{g_kofi}/respond', data={'action': 'refuse'})
h = body(pres.get('/loans'))
check('Approuver' in h, 'bouton Approuver disponible avec 1/1 aval')
pres.post(f'/loans/{loan_id}/approve')
with app.app_context():
    loan = db.session.get(Loan, loan_id)
    check(loan.status == 'ACTIF', 'prêt approuvé')
    awa = db.session.get(Member, ids['Awa'])
    check(awa.guarantee_exposure > 0, f'engagement d\'Awa comptabilisé ({awa.guarantee_exposure})')

# Kofi a refusé : on peut demander un autre avaliste... mais le prêt n'est plus en attente
r = marc_c.post(f'/loans/{loan_id}/guarantors/add', data={'guarantor_id': ids['Kofi']})
check(r.status_code == 302, 'ajout d\'avaliste refusé après approbation (redirection avec message)')

# ---------------------------------------------------------------- défaut de paiement : appel en garantie
with app.app_context():
    loan = db.session.get(Loan, loan_id)
    loan.end_date = date.today() - timedelta(days=10)
    db.session.commit()
pres.get('/loans')  # met à jour le statut OVERDUE
check(marc_c.post(f'/avals/{g_awa}/call', data={'amount': 1000}).status_code in (302, 403), 'un membre ne peut pas appeler un aval')
with app.app_context():
    check(db.session.get(LoanGuarantor, g_awa).status == 'ACCEPTE', '... et rien n\'a changé')
pres.post(f'/avals/{g_awa}/call', data={'amount': 99999999})
with app.app_context():
    check(db.session.get(LoanGuarantor, g_awa).called_amount == 0, 'appel supérieur à la garantie refusé')
    share_awa = db.session.get(LoanGuarantor, g_awa).amount
pres.post(f'/avals/{g_awa}/call', data={'amount': int(share_awa), 'payment_mode': 'ESPECE'})
with app.app_context():
    g = db.session.get(LoanGuarantor, g_awa)
    loan = db.session.get(Loan, loan_id)
    check(g.status == 'APPELE' and g.called_amount == share_awa, 'avaliste appelé à hauteur de sa part')
    check(loan.amount_paid == share_awa, 'remboursement imputé sur le prêt')
    tx = Transaction.query.filter_by(member_id=ids['Awa'], type='REMBOURSEMENT').one()
    check('avaliste' in tx.description, 'transaction au nom de l\'avaliste')
    marc = db.session.get(Member, ids['Marc'])
    ok, reason = marc.is_eligible_for_loan(1000)
    check(not ok, f'Marc inéligible tant qu\'il doit à son avaliste ({reason})')

# Marc rembourse le reste -> prêt soldé
with app.app_context():
    rest = int(db.session.get(Loan, loan_id).remaining_amount)
pres.post(f'/loans/{loan_id}/repay', data={'amount': rest, 'payment_mode': 'ESPECE'})
with app.app_context():
    check(db.session.get(Loan, loan_id).status == 'REMBOURSE', 'prêt soldé')
pres.post(f'/avals/{g_awa}/settle')
with app.app_context():
    check(db.session.get(LoanGuarantor, g_awa).status == 'REGLE', 'dette envers l\'avaliste réglée')
    check(not db.session.get(Member, ids['Marc']).unsettled_guarantor_debts, 'Marc redevient éligible')

for url in ['/avals', '/cotisations', '/loans', '/transactions', '/parametres', '/dashboard']:
    check(pres.get(url).status_code == 200, f'président GET {url}')
for url in ['/avals', '/cotisations', '/loans', '/dashboard']:
    check(awa_c.get(url).status_code == 200, f'membre GET {url}')
check('Tchoua' not in body(awa_c.get('/cotisations')).split('Mes cotisations')[-1], 'un membre ne voit que sa ligne de cotisations')

# Paramètres d'aval
pres.post('/parametres', data={'name': 'Tontine des Amis', 'presence_amount': '1050', 'fonds_caisse_amount': '5000',
                               'loan_interest_rate': '5', 'max_aid_per_member': '3', 'guarantors_min': '2',
                               'guarantee_threshold': '100000'})
with app.app_context():
    t = db.session.get(Tontine, tid)
    check(t.guarantors_min == 2 and t.guarantee_threshold == 100000, 'règles d\'aval enregistrées')
r = kofi_c.post('/loan/request', data={'member_id': ids['Kofi'], 'amount': 30000, 'duration_months': 2})
with app.app_context():
    check(Loan.query.filter_by(member_id=ids['Kofi']).count() == 1, 'sous le seuil : emprunt sans avaliste accepté')

# Isolation : la JSB ne voit pas ces avals
with app.app_context():
    jsb_pres = User.query.filter_by(username='president', tontine_id=Tontine.query.filter_by(slug='jsb').one().id).one()
    jsb_pres.set_password('JsbPass123')
    db.session.commit()
jsb = client_for('president', 'JsbPass123', 'jsb')
check('Tchoua' not in body(jsb.get('/avals')), 'JSB ne voit pas les avals des Amis')
check(jsb.post(f'/avals/{g_kofi}/call', data={'amount': 1}).status_code == 404, 'JSB ne peut pas appeler un aval des Amis')
h = body(jsb.get('/cotisations'))
check(jsb.get('/cotisations').status_code == 200 and 'Cotisation deuil' not in h, 'JSB a ses propres rubriques (créées à la volée)')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
