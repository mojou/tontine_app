"""Rapport d'épargne de janvier à décembre : parts (1 000 FCFA restés 1 mois), intérêts des emprunts partagés
selon les parts, relevé par membre, fermeture de l'année."""
import html
import os
import re
import sys
from datetime import date
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'ei.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, Transaction, Loan  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Epargne', 'slug': 'epargne', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@epargne.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})
for i, first in enumerate(['Awa', 'Rose', 'Paul', 'Kofi']):
    pres.post('/members/add', data={'first_name': first, 'last_name': 'Test', 'email': f'{first.lower()}@epargne.cm',
                                    'phone': f'69911122{i}', 'username': first.lower(), 'role': 'MEMBRE',
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
Y = date.today().year - 1          # une année complète, terminée
with app.app_context():
    tid = Tontine.query.filter_by(slug='epargne').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}

    def tx(name, kind, amount, day, **extra):
        db.session.add(Transaction(tontine_id=tid, member_id=ids[name], type=kind, amount=Decimal(amount), date=day,
                                   description=extra.pop('description', 'test'), payment_mode='ESPECE', **extra))
    tx('Awa', 'EPARGNE', 100000, date(Y, 1, 28))            # fin janvier : compte quand même 12 mois
    tx('Rose', 'EPARGNE', 50000, date(Y, 1, 5))
    tx('Rose', 'EPARGNE', 50000, date(Y, 10, 20))           # octobre : 3 mois
    tx('Paul', 'EPARGNE', 100000, date(Y, 7, 1))            # juillet : 6 mois
    # Emprunt de Kofi : 300 000 à 10 % -> 30 000 d'intérêts, remboursé en deux fois dans l'année
    loan = Loan(tontine_id=tid, member_id=ids['Kofi'], amount=Decimal('300000'), interest=Decimal('30000'),
                total_amount=Decimal('330000'), amount_paid=Decimal('330000'), request_date=date(Y, 2, 1), status='REMBOURSE')
    db.session.add(loan)
    db.session.flush()
    tx('Kofi', 'REMBOURSEMENT', 165000, date(Y, 5, 1), description=f"Remboursement emprunt #{loan.id}")   # ancien : sans lien
    tx('Kofi', 'REMBOURSEMENT', 165000, date(Y, 8, 1), description=f"Remboursement emprunt #{loan.id}", loan_id=loan.id)
    db.session.commit()

r = pres.get(f'/epargne/rapport?year={Y}')
t = text(r)
check(r.status_code == 200 and f"Rapport d'épargne {Y}" in t, 'page « Rapport d\'épargne » ouverte pour le président')
check(f'Intérêts des emprunts remboursés en {Y} 30 000 FCFA' in t, 'intérêts reçus dans l\'année : 30 000 (deux remboursements)')
check('2 550,0 parts' in t, 'total des parts : 1 200 + 750 + 600 = 2 550')
with app.app_context():
    m.g.tenant_id = tid
    rep = m.savings_report(Y)
    rows = {r_['member'].first_name: r_ for r_ in rep['rows']}
    check(rows['Awa']['parts'] == 1200 and rows['Rose']['parts'] == 750 and rows['Paul']['parts'] == 600,
          'parts : Awa 1 200 (janvier), Rose 600 + 150 (janvier + octobre), Paul 600 (juillet)')
    check((rows['Awa']['profit'], rows['Rose']['profit'], rows['Paul']['profit']) == (14117, 8823, 7058),
          'intérêts : Awa 14 117, Rose 8 823, Paul 7 058 — même épargne, mais Awa (janvier) gagne le double de Paul')
    check(rows['Awa']['months'][0] == 100000 and rows['Paul']['months'][5] == 0 and rows['Paul']['months'][6] == 100000,
          'tableau mois par mois : Awa 100 000 dès janvier, Paul 0 en juin puis 100 000 en juillet')
    check(rows['Awa']['total'] == 114117, 'Awa reçoit 100 000 + 14 117 = 114 117')
    check(rep['month_totals'][11] == 300000, 'total de décembre : 300 000 épargnés')
check('14 117' in t and '8 823' in t and '7 058' in t and '+100 000 versé' in t, 'les chiffres et les versements apparaissent dans le rapport')

# ---------------------------------------------------------------- relevé et droits
r = pres.get(f'/epargne/releve/{ids["Rose"]}?year={Y}')
t = text(r)
check('Janvier 50 000 14,12 % 12 mois 7 059 57 059' in t, 'relevé de Rose, janvier : 50 000, taux 14,12 %, intérêt 7 059, à percevoir 57 059')
check('Février 0 12,94 % 11 mois 0 0' in t, 'février : rien épargné, la ligne est quand même là (taux 12,94 %)')
check('Octobre 50 000 3,53 % 3 mois 1 765 51 765' in t, 'octobre : 50 000, taux 3,53 %, intérêt 1 765, à percevoir 51 765')
check(f'Total {Y} 100 000 moyen 8,82 % 8 823 108 823' in t and 'Somme totale à percevoir 108 823 FCFA' in t,
      "totaux : 100 000 épargnés, 8 823 d'intérêts (taux moyen 8,82 %), 108 823 à remettre")
t = text(pres.get(f'/epargne/releves?year={Y}'))
check(t.count('Somme totale à percevoir') == 3 and 'Awa Test' in t and 'Paul Test' in t,
      'relevés de tous les membres sur une seule page (un par membre, à imprimer)')
paul = app.test_client()
paul.post('/login', data={'tontine': 'epargne', 'username': 'paul', 'password': 'Passw0rd1'})
t = text(paul.get(f'/epargne/rapport?year={Y}', follow_redirects=True))
check('Paul Test' in t and 'Rose Test' not in t and 'Juillet 100 000' in t and 'Somme totale à percevoir 107 058' in t,
      '« Mon épargne » : Paul arrive sur son relevé mois par mois, sans voir les autres')
check(paul.get(f'/epargne/releves?year={Y}').status_code in (302, 403), 'Paul ne peut pas imprimer les relevés des autres')
check(paul.get(f'/epargne/releve/{ids["Rose"]}?year={Y}').status_code == 403, 'Paul ne peut pas ouvrir le relevé de Rose')
check('Mon épargne' in paul.get('/dashboard').get_data(as_text=True), 'menu du membre : « Mon épargne »')

# ---------------------------------------------------------------- retrait en cours d'année
with app.app_context():
    tx('Paul', 'RETRAIT_EPARGNE', 20000, date(Y, 9, 15))
    db.session.commit()
    m.g.tenant_id = tid
    paul_row = [r_ for r_ in m.savings_report(Y)['rows'] if r_['member'].first_name == 'Paul'][0]
    check(paul_row['parts'] == 520 and paul_row['savings'] == 80000, 'retrait de 20 000 en septembre : 600 − 80 = 520 parts')
    db.session.delete(Transaction.query.filter_by(member_id=ids['Paul'], type='RETRAIT_EPARGNE').one())
    db.session.commit()

# ---------------------------------------------------------------- fermeture de l'année : mêmes chiffres
t = text(pres.get(f'/exercice?year={Y}'))
check('Parts' in t and '14 117' in t and "Voir le rapport mois par mois" in t, 'la fin d\'année utilise les mêmes parts')
pres.post('/exercice', data={'action': 'execute', 'year': Y, 'pool_amount': 30000, 'payment_mode': 'ESPECE'})
with app.app_context():
    partage = {x.member_id: int(x.amount) for x in Transaction.query.filter_by(tontine_id=tid, type='PARTAGE').all()}
    rendu = {x.member_id: int(x.amount) for x in Transaction.query.filter_by(tontine_id=tid, type='RETRAIT_EPARGNE').all()}
    check(partage == {ids['Awa']: 14117, ids['Rose']: 8823, ids['Paul']: 7058}, 'année fermée : intérêts versés selon les parts')
    check(rendu == {ids['Awa']: 100000, ids['Rose']: 100000, ids['Paul']: 100000}, 'épargne rendue à chacun')
    m.g.tenant_id = tid
    check(m.savings_report(Y)['total_parts'] == 2550, "après la fermeture, le rapport de l'année reste identique")

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
