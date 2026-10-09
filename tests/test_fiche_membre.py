"""Fiche membre : chaque ligne explique sa nature (épargne ≠ fonds de caisse) ; formulaire sans montants figés."""
import html
import os
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'fm.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, Transaction  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return html.unescape(r.get_data(as_text=True))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Fiche', 'slug': 'fiche', 'first_name': 'Hélène', 'last_name': 'Mballa',
                                'email': 'h@fiche.cm', 'phone': '699000000', 'username': 'helene', 'password': 'Helene2026',
                                'password_confirm': 'Helene2026'})
pres.post('/members/add', data={'first_name': 'Paul', 'last_name': 'Ndongo', 'email': 'paul@fiche.cm', 'phone': '699111111',
                                'username': 'paul', 'role': 'MEMBRE', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='fiche').one().id
    paul = Member.query.filter_by(tontine_id=tid, first_name='Paul').one().id

# ---------------------------------------------------------------- formulaire de saisie
r = pres.get('/transactions/add')
h = body(r)
check(r.status_code == 200, 'page de saisie accessible')
script = h[h.rindex('<script>'):]
check('5100' not in script and '20200' not in script, "le formulaire n'impose plus d'anciens montants figés (5 100 / 10 200 / 20 200)")
check("rendu en fin d'exercice" in h and "PAS le fonds de caisse" in h, "le formulaire explique la différence épargne / fonds de caisse")

for typ, amount, desc in [('TONTINE', 12000, 'Tour 1'), ('EPARGNE', 5000, ''), ('FONDS_CAISSE', 5000, 'Fonds annuel')]:
    pres.post('/transactions/add', data={'member_id': paul, 'type': typ, 'amount': amount, 'payment_mode': 'ESPECE',
                                         'description': desc})
with app.app_context():
    check(Transaction.query.filter_by(member_id=paul, type='TONTINE', amount=12000).count() == 1,
          'une cotisation tontine de 12 000 est acceptée')

# ---------------------------------------------------------------- fiche membre
h = body(pres.get(f'/members/{paul}'))
check('<th>Détail</th>' in h, 'le tableau des transactions a une colonne « Détail »')
check("rendu en fin d'exercice" in h, "une épargne sans description affiche son explication")
check('Tour 1' in h and 'Saisi par helene' in h, 'la description et l\'auteur de la saisie sont affichés')
summary = h[h.index('id="fundSummary"'):] if 'id="fundSummary"' in h else ''
check('Épargne personnelle (restituable)' in summary and '5 000 FCFA' in summary and '12 000 FCFA' in summary,
      'la fiche sépare tontine, fonds de caisse et épargne restituable')

membre = app.test_client()
membre.post('/login', data={'tontine': 'fiche', 'username': 'paul', 'password': 'Passw0rd1'})
check(membre.get(f'/members/{paul}').status_code == 200, 'le membre voit sa propre fiche')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
