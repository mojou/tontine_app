"""Caisse : les chiffres suivent l'année choisie ; pas de signes « + / − » incompréhensibles."""
import html
import os
import re
import sys
from datetime import date
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'ca.db').replace(os.sep, '/')
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


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Caisse', 'slug': 'caisse', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@caisse.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})
pres.post('/members/add', data={'first_name': 'Marc', 'last_name': 'Test', 'email': 'marc@caisse.cm', 'phone': '699111220',
                                'username': 'marc', 'role': 'MEMBRE', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
this_year = date.today().year
last_year = this_year - 1
with app.app_context():
    tid = Tontine.query.filter_by(slug='caisse').one().id
    marc = Member.query.filter_by(tontine_id=tid, first_name='Marc').one().id

    def tx(kind, amount, day):
        db.session.add(Transaction(tontine_id=tid, member_id=marc, type=kind, amount=Decimal(amount), date=day,
                                   description='test', payment_mode='ESPECE'))
    tx('EPARGNE', 30000, date(last_year, 3, 1))           # l'an dernier : 30 000 d'épargne
    tx('PRESENCE', 2000, date(last_year, 3, 1))
    tx('EPARGNE', 5000, date(this_year, 1, 15))           # cette année : 5 000 d'épargne, 10 000 rendus
    tx('RETRAIT_EPARGNE', 10000, date(this_year, 2, 1))
    tx('DEPENSE', 7000, date(this_year, 2, 1))            # dépense > ce qui est entré en caisse générale
    db.session.commit()

old = text(pres.get(f'/cotisations?year={last_year}'))
new = text(pres.get(f'/cotisations?year={this_year}'))
check(old != new, "changer d'année change bien les chiffres")
check(f"Chiffres de l'année {last_year}" in old and f'Total en caisse au 31/12/{last_year} 32 000' in old,
      f'{last_year} : 32 000 en caisse au 31 décembre')
check("Total en caisse aujourd'hui 20 000" in new and 'Au 1 er janvier : 32 000' in new,
      f"{this_year} : part des 32 000 de l'an dernier, il reste 20 000")
check('Épargne des membres 25 000' in new and 'Entré : 5 000' in new and 'Sorti : 10 000' in new,
      'épargne : 30 000 + 5 000 − 10 000 = 25 000, écrit avec des mots (Entré / Sorti)')
check('Caisse générale Manque 5 000' in new and '« Manque »' in new,
      'caisse générale : 2 000 − 7 000 affiché « Manque 5 000 » avec une explication, pas « -5 000 »')
check(' / −' not in new and '+0' not in new, 'plus de signes « + / − » sous les montants')
check(f'<option value="{last_year}"' in pres.get('/cotisations').get_data(as_text=True), "l'année passée est proposée dans la liste")

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
