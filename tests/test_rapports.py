"""Rapports : PDF (impression), CSV et Excel pour chaque type de rapport."""
import csv
import io
import os
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'rp.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, Sanction  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


# Tontine avec des données variées
c = app.test_client()
c.post('/inscription', data={'name': 'Tontine Rapports', 'slug': 'rapports', 'first_name': 'Hélène', 'last_name': 'Ekané',
                             'email': 'h@rap.cm', 'phone': '699000000', 'username': 'helene', 'password': 'Helene2026',
                             'password_confirm': 'Helene2026'})
c.post('/members/add', data={'first_name': 'Paul', 'last_name': 'Éboa', 'email': 'paul@rap.cm', 'phone': '699111111',
                             'username': 'paul', 'role': 'MEMBRE', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
c.post('/parametres', data={'name': 'Tontine Rapports', 'presence_amount': '1050', 'fonds_caisse_amount': '5000',
                            'loan_interest_rate': '5', 'max_aid_per_member': '3', 'guarantors_min': '0', 'guarantee_threshold': '0'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='rapports').one().id
    paul = Member.query.filter_by(tontine_id=tid, first_name='Paul').one().id
for t, amount in [('FONDS_CAISSE', 5000), ('EPARGNE', 25000), ('PRESENCE', 1050)]:
    c.post('/transactions/add', data={'member_id': paul, 'type': t, 'amount': amount, 'payment_mode': 'ORANGE_MONEY',
                                      'payment_reference': f'OM-{t}', 'description': ''})
c.post('/loan/request', data={'member_id': paul, 'amount': 20000, 'duration_months': 2, 'purpose': 'Commerce & stock'})
with app.app_context():
    db.session.add(Sanction(tontine_id=tid, member_id=paul, type_sanction='RETARD_REUNION', amount=500,
                            description='Retard <réunion> du 12/10', sanction_date=m.date.today(), status='PENDING'))
    db.session.commit()

today = m.date.today()
period = {'start_date': f'{today.year}-01-01', 'end_date': today.isoformat()}

check(c.get('/reports').status_code == 200 and 'Impression directe' in c.get('/reports').get_data(as_text=True),
      'page Rapports : impression directe, PDF, CSV, Excel proposés')

for kind in ('cotisations', 'loans', 'sanctions', 'financial'):
    # PDF : affiché dans le navigateur
    r = c.post('/reports', data=dict(period, report_type=kind, format='PDF'))
    check(r.status_code == 302 and '/reports/fichier/' in r.headers['Location'], f'{kind} : redirection vers une adresse GET (compatible IDM)')
    r = c.get(r.headers['Location'])
    pdf = r.data
    check(r.status_code == 200 and r.mimetype == 'application/pdf' and pdf.startswith(b'%PDF') and len(pdf) > 1500
          and 'inline' in r.headers.get('Content-Disposition', ''), f'{kind} : PDF généré et affiché pour impression ({len(pdf)} octets)')
    # CSV : téléchargé, lisible par Excel (BOM + ;)
    r = c.post('/reports', data=dict(period, report_type=kind, format='CSV'), follow_redirects=True)
    text = r.data.decode('utf-8')
    rows = list(csv.reader(io.StringIO(text.lstrip('﻿')), delimiter=';'))
    check(r.status_code == 200 and text.startswith('﻿') and 'attachment' in r.headers.get('Content-Disposition', '')
          and len(rows) >= 2 and rows[-1][0] == 'TOTAL', f'{kind} : CSV ({len(rows) - 2} ligne(s) + en-tête + total)')
    # Excel
    r = c.post('/reports', data=dict(period, report_type=kind, format='EXCEL'), follow_redirects=True)
    check(r.status_code == 200 and r.data[:2] == b'PK', f'{kind} : Excel généré')

# Contenu des rapports
r = c.post('/reports', data=dict(period, report_type='cotisations', format='CSV'), follow_redirects=True)
rows = list(csv.reader(io.StringIO(r.data.decode('utf-8').lstrip('﻿')), delimiter=';'))
check(rows[0] == ['Date', 'Membre', 'Rubrique', 'Mode', 'Référence', 'Montant (FCFA)'], 'cotisations : colonnes attendues')
check(rows[-1][-1] == '31050' and any('OM-EPARGNE' in row for row in rows), f'cotisations : total 31 050 et références ({rows[-1]})')
r = c.post('/reports', data=dict(period, report_type='loans', format='CSV'), follow_redirects=True)
rows = list(csv.reader(io.StringIO(r.data.decode('utf-8').lstrip('﻿')), delimiter=';'))
check(len(rows) == 3 and rows[1][1] == 'Paul Éboa' and rows[1][2] == '20000', f'emprunts : vrai rapport des prêts ({rows[1][:3]})')
r = c.post('/reports', data=dict(period, report_type='financial', format='CSV'), follow_redirects=True)
rows = list(csv.reader(io.StringIO(r.data.decode('utf-8').lstrip('﻿')), delimiter=';'))
check(rows[0][4:] == ['Entrée (FCFA)', 'Sortie (FCFA)'], 'financier : entrées et sorties séparées')

# Erreurs de saisie : message propre
for bad in [dict(period, report_type='loans', format='DOCX'), dict(period, report_type='inconnu', format='PDF'),
            dict(report_type='loans', format='PDF', start_date='2026-12-31', end_date='2026-01-01'),
            dict(report_type='loans', format='PDF', start_date='zz', end_date='')]:
    r = c.post('/reports', data=bad)
    check(r.status_code == 302 and '/fichier/' not in r.headers['Location'], f"saisie invalide refusée proprement ({bad.get('format')}, {bad.get('report_type')})")

# Isolation : la JSB n'exporte pas les données de cette tontine
with app.app_context():
    from models import User
    u = User.query.filter(User.username == 'president', User.tontine_id != tid).first()
    u.set_password('JsbPass123')
    db.session.commit()
jsb = app.test_client()
jsb.post('/login', data={'tontine': 'jsb', 'username': 'president', 'password': 'JsbPass123'})
r = jsb.post('/reports', data=dict(period, report_type='cotisations', format='CSV'), follow_redirects=True)
check('Éboa' not in r.data.decode('utf-8'), "rapport d'une autre tontine : aucune donnée de « Tontine Rapports »")
member = app.test_client()
member.post('/login', data={'tontine': 'rapports', 'username': 'paul', 'password': 'Passw0rd1'})
check(member.post('/reports', data=dict(period, report_type='financial', format='PDF')).status_code == 302,
      'un simple membre ne peut pas exporter les rapports')

# Impression directe (page web) et sécurité du lien
r = c.post('/reports', data=dict(period, report_type='financial', format='PRINT'), follow_redirects=True)
h = r.get_data(as_text=True)
check(r.status_code == 200 and r.mimetype == 'text/html' and 'window.print()' in h and 'Solde de la période' in h,
      'impression directe : page web prête à imprimer (aucun fichier à télécharger)')
link = c.post('/reports', data=dict(period, report_type='loans', format='PDF')).headers['Location']
check(jsb.get(link).status_code == 404, "le lien d'un rapport ne fonctionne que pour la personne qui l'a demandé")
check(c.get(link[:-4] + 'abcd').status_code == 404, 'lien de rapport falsifié refusé')
check(c.get(link).status_code == 200 and c.get(link).data.startswith(b'%PDF'), 'le lien GET peut être rechargé (gestionnaire de téléchargement)')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
